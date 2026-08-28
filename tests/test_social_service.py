from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from dripcut.auth.models import AuthUser
from dripcut.core.errors import ValidationError
from dripcut.core.events import EventBus
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.services.social_service import SocialScheduleService
from dripcut.social.models import OAuthResult, PublishResult, SocialCredentials
from dripcut.social.store import LocalSocialStore
from dripcut.tenancy.models import Principal


def _write_last_render(paths, archive) -> None:
    paths.cache.mkdir(parents=True, exist_ok=True)
    (paths.cache / "last_render.json").write_text(
        (
            "{"
            f'"archive": "{archive}",'
            '"source": "demo.mp4",'
            '"clip_count": 2,'
            '"status": "Done"'
            "}"
        ),
        encoding="utf-8",
    )


def test_social_connections_read_environment(paths, monkeypatch) -> None:
    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_ID", "id")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_SECRET", "secret")
    service = SocialScheduleService(paths)

    status = service.connection_map()
    assert status["youtube"].configured
    assert not status["youtube"].connected
    assert not status["instagram"].connected


def test_create_schedule_from_latest_zip(paths) -> None:
    archive = paths.cache / "clips.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("clip-001.mp4", b"one")
        zipped.writestr("clip-002.mp4", b"two")
    _write_last_render(paths, archive)

    service = SocialScheduleService(paths)
    schedule = service.create_schedule(
        platforms=["instagram", "youtube"],
        interval_minutes=30,
        start_at="2026-08-22 18:00",
        caption="{clip} for {platform}",
    )

    assert schedule.archive_name == "clips.zip"
    assert len(schedule.posts) == 4
    assert schedule.posts[0].platform == "instagram"
    assert schedule.posts[0].publish_at.startswith("2026-08-22T18:00")
    assert schedule.posts[1].platform == "youtube"
    assert schedule.posts[1].publish_at.startswith("2026-08-22T18:30")
    assert "clip-001" in schedule.posts[0].caption
    assert service.latest_schedule() is not None


def test_create_schedule_requires_latest_zip(paths) -> None:
    service = SocialScheduleService(paths)

    with pytest.raises(ValidationError):
        service.create_schedule(
            platforms=["youtube"],
            interval_minutes=30,
            start_at="now",
            caption="{clip}",
        )


def test_oauth_credentials_are_encrypted_and_state_is_one_time(paths) -> None:
    class FakeProvider:
        platform = "youtube"
        label = "YouTube Shorts"
        configured = True

        def authorization_url(self, *, state, redirect_uri):
            return f"https://accounts.example/authorize?state={state}&redirect={redirect_uri}"

        def exchange_code(self, *, code, redirect_uri):
            assert code == "authorization-code"
            assert redirect_uri.endswith("/callback")
            return OAuthResult(
                external_account_id="channel-1",
                display_name="Creator channel",
                credentials=SocialCredentials(
                    access_token="plain-access-token",
                    refresh_token="plain-refresh-token",
                ),
            )

        def publish(self, credentials, **_kwargs):
            return PublishResult(external_post_id="unused")

    principal = Principal(
        user=AuthUser(id="user-1", email="creator@example.com", name="Creator"),
        workspace_id="workspace-1",
        role="owner",
        access_token="session-token",
    )
    service = SocialScheduleService(paths, providers={"youtube": FakeProvider()})
    url = service.begin_oauth(
        "youtube", principal, redirect_uri="https://api.example/social/callback"
    )
    state = url.split("state=", 1)[1].split("&", 1)[0]
    connected = service.complete_oauth(
        "youtube",
        principal,
        code="authorization-code",
        state=state,
        redirect_uri="https://api.example/social/callback",
    )

    assert connected.connected
    database = (paths.projects / "social" / "social.json").read_text(encoding="utf-8")
    assert "plain-access-token" not in database
    assert "plain-refresh-token" not in database
    with pytest.raises(Exception, match="already used"):
        service.complete_oauth(
            "youtube",
            principal,
            code="authorization-code",
            state=state,
            redirect_uri="https://api.example/social/callback",
        )


def test_due_social_post_publishes_through_durable_queue(paths) -> None:
    class FakeProvider:
        platform = "youtube"
        label = "YouTube Shorts"
        configured = True

        def authorization_url(self, *, state, redirect_uri):
            return f"https://accounts.example/?state={state}&redirect={redirect_uri}"

        def exchange_code(self, *, code, redirect_uri):
            del code, redirect_uri
            return OAuthResult(
                external_account_id="channel-1",
                display_name="Creator channel",
                credentials=SocialCredentials(access_token="secret-token"),
            )

        def publish(
            self,
            credentials,
            *,
            video_path: Path,
            media_url,
            title,
            caption,
        ):
            del media_url, title, caption
            assert credentials.access_token == "secret-token"
            assert video_path.read_bytes() == b"video"
            return PublishResult(external_post_id="youtube-video-1")

    principal = Principal(
        user=AuthUser(id="user-1", email="creator@example.com", name="Creator"),
        workspace_id="workspace-1",
        role="owner",
        access_token="session-token",
    )
    queue = LocalJobQueue(EventBus(), history_file=paths.history_file)
    service = SocialScheduleService(
        paths,
        queue=queue,
        providers={"youtube": FakeProvider()},
        poll_interval=60,
    )
    state = service.begin_oauth(
        "youtube", principal, redirect_uri="https://api.example/callback"
    ).split("state=", 1)[1].split("&", 1)[0]
    service.complete_oauth(
        "youtube",
        principal,
        code="code",
        state=state,
        redirect_uri="https://api.example/callback",
    )
    archive = paths.cache / "publish.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("clip-001.mp4", b"video")

    schedule = service.create_schedule_for_archive(
        archive=archive,
        project_id="project-1",
        platforms=["youtube"],
        interval_minutes=30,
        start_at="2020-01-01T00:00:00+00:00",
        caption="Ready",
        principal=principal,
    )

    assert queue.wait(timeout=5)
    persisted = service.latest_schedule(principal)
    assert persisted is not None
    assert persisted.id == schedule.id
    assert persisted.posts[0].status == "published"
    assert persisted.posts[0].external_post_id == "youtube-video-1"
    queue.shutdown()


def test_social_store_recovers_posts_interrupted_during_upload(paths) -> None:
    store = LocalSocialStore(paths.projects / "social-recovery")
    service = SocialScheduleService(paths, store=store)
    archive = paths.cache / "recovery.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("clip.mp4", b"video")
    schedule = service.create_schedule_for_archive(
        archive=archive,
        project_id="project-1",
        platforms=["youtube"],
        interval_minutes=30,
        start_at="2026-09-01T00:00:00+00:00",
        caption="Ready",
    )
    post = schedule.posts[0]
    post.status = "uploading"
    store.update_post(post)

    assert store.recover_interrupted_posts() == 1
    recovered = store.schedule("local", schedule.id)
    assert recovered is not None
    assert recovered.posts[0].status == "scheduled"
