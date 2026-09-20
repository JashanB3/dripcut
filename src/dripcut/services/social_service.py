"""Official social OAuth, durable schedules, and worker-based publishing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dripcut.core.errors import SocialProviderError, ValidationError
from dripcut.core.paths import AppPaths
from dripcut.engines.export.queue import JobQueue
from dripcut.models.job import Job, JobKind, JobResult
from dripcut.social.crypto import CredentialCipher
from dripcut.social.models import (
    PlatformName,
    ProviderCapabilities,
    ScheduledPost,
    SocialAccount,
    SocialCredentials,
    SocialSchedule,
)
from dripcut.social.providers import InstagramProvider, SocialProvider, YouTubeProvider
from dripcut.social.store import LocalSocialStore, SocialStore
from dripcut.storage.provider import StorageProvider
from dripcut.tenancy.models import Principal
from dripcut.utils.fs import ensure_dir, human_size, safe_filename

__all__ = [
    "PlatformName",
    "SocialConnection",
    "ScheduledPost",
    "SocialSchedule",
    "SocialScheduleService",
]


@dataclass(frozen=True, slots=True)
class SocialConnection:
    platform: PlatformName
    label: str
    connected: bool
    configured: bool
    detail: str
    setup_hint: str
    channel_id: str = ""
    avatar_url: str = ""


class _OAuthStateSigner:
    """Short-lived signed OAuth state bound to one authenticated workspace."""

    def __init__(self, key_file: Path) -> None:
        configured = os.environ.get("DRIPCUT_OAUTH_STATE_SECRET", "").strip()
        if configured:
            self._key = configured.encode("utf-8")
        else:
            key_file.parent.mkdir(parents=True, exist_ok=True)
            if not key_file.exists():
                key_file.write_bytes(secrets.token_bytes(32))
                key_file.chmod(0o600)
            self._key = key_file.read_bytes()
        self._used: set[str] = set()
        self._lock = threading.Lock()

    def issue(self, principal: Principal, platform: PlatformName) -> str:
        payload = {
            "user_id": principal.user.id,
            "workspace_id": principal.workspace_id,
            "platform": platform,
            "expires_at": int(time.time()) + 600,
            "nonce": secrets.token_urlsafe(18),
        }
        encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64(hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def consume(
        self, state: str, principal: Principal, platform: PlatformName
    ) -> dict[str, Any]:
        try:
            encoded, supplied = state.split(".", 1)
            expected = _b64(
                hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied, expected):
                raise ValueError
            payload = json.loads(_unb64(encoded))
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise SocialProviderError(
                "The social connection request is invalid.", hint="Start the connection again."
            ) from error
        nonce = str(payload.get("nonce") or "")
        with self._lock:
            if not nonce or nonce in self._used:
                raise SocialProviderError("This social connection request was already used.")
            if int(payload.get("expires_at") or 0) < int(time.time()):
                raise SocialProviderError("This social connection request expired.")
            if (
                payload.get("user_id") != principal.user.id
                or payload.get("workspace_id") != principal.workspace_id
                or payload.get("platform") != platform
            ):
                raise SocialProviderError("This social connection belongs to another workspace.")
            self._used.add(nonce)
        return payload


class SocialScheduleService:
    """Coordinate official providers without exposing credentials to the browser."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        queue: JobQueue | None = None,
        store: SocialStore | None = None,
        storage: StorageProvider | None = None,
        providers: dict[PlatformName, SocialProvider] | None = None,
        cipher: CredentialCipher | None = None,
        poll_interval: float = 15.0,
    ) -> None:
        self.paths = paths
        self.queue = queue
        self.store = store or LocalSocialStore(paths.projects / "social")
        self.storage = storage
        self.providers = providers or {
            "youtube": YouTubeProvider.from_environment(),
            "instagram": InstagramProvider.from_environment(),
        }
        self.cipher = cipher or CredentialCipher.from_environment(
            paths.home / "secrets" / "social-credentials.key"
        )
        self.state = _OAuthStateSigner(paths.home / "secrets" / "oauth-state.key")
        self.poll_interval = max(1.0, poll_interval)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def start_worker(self) -> None:
        if (
            self.queue is None
            or not self.store.supports_background_worker
            or self._worker is not None
        ):
            return
        self._stop.clear()
        self.store.recover_interrupted_posts()
        self.dispatch_due()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="dripcut-social-scheduler",
            daemon=True,
        )
        self._worker.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=min(2.0, self.poll_interval + 0.25))
            self._worker = None

    def begin_oauth(
        self, platform: PlatformName, principal: Principal, *, redirect_uri: str
    ) -> str:
        provider = self._provider(platform)
        state = self.state.issue(principal, platform)
        return provider.authorization_url(state=state, redirect_uri=redirect_uri)

    def complete_oauth(
        self,
        platform: PlatformName,
        principal: Principal,
        *,
        code: str,
        state: str,
        redirect_uri: str,
    ) -> SocialConnection:
        self.state.consume(state, principal, platform)
        provider = self._provider(platform)
        result = provider.exchange_code(code=code, redirect_uri=redirect_uri)
        encrypted = self.cipher.encrypt(result.credentials.to_dict())
        account = SocialAccount(
            workspace_id=principal.workspace_id,
            owner_id=principal.user.id,
            platform=platform,
            external_account_id=result.external_account_id,
            display_name=result.display_name,
            encrypted_credentials=encrypted,
            scopes=result.credentials.scopes,
            token_expires_at=result.credentials.expires_at,
        )
        self.store.save_account(account, access_token=principal.access_token)
        return self._connection(provider, account)

    def disconnect(self, platform: PlatformName, principal: Principal) -> None:
        account = self.store.account(
            principal.workspace_id,
            platform,
            access_token=principal.access_token,
        )
        if account is not None:
            try:
                credentials = SocialCredentials.from_dict(
                    self.cipher.decrypt(account.encrypted_credentials)
                )
                revoke = getattr(self._provider(platform), "revoke", None)
                if callable(revoke):
                    revoke(credentials)
            except Exception:
                # Removing the local credential must still succeed when the provider
                # is unavailable or has already revoked the token.
                pass
        self.store.delete_account(
            principal.workspace_id,
            platform,
            access_token=principal.access_token,
        )

    def connections(self, principal: Principal | None = None) -> list[SocialConnection]:
        workspace_id, access_token = _identity(principal)
        return [
            self._connection(
                provider,
                self.store.account(
                    workspace_id,
                    platform,
                    access_token=access_token,
                ),
            )
            for platform, provider in self.providers.items()
        ]

    def connection_map(
        self, principal: Principal | None = None
    ) -> dict[PlatformName, SocialConnection]:
        return {item.platform: item for item in self.connections(principal)}

    def capabilities(self) -> list[ProviderCapabilities]:
        return [provider.capabilities() for provider in self.providers.values()]

    def create_schedule(
        self,
        *,
        platforms: list[str],
        interval_minutes: int,
        start_at: str,
        caption: str,
        principal: Principal | None = None,
    ) -> SocialSchedule:
        latest = self.latest_render()
        if latest is None:
            raise ValidationError("Create clips first, then schedule the finished ZIP.")
        return self.create_schedule_for_archive(
            archive=Path(str(latest.get("archive", ""))),
            project_id=str(latest.get("project_id", "legacy")),
            platforms=platforms,
            interval_minutes=interval_minutes,
            start_at=start_at,
            caption=caption,
            principal=principal,
        )

    def create_schedule_for_archive(
        self,
        *,
        archive: Path,
        project_id: str,
        platforms: list[str],
        interval_minutes: int,
        start_at: str,
        caption: str,
        principal: Principal | None = None,
    ) -> SocialSchedule:
        clips = self.clips_in_archive(archive)
        return self._create_schedule_for_assets(
            clip_assets=[(clip, str(archive)) for clip in clips],
            archive_label=archive.name,
            project_id=project_id,
            platforms=platforms,
            interval_minutes=interval_minutes,
            start_at=start_at,
            caption=caption,
            principal=principal,
        )

    def create_schedule_for_clips(
        self,
        *,
        clip_assets: list[tuple[str, str] | tuple[str, str, str]],
        project_id: str,
        platforms: list[str],
        interval_minutes: int,
        start_at: str,
        caption: str,
        title: str = "",
        description: str = "",
        privacy: str = "private",
        timezone: str = "UTC",
        publish_mode: str = "schedule",
        require_connected: bool = False,
        principal: Principal | None = None,
    ) -> SocialSchedule:
        """Schedule durable object-store clips without building a duplicate ZIP."""
        if not clip_assets:
            raise ValidationError("Create clips before scheduling posts.")
        return self._create_schedule_for_assets(
            clip_assets=clip_assets,
            archive_label=f"{len(clip_assets)} stored clips",
            project_id=project_id,
            platforms=platforms,
            interval_minutes=interval_minutes,
            start_at=start_at,
            caption=caption,
            title=title,
            description=description,
            privacy=privacy,
            timezone=timezone,
            publish_mode=publish_mode,
            require_connected=require_connected,
            principal=principal,
        )

    def _create_schedule_for_assets(
        self,
        *,
        clip_assets: list[tuple[str, str] | tuple[str, str, str]],
        archive_label: str,
        project_id: str,
        platforms: list[str],
        interval_minutes: int,
        start_at: str,
        caption: str,
        title: str = "",
        description: str = "",
        privacy: str = "private",
        timezone: str = "UTC",
        publish_mode: str = "schedule",
        require_connected: bool = False,
        principal: Principal | None = None,
    ) -> SocialSchedule:
        selected = [item for item in platforms if item in {"instagram", "youtube"}]
        if not selected:
            raise ValidationError("Choose Instagram, YouTube, or both.")
        if interval_minutes < 5:
            raise ValidationError("Use at least 5 minutes between posts.")
        if privacy not in {"private", "unlisted", "public"}:
            raise ValidationError("Choose Private, Unlisted, or Public visibility.")
        if publish_mode not in {"now", "schedule"}:
            raise ValidationError("Choose Publish now or Schedule.")
        start = self._parse_start(start_at, timezone=timezone)
        if publish_mode == "schedule" and require_connected:
            if privacy != "public":
                raise ValidationError(
                    "YouTube scheduled publishing requires Public visibility.",
                    hint="Choose Public, or use Publish now with Private or Unlisted visibility.",
                )
            if start <= datetime.now(UTC) + timedelta(seconds=30):
                raise ValidationError("Choose a publish time at least one minute in the future.")
        elif publish_mode == "now":
            start = datetime.now(UTC)
        template = (caption or "").strip() or "{clip} #shorts #reels"
        workspace_id, access_token = _identity(principal)
        owner_id = principal.user.id if principal else "local"
        schedule_id = str(uuid4())
        accounts = {
            platform: self.store.account(
                workspace_id,
                platform,  # type: ignore[arg-type]
                access_token=access_token,
            )
            for platform in selected
        }
        if require_connected:
            disconnected = [platform for platform, account in accounts.items() if account is None]
            if disconnected:
                raise ValidationError(
                    f"{disconnected[0].title()} is not connected.",
                    hint=f"Connect {disconnected[0].title()} before scheduling this clip.",
                )
        posts: list[ScheduledPost] = []
        slot = 0
        normalized_assets = [
            ("", item[0], item[1]) if len(item) == 2 else (item[0], item[1], item[2])
            for item in clip_assets
        ]
        for artifact_id, clip, asset_reference in normalized_assets:
            clean_name = Path(clip).stem
            for platform in selected:
                publish_at = start + timedelta(minutes=interval_minutes * slot)
                account = accounts[platform]
                post_title = (title.strip() or clean_name)[:100]
                rendered_caption = template.replace("{clip}", clean_name).replace(
                    "{platform}", platform
                )
                post_description = (description.strip() or rendered_caption)[:5000]
                posts.append(
                    ScheduledPost(
                        schedule_id=schedule_id,
                        workspace_id=workspace_id,
                        owner_id=owner_id,
                        project_id=project_id,
                        platform=platform,  # type: ignore[arg-type]
                        clip_name=clip,
                        archive=asset_reference,
                        publish_at=publish_at.isoformat(timespec="minutes"),
                        caption=post_description,
                        title=post_title,
                        artifact_id=artifact_id,
                        social_connection_id=account.id if account else "",
                        description=post_description,
                        privacy=privacy,
                        timezone=timezone,
                        publish_mode=publish_mode,
                        status="scheduled" if account else "draft",
                    )
                )
                slot += 1
        schedule = SocialSchedule(
            id=schedule_id,
            project_id=project_id,
            archive=normalized_assets[0][2],
            archive_name=archive_label,
            created_at=time.time(),
            posts=posts,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        self.store.save_schedule(schedule, access_token=access_token)
        if require_connected:
            for post in posts:
                self._enqueue(post, access_token=access_token)
        else:
            self.dispatch_due(principal=principal)
        return schedule

    def latest_schedule(self, principal: Principal | None = None) -> SocialSchedule | None:
        workspace_id, access_token = _identity(principal)
        return self.store.latest_schedule(workspace_id, access_token=access_token)

    def get_schedule(
        self, schedule_id: str, principal: Principal | None = None
    ) -> SocialSchedule:
        workspace_id, access_token = _identity(principal)
        schedule = self.store.schedule(
            workspace_id,
            schedule_id,
            access_token=access_token,
        )
        if schedule is None:
            raise ValidationError("That schedule could not be found.")
        return schedule

    def update_scheduled_post(
        self,
        schedule_id: str,
        post_id: str,
        *,
        publish_at: str | None,
        caption: str | None,
        principal: Principal | None = None,
    ) -> SocialSchedule:
        schedule = self.get_schedule(schedule_id, principal)
        post = next((item for item in schedule.posts if item.id == post_id), None)
        if post is None:
            raise ValidationError("That scheduled post could not be found.")
        if post.status in {"uploading", "published"}:
            raise ValidationError("This post has already started publishing.")
        if publish_at is not None:
            post.publish_at = self._parse_start(publish_at).isoformat(timespec="minutes")
        if caption is not None:
            post.caption = caption.strip()
        account = self.store.account(
            schedule.workspace_id,
            post.platform,
            access_token=principal.access_token if principal else "",
        )
        post.status = "scheduled" if account else "draft"
        post.error_message = None
        self.store.update_post(
            post,
            access_token=principal.access_token if principal else "",
        )
        self.dispatch_due(principal=principal)
        return schedule

    def dispatch_due(self, *, principal: Principal | None = None) -> int:
        if self.queue is None:
            return 0
        token = principal.access_token if principal else ""
        due = self.store.due_posts(datetime.now(UTC))
        if principal is not None:
            due = [post for post in due if post.workspace_id == principal.workspace_id]
        for post in due:
            self._enqueue(post, access_token=token)
        return len(due)

    def latest_render(self) -> dict[str, object] | None:
        path = self.paths.cache / "last_render.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        archive = Path(str(data.get("archive", "")))
        return data if archive.exists() else None

    @staticmethod
    def clips_in_archive(archive: str | Path) -> list[str]:
        path = Path(archive)
        if not path.exists():
            raise ValidationError("Create a ZIP before scheduling posts.")
        try:
            with zipfile.ZipFile(path) as zipped:
                names = [
                    name
                    for name in zipped.namelist()
                    if Path(name).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
                    and not name.endswith("/")
                ]
        except zipfile.BadZipFile as error:
            raise ValidationError("The latest ZIP could not be opened.") from error
        if not names:
            raise ValidationError("The latest ZIP has no video clips to schedule.")
        return sorted(names)

    def latest_summary(self) -> dict[str, object]:
        latest = self.latest_render()
        if latest is None:
            return {"ready": False, "detail": "No ZIP ready yet."}
        archive = Path(str(latest.get("archive", "")))
        return {
            "ready": True,
            "archive": str(archive),
            "archive_name": archive.name,
            "size": human_size(archive.stat().st_size),
            "clips": len(self.clips_in_archive(archive)),
        }

    def _worker_loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                self.dispatch_due()
            except Exception:
                continue

    def _enqueue(self, post: ScheduledPost, *, access_token: str = "") -> None:
        if self.queue is None:
            return
        post.status = "uploading"
        post.error_message = None
        post.last_error_code = None
        self.store.update_post(post, access_token=access_token)

        def publish(job: Job) -> JobResult:
            try:
                post.attempt_count += 1
                self.store.update_post(post, access_token=access_token)
                job.set_progress(0.08, "Preparing clip")
                video = self._extract_clip(post)
                account = self.store.account(
                    post.workspace_id,
                    post.platform,
                    access_token=access_token,
                )
                if account is None:
                    raise SocialProviderError(
                        f"{post.platform.title()} is no longer connected."
                    )
                credentials = SocialCredentials.from_dict(
                    self.cipher.decrypt(account.encrypted_credentials)
                )
                media_url = self._publish_media_url(post, video)
                job.set_progress(0.2, f"Uploading to {post.platform.title()}")
                result = self._provider(post.platform).publish(
                    credentials,
                    video_path=video,
                    media_url=media_url,
                    title=post.title,
                    caption=post.caption,
                    publish_at=(
                        _as_utc_iso(post.publish_at)
                        if post.platform == "youtube"
                        and post.publish_mode == "schedule"
                        and post.privacy == "public"
                        else None
                    ),
                    privacy=post.privacy,
                )
                if result.credentials and result.credentials != credentials:
                    account.encrypted_credentials = self.cipher.encrypt(
                        result.credentials.to_dict()
                    )
                    account.updated_at = time.time()
                    account.scopes = result.credentials.scopes
                    account.token_expires_at = result.credentials.expires_at
                    self.store.save_account(account, access_token=access_token)
                post.status = result.status
                post.external_post_id = result.external_post_id
                post.external_url = result.url
                post.error_message = None
                post.last_error_code = None
                self.store.update_post(post, access_token=access_token)
                job.set_progress(1.0, _status_label(result.status))
                return JobResult(
                    outputs=[],
                    message=f"Published {post.clip_name} to {post.platform}.",
                    data={
                        "schedule_id": post.schedule_id,
                        "post_id": post.id,
                        "platform": post.platform,
                        "external_post_id": result.external_post_id,
                        "url": result.url,
                        "status": result.status,
                    },
                )
            except Exception as error:
                post.status = "failed"
                post.last_error_code = _safe_error_code(error)
                post.error_message = _safe_publish_error(error)
                self.store.update_post(post, access_token=access_token)
                raise

        idempotency_key = f"publish:{post.id}"
        existing = self.queue.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.status.value == "succeeded":
                post.status = str(
                    (existing.result.data.get("status") if existing.result else None)
                    or "published"
                )  # type: ignore[assignment]
                if existing.result:
                    post.external_post_id = str(
                        existing.result.data.get("external_post_id") or ""
                    ) or None
                    post.external_url = str(existing.result.data.get("url") or "") or None
                self.store.update_post(post, access_token=access_token)
            elif existing.status.is_terminal:
                self.queue.resume_callable(existing.id, publish)
            return
        self.queue.submit_callable(
            Job(
                kind=JobKind.PUBLISH,
                title=f"Publish {Path(post.clip_name).name} to {post.platform.title()}",
                run=publish,
                project_id=post.project_id,
                idempotency_key=idempotency_key,
                max_attempts=3,
                retry_backoff_seconds=5,
                metadata={
                    "schedule_id": post.schedule_id,
                    "post_id": post.id,
                    "workspace_id": post.workspace_id,
                    "platform": post.platform,
                    "artifact_id": post.artifact_id,
                },
            ),
            publish,
        )

    def _extract_clip(self, post: ScheduledPost) -> Path:
        if post.archive.startswith("object://"):
            if self.storage is None:
                raise ValidationError("Object storage is unavailable for this scheduled clip.")
            target_dir = ensure_dir(self.paths.temp / "publishing" / post.id)
            target = target_dir / safe_filename(
                Path(post.clip_name).name, fallback="clip.mp4"
            )
            try:
                return self.storage.materialize(post.archive.removeprefix("object://"), target)
            except Exception as error:
                raise ValidationError("The scheduled clip is no longer available.") from error
        archive = Path(post.archive)
        if not archive.is_file():
            raise ValidationError("The scheduled ZIP is no longer available.")
        target_dir = ensure_dir(self.paths.temp / "publishing" / post.id)
        target = target_dir / safe_filename(Path(post.clip_name).name, fallback="clip.mp4")
        if archive.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
            try:
                shutil.copyfile(archive, target)
                return target
            except OSError as error:
                raise ValidationError("The scheduled clip could not be copied.") from error
        try:
            with (
                zipfile.ZipFile(archive) as zipped,
                zipped.open(post.clip_name) as source,
                target.open("wb") as output,
            ):
                shutil.copyfileobj(source, output, length=1024 * 1024)
        except (KeyError, zipfile.BadZipFile, OSError) as error:
            raise ValidationError("The scheduled clip could not be extracted.") from error
        return target

    def _publish_media_url(self, post: ScheduledPost, video: Path) -> str | None:
        if post.platform != "instagram" or self.storage is None:
            return None
        key = f"social/{post.workspace_id}/{post.id}/{video.name}"
        self.storage.put_file(key, video, content_type="video/mp4")
        return self.storage.signed_url(key, expires_seconds=3600)

    def _provider(self, platform: PlatformName) -> SocialProvider:
        try:
            return self.providers[platform]
        except KeyError as error:
            raise ValidationError("Choose YouTube or Instagram.") from error

    def _connection(self, provider: SocialProvider, account: SocialAccount | None) -> SocialConnection:
        connected = bool(account and account.status == "connected")
        channel_id = ""
        avatar_url = ""
        if connected:
            detail = f"Connected as {account.display_name}."
            try:
                credentials = SocialCredentials.from_dict(
                    self.cipher.decrypt(account.encrypted_credentials)
                )
                channel_id = credentials.extra.get("channel_id", account.external_account_id)
                avatar_url = credentials.extra.get("avatar_url", "")
            except Exception:
                channel_id = account.external_account_id
        elif provider.configured:
            detail = "OAuth is configured. Connect an account to publish."
        else:
            detail = "The server needs official OAuth application credentials."
        hints = {
            "youtube": (
                "Set DRIPCUT_YOUTUBE_CLIENT_ID and DRIPCUT_YOUTUBE_CLIENT_SECRET."
            ),
            "instagram": "Set DRIPCUT_META_APP_ID and DRIPCUT_META_APP_SECRET.",
        }
        return SocialConnection(
            platform=provider.platform,
            label=provider.label,
            connected=connected,
            configured=provider.configured,
            detail=detail,
            setup_hint=hints[provider.platform],
            channel_id=channel_id,
            avatar_url=avatar_url,
        )

    @staticmethod
    def _parse_start(value: str, *, timezone: str = "UTC") -> datetime:
        raw = (value or "").strip()
        if not raw or raw.lower() == "now":
            return datetime.now(UTC) + timedelta(minutes=5)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
            return parsed.astimezone(UTC)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValidationError(
                "Use a valid start date and time.",
                hint="Choose the date and time from the scheduling control.",
            ) from error


def _as_utc_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_error_code(error: Exception) -> str:
    if isinstance(error, SocialProviderError):
        return "YOUTUBE_CONNECTION_ERROR"
    if isinstance(error, ValidationError):
        return "SCHEDULE_ARTIFACT_ERROR"
    return "YOUTUBE_UPLOAD_ERROR"


def _safe_publish_error(error: Exception) -> str:
    if isinstance(error, SocialProviderError):
        return "YouTube could not accept this upload. Reconnect YouTube and try again."
    if isinstance(error, ValidationError):
        return str(error)[:300]
    return "YouTube upload failed temporarily. DripCut will retry safely."


def _status_label(status: str) -> str:
    return {
        "scheduled_on_youtube": "Scheduled on YouTube",
        "uploaded": "Uploaded to YouTube",
        "published": "Published",
    }.get(status, "Upload complete")


def _identity(principal: Principal | None) -> tuple[str, str]:
    return (
        (principal.workspace_id, principal.access_token)
        if principal
        else ("local", "")
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
