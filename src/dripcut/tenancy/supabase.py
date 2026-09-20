"""Supabase/PostgREST tenant repository. RLS remains the final authorization boundary."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.auth.models import AuthProviderError, AuthUser
from dripcut.supabase_http import supabase_ssl_context
from dripcut.tenancy.models import Principal, ResourceKind, TenantAccessDenied

TABLES: dict[ResourceKind, str] = {
    "project": "projects",
    "source": "source_assets",
    "job": "render_jobs",
    "artifact": "artifacts",
}


class SupabaseTenantRepository:
    name = "supabase"

    def __init__(self, url: str, anon_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self._access_ttl = max(
            0.0, float(os.environ.get("DRIPCUT_RESOURCE_ACCESS_CACHE_TTL_SECONDS", "15"))
        )
        self._access_limit = max(
            1, int(os.environ.get("DRIPCUT_RESOURCE_ACCESS_CACHE_MAX_ENTRIES", "4096"))
        )
        self._access_cache: OrderedDict[
            tuple[str, ResourceKind, str], float
        ] = OrderedDict()
        self._access_lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> SupabaseTenantRepository:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
        return cls(url, key)

    def principal_for(self, user: AuthUser, access_token: str) -> Principal:
        rows = self._request(
            "GET",
            "/rest/v1/workspace_members?"
            + urlencode(
                {
                    "select": "workspace_id,role",
                    "user_id": f"eq.{user.id}",
                    "order": "created_at.asc",
                    "limit": "1",
                }
            ),
            access_token=access_token,
        )
        if not isinstance(rows, list) or not rows:
            raise AuthProviderError(
                "Your account does not have a workspace yet.",
                status_code=403,
                code="WORKSPACE_REQUIRED",
            )
        row = rows[0]
        profiles = self._request(
            "GET",
            "/rest/v1/profiles?"
            + urlencode({"select": "is_dripcut_admin", "id": f"eq.{user.id}", "limit": "1"}),
            access_token=access_token,
        )
        return Principal(
            user=user,
            workspace_id=str(row["workspace_id"]),
            role=str(row["role"]),  # type: ignore[arg-type]
            access_token=access_token,
            is_dripcut_admin=bool(profiles and profiles[0].get("is_dripcut_admin")),
        )

    def register(
        self,
        principal: Principal,
        kind: ResourceKind,
        resource_id: str,
        *,
        project_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        values = attributes or {}
        payload: dict[str, Any] = {
            "id": resource_id,
            "workspace_id": principal.workspace_id,
            "owner_id": principal.user.id,
        }
        if project_id and kind != "project":
            payload["project_id"] = project_id
        if kind == "project":
            payload.update(
                {
                    "title": str(values.get("title") or "Untitled"),
                    "project_type": str(values.get("project_type") or "auto_clip"),
                    "status": str(values.get("status") or "draft"),
                    "output_format": str(values.get("output_format") or "portrait"),
                }
            )
        elif kind == "source":
            payload.update(
                {
                    "kind": str(values.get("kind") or "upload"),
                    "name": str(values.get("name") or "source"),
                    "status": str(values.get("status") or "ready"),
                    "duration_seconds": float(values.get("duration") or 0),
                    "size_bytes": int(values.get("size_bytes") or 0),
                    "mime_type": str(values.get("mime_type") or "application/octet-stream"),
                    "storage_key": values.get("storage_key") or None,
                    "poster_storage_key": values.get("poster_storage_key") or None,
                    "width": int(values.get("width") or 0),
                    "height": int(values.get("height") or 0),
                    "source_url": values.get("source_url") or None,
                }
            )
        elif kind == "job":
            started_at = values.get("started_at")
            finished_at = values.get("finished_at")
            payload.update(
                {
                    "source_asset_id": values.get("source_id") or None,
                    "status": str(values.get("status") or "queued"),
                    "progress": float(values.get("progress") or 0),
                    "stage": str(values.get("stage") or ""),
                    "error_code": values.get("error_code") or None,
                    "error_message": values.get("error_message") or None,
                    "started_at": (
                        datetime.fromtimestamp(float(started_at), tz=UTC).isoformat()
                        if isinstance(started_at, int | float)
                        else started_at or None
                    ),
                    "finished_at": (
                        datetime.fromtimestamp(float(finished_at), tz=UTC).isoformat()
                        if isinstance(finished_at, int | float)
                        else finished_at or None
                    ),
                    "attempt": int(values.get("attempt") or 0),
                    "max_attempts": max(1, int(values.get("max_attempts") or 1)),
                    "idempotency_key": values.get("idempotency_key") or None,
                }
            )
        elif kind == "artifact":
            payload.update(
                {
                    "render_job_id": str(values.get("job_id")),
                    "kind": str(values.get("kind") or "clip"),
                    "name": str(values.get("name") or "artifact"),
                    "size_bytes": int(values.get("size_bytes") or 0),
                    "mime_type": str(values.get("mime_type") or "application/octet-stream"),
                    "storage_key": values.get("storage_key") or None,
                }
            )
        self._request(
            "POST",
            f"/rest/v1/{TABLES[kind]}?on_conflict=id",
            payload,
            access_token=principal.access_token,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        self._remember_access(principal, kind, resource_id)

    def can_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> bool:
        if self._has_cached_access(principal, kind, resource_id):
            return True
        query = urlencode({"select": "id", "id": f"eq.{resource_id}", "limit": "1"})
        rows = self._request(
            "GET", f"/rest/v1/{TABLES[kind]}?{query}", access_token=principal.access_token
        )
        allowed = isinstance(rows, list) and bool(rows)
        if allowed:
            self._remember_access(principal, kind, resource_id)
        return allowed

    def require_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> None:
        if not self.can_access(principal, kind, resource_id):
            raise TenantAccessDenied(kind, resource_id)

    def project_ids(self, principal: Principal) -> set[str]:
        rows = self._request(
            "GET", "/rest/v1/projects?select=id&order=updated_at.desc", access_token=principal.access_token
        )
        return {str(row["id"]) for row in rows} if isinstance(rows, list) else set()

    def delete_project(self, principal: Principal, project_id: str) -> None:
        self.require_access(principal, "project", project_id)
        query = urlencode({"id": f"eq.{project_id}"})
        self._request(
            "DELETE",
            f"/rest/v1/projects?{query}",
            access_token=principal.access_token,
            prefer="return=minimal",
        )
        with self._access_lock:
            self._access_cache = OrderedDict(
                (key, expiry)
                for key, expiry in self._access_cache.items()
                if key[0] != principal.workspace_id
            )

    def _has_cached_access(
        self, principal: Principal, kind: ResourceKind, resource_id: str
    ) -> bool:
        if self._access_ttl <= 0:
            return False
        key = (principal.workspace_id, kind, resource_id)
        now = time.monotonic()
        with self._access_lock:
            expiry = self._access_cache.get(key, 0.0)
            if expiry <= now:
                self._access_cache.pop(key, None)
                return False
            self._access_cache.move_to_end(key)
            return True

    def _remember_access(
        self, principal: Principal, kind: ResourceKind, resource_id: str
    ) -> None:
        if self._access_ttl <= 0:
            return
        key = (principal.workspace_id, kind, resource_id)
        with self._access_lock:
            self._access_cache[key] = time.monotonic() + self._access_ttl
            self._access_cache.move_to_end(key)
            while len(self._access_cache) > self._access_limit:
                self._access_cache.popitem(last=False)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        access_token: str,
        prefer: str | None = None,
    ) -> Any:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {access_token}",
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
            with urlopen(  # noqa: S310 - configured Supabase URL
                request,
                timeout=20,
                context=supabase_ssl_context(),
            ) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except HTTPError as error:
            try:
                data = json.loads(error.read())
            except (json.JSONDecodeError, OSError):
                data = {}
            raise AuthProviderError(
                str(data.get("message") or "Database authorization failed."),
                status_code=error.code,
                code=str(data.get("code") or "SUPABASE_DATABASE_ERROR"),
            ) from error
        except URLError as error:
            raise AuthProviderError(
                "Database service is temporarily unavailable.",
                status_code=503,
                code="DATABASE_UNAVAILABLE",
            ) from error
