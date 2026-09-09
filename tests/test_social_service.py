from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from dripcut.auth.models import AuthUser
from dripcut.core.errors import ValidationError
from dripcut.core.events import EventBus
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.services.social_service import SocialScheduleService
from dripcut.social.models import OAuthResult, PublishResult, ScheduledPost, SocialCredentials
from dripcut.social.providers import YouTubeProvider
from dripcut.social.store import LocalSocialStore, SupabaseSocialStore
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


def test_youtube_oauth_defaults_to_upload_only_scope(monkeypatch) -> None:
    monkeypatch.delenv("DRIPCUT_YOUTUBE_SCOPES", raising=False)
    provider = YouTubeProvider("client-id", "client-secret")

    query = parse_qs(
        urlparse(
            provider.authorization_url(
                state="signed-state",
                redirect_uri="http://127.0.0.1:8000/api/social/youtube/callback",
            )
        ).query
    )

    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.upload"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


def test_youtube_oauth_scopes_can_be_overridden_for_provider_requirements(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_ID", "client-id")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "DRIPCUT_YOUTUBE_SCOPES",
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.readonly",
    )

    provider = YouTubeProvider.from_environment()

    assert provider.scopes == (
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    )


def test_official_social_providers_expose_truthful_capabilities(paths) -> None:
    service = SocialScheduleService(paths)
    capabilities = {item.platform: item for item in service.capabilities()}

    assert set(capabilities) == {"youtube", "instagram"}
    assert capabilities["youtube"].can_upload_video
    assert capabilities["youtube"].can_publish_short
    assert capabilities["youtube"].can_schedule
    assert not capabilities["youtube"].can_fetch_analytics
    assert capabilities["instagram"].supported_content_types == ("video_clip",)
    assert "9:16" in capabilities["instagram"].supported_aspect_ratios


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


def test_dispatch_due_scopes_manual_dispatch_to_current_workspace(paths) -> None:
    class FakeStore:
        supports_background_worker = True

        def due_posts(self, now):
            assert isinstance(now, datetime)
            return [
                ScheduledPost(
                    schedule_id="schedule-1",
                    workspace_id="workspace-1",
                    owner_id="user-1",
                    project_id="project-1",
                    platform="youtube",
                    clip_name="clip-1.mp4",
                    archive="clips.zip",
                    publish_at="2020-01-01T00:00:00+00:00",
                    caption="one",
                ),
                ScheduledPost(
                    schedule_id="schedule-2",
                    workspace_id="workspace-2",
                    owner_id="user-2",
                    project_id="project-2",
                    platform="youtube",
                    clip_name="clip-2.mp4",
                    archive="clips.zip",
                    publish_at="2020-01-01T00:00:00+00:00",
                    caption="two",
                ),
            ]

        def account(self, *args, **kwargs):
            return None

        def update_post(self, *args, **kwargs):
            return None

    principal = Principal(
        user=AuthUser(id="user-1", email="creator@example.com", name="Creator"),
        workspace_id="workspace-1",
        role="owner",
        access_token="session-token",
    )
    queue = LocalJobQueue(EventBus(), history_file=paths.history_file)
    service = SocialScheduleService(paths, queue=queue, store=FakeStore())
    enqueued: list[ScheduledPost] = []
    service._enqueue = lambda post, *, access_token="": enqueued.append(post)  # type: ignore[method-assign]

    assert service.dispatch_due(principal=principal) == 1
    assert [post.workspace_id for post in enqueued] == ["workspace-1"]
    queue.shutdown()


def test_supabase_update_post_persists_publish_time_and_archive_metadata(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    store = SupabaseSocialStore("https://example.supabase.co", "anon", "service")

    def capture_request(method, path, payload=None, **kwargs):
        calls.append({"method": method, "path": path, "payload": payload, **kwargs})

    monkeypatch.setattr(store, "_request", capture_request)
    post = ScheduledPost(
        id="post-1",
        schedule_id="schedule-1",
        workspace_id="workspace-1",
        owner_id="user-1",
        project_id="project-1",
        platform="youtube",
        clip_name="clip-001.mp4",
        archive="/tmp/dripcut/final-clips.zip",
        publish_at=datetime(2026, 8, 30, 10, 30, tzinfo=UTC).isoformat(),
        caption="Ready",
        title="clip-001",
        status="scheduled",
    )

    store.update_post(post, access_token="user-token")

    payload = calls[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["publish_at"] == "2026-08-30T10:30:00+00:00"
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["archive_name"] == "final-clips.zip"
    assert metadata["schedule_id"] == "schedule-1"


@pytest.mark.parametrize("caller_token", ["", "user-session-jwt", "legacy-service-jwt"])
def test_supabase_secret_api_key_does_not_replace_caller_identity(monkeypatch, caller_token) -> None:
    import io

    service_key = "sb_secret_" + "test-only-placeholder"
    store = SupabaseSocialStore("https://example.supabase.co", "public-key", service_key)
    observed = []

    def respond(request, **kwargs):
        observed.append(request)
        return io.BytesIO(b"[]")

    monkeypatch.setattr("dripcut.social.store.urlopen", respond)
    store._request("GET", "/rest/v1/scheduled_posts", access_token=caller_token)
    request = observed[0]
    if caller_token:
        assert request.get_header("Apikey") == "public-key"
        assert request.get_header("Authorization") == f"Bearer {caller_token}"
    else:
        assert request.get_header("Apikey") == service_key
        assert request.get_header("Authorization") is None
