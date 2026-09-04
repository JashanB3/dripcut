"""Tenant-scoped social account and scheduled-post persistence."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.auth.models import AuthProviderError
from dripcut.social.models import PlatformName, ScheduledPost, SocialAccount, SocialSchedule
from dripcut.supabase_http import supabase_ssl_context
from dripcut.utils.fs import ensure_dir


class SocialStore(Protocol):
    supports_background_worker: bool

    def account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> SocialAccount | None: ...

    def save_account(self, account: SocialAccount, *, access_token: str = "") -> None: ...

    def delete_account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> None: ...

    def save_schedule(self, schedule: SocialSchedule, *, access_token: str = "") -> None: ...

    def latest_schedule(
        self, workspace_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None: ...

    def schedule(
        self, workspace_id: str, schedule_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None: ...

    def due_posts(self, now: datetime) -> list[ScheduledPost]: ...

    def recover_interrupted_posts(self) -> int: ...

    def update_post(self, post: ScheduledPost, *, access_token: str = "") -> None: ...


class LocalSocialStore:
    """Atomic JSON persistence for local development and one-host deployments."""

    supports_background_worker = True

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.database = self.root / "social.json"
        self._lock = threading.RLock()

    def account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> SocialAccount | None:
        del access_token
        with self._lock:
            row = self._read()["accounts"].get(f"{workspace_id}:{platform}")
        try:
            return SocialAccount(**row) if row else None
        except (TypeError, ValueError):
            return None

    def save_account(self, account: SocialAccount, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            data["accounts"][f"{account.workspace_id}:{account.platform}"] = asdict(account)
            self._write(data)

    def delete_account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> None:
        del access_token
        with self._lock:
            data = self._read()
            data["accounts"].pop(f"{workspace_id}:{platform}", None)
            self._write(data)

    def save_schedule(self, schedule: SocialSchedule, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            data["schedules"][schedule.id] = asdict(schedule)
            self._write(data)

    def latest_schedule(
        self, workspace_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None:
        del access_token
        with self._lock:
            rows = [
                row
                for row in self._read()["schedules"].values()
                if row.get("workspace_id") == workspace_id
            ]
        if not rows:
            return None
        return _schedule_from_dict(max(rows, key=lambda row: float(row.get("created_at", 0))))

    def schedule(
        self, workspace_id: str, schedule_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None:
        del access_token
        with self._lock:
            row = self._read()["schedules"].get(schedule_id)
        if not row or row.get("workspace_id") != workspace_id:
            return None
        return _schedule_from_dict(row)

    def due_posts(self, now: datetime) -> list[ScheduledPost]:
        due: list[ScheduledPost] = []
        with self._lock:
            schedules = list(self._read()["schedules"].values())
        for row in schedules:
            schedule = _schedule_from_dict(row)
            if schedule is None:
                continue
            due.extend(
                post
                for post in schedule.posts
                if post.status == "scheduled" and _as_utc(post.publish_at) <= now
            )
        return due

    def recover_interrupted_posts(self) -> int:
        recovered = 0
        with self._lock:
            data = self._read()
            for schedule in data["schedules"].values():
                for post in schedule.get("posts", []):
                    if post.get("status") != "uploading":
                        continue
                    post["status"] = "scheduled"
                    post["error_message"] = "Publishing resumed after a worker restart."
                    recovered += 1
            if recovered:
                self._write(data)
        return recovered

    def update_post(self, post: ScheduledPost, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            schedule = data["schedules"].get(post.schedule_id)
            if not schedule:
                return
            schedule["posts"] = [
                asdict(post) if row.get("id") == post.id else row
                for row in schedule.get("posts", [])
            ]
            self._write(data)

    def _read(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"accounts": {}, "schedules": {}}
        if not self.database.exists():
            return empty
        try:
            payload = json.loads(self.database.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return empty
        if not isinstance(payload, dict):
            return empty
        payload.setdefault("accounts", {})
        payload.setdefault("schedules", {})
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        temporary = self.database.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.database)


class SupabaseSocialStore:
    """PostgREST persistence with RLS for callers and a service key for workers."""

    def __init__(self, url: str, anon_key: str, service_key: str = "") -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_key
        self.supports_background_worker = bool(service_key)

    @classmethod
    def from_environment(cls) -> SupabaseSocialStore:
        url = os.environ.get("SUPABASE_URL", "").strip()
        anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not anon:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
        return cls(url, anon, os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip())

    def account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> SocialAccount | None:
        rows = self._request(
            "GET",
            "/rest/v1/social_connections?"
            + urlencode(
                {
                    "select": "id,workspace_id,owner_id,platform,external_account_id,display_name,encrypted_credentials,status,created_at,updated_at",
                    "workspace_id": f"eq.{workspace_id}",
                    "platform": f"eq.{platform}",
                    "status": "eq.connected",
                    "limit": "1",
                }
            ),
            access_token=access_token,
        )
        return _account_from_row(rows[0]) if isinstance(rows, list) and rows else None

    def save_account(self, account: SocialAccount, *, access_token: str = "") -> None:
        self._request(
            "POST",
            "/rest/v1/social_connections?on_conflict=workspace_id,platform",
            {
                "id": account.id,
                "workspace_id": account.workspace_id,
                "owner_id": account.owner_id,
                "platform": account.platform,
                "external_account_id": account.external_account_id,
                "display_name": account.display_name,
                "encrypted_credentials": account.encrypted_credentials,
                "status": account.status,
            },
            access_token=access_token,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def delete_account(
        self, workspace_id: str, platform: PlatformName, *, access_token: str = ""
    ) -> None:
        self._request(
            "DELETE",
            "/rest/v1/social_connections?"
            + urlencode(
                {"workspace_id": f"eq.{workspace_id}", "platform": f"eq.{platform}"}
            ),
            access_token=access_token,
        )

    def save_schedule(self, schedule: SocialSchedule, *, access_token: str = "") -> None:
        payload = []
        for post in schedule.posts:
            payload.append(
                {
                    "id": post.id,
                    "workspace_id": post.workspace_id,
                    "owner_id": post.owner_id,
                    "project_id": post.project_id,
                    "platform": post.platform,
                    "publish_at": _as_utc(post.publish_at).isoformat(),
                    "status": post.status,
                    "metadata": {
                        "schedule_id": schedule.id,
                        "archive": post.archive,
                        "archive_name": schedule.archive_name,
                        "clip_name": post.clip_name,
                        "caption": post.caption,
                        "title": post.title,
                        "schedule_created_at": schedule.created_at,
                    },
                }
            )
        self._request(
            "POST",
            "/rest/v1/scheduled_posts?on_conflict=id",
            payload,
            access_token=access_token,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def latest_schedule(
        self, workspace_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None:
        rows = self._request(
            "GET",
            "/rest/v1/scheduled_posts?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "order": "created_at.desc",
                    "limit": "100",
                }
            ),
            access_token=access_token,
        )
        if not isinstance(rows, list) or not rows:
            return None
        schedule_id = str(rows[0].get("metadata", {}).get("schedule_id") or "")
        selected = [
            row for row in rows if str(row.get("metadata", {}).get("schedule_id")) == schedule_id
        ]
        return _schedule_from_rows(selected)

    def schedule(
        self, workspace_id: str, schedule_id: str, *, access_token: str = ""
    ) -> SocialSchedule | None:
        rows = self._request(
            "GET",
            "/rest/v1/scheduled_posts?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "metadata->>schedule_id": f"eq.{schedule_id}",
                    "order": "publish_at.asc",
                }
            ),
            access_token=access_token,
        )
        return _schedule_from_rows(rows) if isinstance(rows, list) else None

    def due_posts(self, now: datetime) -> list[ScheduledPost]:
        if not self.service_key:
            return []
        rows = self._request(
            "GET",
            "/rest/v1/scheduled_posts?"
            + urlencode(
                {
                    "select": "*",
                    "status": "eq.scheduled",
                    "publish_at": f"lte.{now.isoformat()}",
                    "order": "publish_at.asc",
                    "limit": "25",
                }
            ),
            access_token=self.service_key,
        )
        return [_post_from_row(row) for row in rows if isinstance(row, dict)]

    def recover_interrupted_posts(self) -> int:
        if not self.service_key:
            return 0
        rows = self._request(
            "PATCH",
            "/rest/v1/scheduled_posts?status=eq.uploading",
            {
                "status": "scheduled",
                "error_message": "Publishing resumed after a worker restart.",
            },
            access_token=self.service_key,
            prefer="return=representation",
        )
        return len(rows) if isinstance(rows, list) else 0

    def update_post(self, post: ScheduledPost, *, access_token: str = "") -> None:
        self._request(
            "PATCH",
            f"/rest/v1/scheduled_posts?id=eq.{post.id}",
            {
                "publish_at": _as_utc(post.publish_at).isoformat(),
                "status": post.status,
                "external_post_id": post.external_post_id,
                "error_message": post.error_message,
                "metadata": {
                    "schedule_id": post.schedule_id,
                    "archive": post.archive,
                    "archive_name": Path(post.archive).name,
                    "clip_name": post.clip_name,
                    "caption": post.caption,
                    "title": post.title,
                },
            },
            access_token=access_token,
            prefer="return=minimal",
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | list[dict[str, Any]] | None = None,
        *,
        access_token: str,
        prefer: str = "",
    ) -> Any:
        token = access_token or self.service_key
        if not token:
            raise RuntimeError("A user access token or SUPABASE_SERVICE_ROLE_KEY is required.")
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20, context=supabase_ssl_context()) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            try:
                detail = json.loads(error.read())
            except (json.JSONDecodeError, OSError):
                detail = {}
            raise AuthProviderError(
                str(detail.get("message") or "Social persistence failed."),
                status_code=error.code,
                code=str(detail.get("code") or "SUPABASE_SOCIAL_ERROR"),
            ) from error
        except URLError as error:
            raise AuthProviderError(
                "Social persistence is temporarily unavailable.",
                status_code=503,
                code="SOCIAL_STORE_UNAVAILABLE",
            ) from error


def build_social_store(root: Path, tenant_provider: str) -> SocialStore:
    configured = os.environ.get("DRIPCUT_SOCIAL_STORE", "").strip().lower()
    provider = configured or ("supabase" if tenant_provider == "supabase" else "local")
    if provider == "supabase":
        return SupabaseSocialStore.from_environment()
    if provider != "local":
        raise RuntimeError(f"Unsupported DRIPCUT_SOCIAL_STORE: {provider}")
    return LocalSocialStore(root / "social")


def _account_from_row(row: dict[str, Any]) -> SocialAccount:
    return SocialAccount(
        id=str(row["id"]),
        workspace_id=str(row["workspace_id"]),
        owner_id=str(row["owner_id"]),
        platform=str(row["platform"]),  # type: ignore[arg-type]
        external_account_id=str(row.get("external_account_id") or ""),
        display_name=str(row.get("display_name") or ""),
        encrypted_credentials=str(row.get("encrypted_credentials") or ""),
        status=str(row.get("status") or "connected"),
        created_at=_as_timestamp(row.get("created_at")),
        updated_at=_as_timestamp(row.get("updated_at")),
    )


def _schedule_from_dict(payload: dict[str, Any]) -> SocialSchedule | None:
    try:
        posts = [ScheduledPost(**item) for item in payload.get("posts", [])]
        return SocialSchedule(
            id=str(payload["id"]),
            project_id=str(payload.get("project_id") or "legacy"),
            archive=str(payload.get("archive") or ""),
            archive_name=str(payload.get("archive_name") or ""),
            created_at=float(payload.get("created_at") or 0),
            posts=posts,
            workspace_id=str(payload.get("workspace_id") or "local"),
            owner_id=str(payload.get("owner_id") or "local"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _post_from_row(row: dict[str, Any]) -> ScheduledPost:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return ScheduledPost(
        id=str(row["id"]),
        schedule_id=str(metadata.get("schedule_id") or ""),
        workspace_id=str(row.get("workspace_id") or ""),
        owner_id=str(row.get("owner_id") or ""),
        project_id=str(row.get("project_id") or ""),
        platform=str(row["platform"]),  # type: ignore[arg-type]
        clip_name=str(metadata.get("clip_name") or "clip.mp4"),
        archive=str(metadata.get("archive") or ""),
        publish_at=_as_utc(str(row["publish_at"])).isoformat(),
        caption=str(metadata.get("caption") or ""),
        title=str(metadata.get("title") or ""),
        status=str(row.get("status") or "draft"),  # type: ignore[arg-type]
        external_post_id=(
            str(row["external_post_id"]) if row.get("external_post_id") else None
        ),
        error_message=str(row["error_message"]) if row.get("error_message") else None,
    )


def _schedule_from_rows(rows: list[dict[str, Any]]) -> SocialSchedule | None:
    if not rows:
        return None
    posts = [_post_from_row(row) for row in rows]
    metadata = rows[0].get("metadata", {})
    return SocialSchedule(
        id=str(metadata.get("schedule_id") or ""),
        project_id=str(rows[0].get("project_id") or ""),
        archive=str(metadata.get("archive") or ""),
        archive_name=str(metadata.get("archive_name") or Path(str(metadata.get("archive") or "")).name),
        created_at=float(metadata.get("schedule_created_at") or _as_timestamp(rows[0].get("created_at"))),
        posts=posts,
        workspace_id=str(rows[0].get("workspace_id") or ""),
        owner_id=str(rows[0].get("owner_id") or ""),
    )


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _as_timestamp(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return _as_utc(value).timestamp()
        except ValueError:
            pass
    return 0.0
