from __future__ import annotations

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest

from dripcut.auth.models import AuthUser
from dripcut.core.errors import SocialProviderError, ValidationError
from dripcut.core.events import EventBus
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.services.social_service import SocialScheduleService
from dripcut.social.models import (
    OAuthResult,
    PublishResult,
    ScheduledPost,
    SocialCredentials,
    SocialSchedule,
)
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


def test_youtube_oauth_defaults_to_minimum_upload_and_channel_scopes(monkeypatch) -> None:
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

    assert query["scope"] == [
        "https://www.googleapis.com/auth/youtube.upload "
        "https://www.googleapis.com/auth/youtube.readonly"
    ]
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


def test_youtube_oauth_requires_refresh_token_for_scheduling() -> None:
    class Client:
        def post(self, *_args, **_kwargs):
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})

    provider = YouTubeProvider("client-id", "client-secret", client=Client())  # type: ignore[arg-type]

    with pytest.raises(SocialProviderError, match="durable YouTube access"):
        provider.exchange_code(code="code", redirect_uri="https://example.test/callback")


def test_youtube_oauth_persists_channel_identity_and_avatar() -> None:
    class Client:
        def post(self, *_args, **_kwargs):
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": "https://www.googleapis.com/auth/youtube.upload",
                },
            )

        def get(self, *_args, **_kwargs):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "channel-1",
                            "snippet": {
                                "title": "Creator channel",
                                "thumbnails": {"high": {"url": "https://img.example/avatar.jpg"}},
                            },
                        }
                    ]
                },
            )

    provider = YouTubeProvider("client-id", "client-secret", client=Client())  # type: ignore[arg-type]
    result = provider.exchange_code(code="code", redirect_uri="https://example.test/callback")

    assert result.external_account_id == "channel-1"
    assert result.display_name == "Creator channel"
    assert result.credentials.refresh_token == "refresh"
    assert result.credentials.extra == {
        "channel_id": "channel-1",
        "avatar_url": "https://img.example/avatar.jpg",
    }


def test_youtube_future_publish_uses_private_upload_and_utc_publish_at(tmp_path) -> None:
    calls: list[dict[str, object]] = []

    class Client:
        def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return httpx.Response(200, headers={"location": "https://upload.example/session"})

        def put(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return httpx.Response(200, json={"id": "video-1"})

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    provider = YouTubeProvider("client-id", "client-secret", client=Client())  # type: ignore[arg-type]
    result = provider.publish(
        SocialCredentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime.now(UTC).timestamp() + 3600,
        ),
        video_path=video,
        media_url=None,
        title="Scheduled Short",
        caption="Description",
        publish_at="2026-09-21T12:30:00Z",
        privacy="public",
    )

    metadata = calls[0]["json"]
    assert isinstance(metadata, dict)
    assert metadata["status"] == {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
        "publishAt": "2026-09-21T12:30:00Z",
    }
    assert result.status == "scheduled_on_youtube"
    assert result.external_post_id == "video-1"


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
    # Both platforms publish each clip in the same slot; the interval advances
    # between clips rather than between platforms.
    assert schedule.posts[1].publish_at.startswith("2026-08-22T18:00")
    assert schedule.posts[2].publish_at.startswith("2026-08-22T18:30")
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
                publish_at=None,
                privacy="private",
            ):
            del media_url, title, caption, publish_at, privacy
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


def test_selected_clip_schedule_is_timezone_safe_and_queued_immediately(paths) -> None:
    published: list[dict[str, object]] = []

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
                credentials=SocialCredentials(
                    access_token="access",
                    refresh_token="refresh",
                    extra={"channel_id": "channel-1"},
                ),
            )

        def publish(self, credentials, **kwargs):
            assert credentials.refresh_token == "refresh"
            published.append(kwargs)
            return PublishResult(
                external_post_id="video-1",
                url="https://youtube.example/video-1",
                status="scheduled_on_youtube",
            )

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
    )
    state = service.begin_oauth(
        "youtube", principal, redirect_uri="https://dripcut.example/api/social/youtube/callback"
    ).split("state=", 1)[1].split("&", 1)[0]
    service.complete_oauth(
        "youtube",
        principal,
        code="code",
        state=state,
        redirect_uri="https://dripcut.example/api/social/youtube/callback",
    )
    clip = paths.temp / "selected.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"video")
    local_time = (
        datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata"))
        .replace(tzinfo=None, second=0, microsecond=0)
        + timedelta(minutes=10)
    ).isoformat(timespec="minutes")

    schedule = service.create_schedule_for_clips(
        clip_assets=[("artifact-1", "selected.mp4", str(clip))],
        project_id="project-1",
        platforms=["youtube"],
        interval_minutes=1440,
        start_at=local_time,
        caption="Description",
        title="Scheduled title",
        description="Description",
        privacy="public",
        timezone="Asia/Kolkata",
        publish_mode="schedule",
        require_connected=True,
        principal=principal,
    )

    assert queue.wait(timeout=5)
    persisted = service.get_schedule(schedule.id, principal)
    post = persisted.posts[0]
    assert post.artifact_id == "artifact-1"
    assert post.social_connection_id
    assert post.timezone == "Asia/Kolkata"
    assert post.status == "scheduled_on_youtube"
    assert post.external_post_id == "video-1"
    assert published[0]["publish_at"].endswith("Z")  # type: ignore[union-attr]
    assert published[0]["privacy"] == "public"
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


def test_future_instagram_posts_wait_while_youtube_uses_native_scheduling(paths) -> None:
    store = LocalSocialStore(paths.projects / "social-due-platforms")
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    schedule = SocialSchedule(
        id="schedule-platforms",
        project_id="project-1",
        archive="object://clips/source.mp4",
        archive_name="source.mp4",
        created_at=datetime.now(UTC).timestamp(),
        posts=[
            ScheduledPost(platform="instagram", clip_name="clip.mp4", publish_at=future, caption="Reel", status="scheduled", schedule_id="schedule-platforms"),
            ScheduledPost(platform="youtube", clip_name="clip.mp4", publish_at=future, caption="Short", status="scheduled", schedule_id="schedule-platforms", privacy="public", publish_mode="schedule"),
        ],
    )
    store.save_schedule(schedule)

    due = store.due_posts(datetime.now(UTC))

    assert [post.platform for post in due] == ["youtube"]


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
