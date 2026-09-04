"""Supabase/PostgREST persistence for universal content with RLS enforcement."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.auth.models import AuthProviderError
from dripcut.content.models import ContentItem, ContentSource, PlatformTarget
from dripcut.supabase_http import supabase_ssl_context
from dripcut.tenancy.models import TenantAccessDenied


class SupabaseContentRepository:
    name = "supabase"

    def __init__(self, url: str, anon_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    @classmethod
    def from_environment(cls) -> SupabaseContentRepository:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
        return cls(url, key)

    def save_source(self, source: ContentSource, *, access_token: str = "") -> ContentSource:
        existing = self._select_one(
            "content_sources", source.workspace_id, source.id, access_token
        )
        rows = self._write_record(
            "content_sources",
            source.workspace_id,
            source.id,
            _payload(source),
            access_token,
            mutable={"title", "text_content", "metadata", "status", "rights_confirmed"},
            exists=bool(existing),
        )
        return ContentSource(**rows[0]) if isinstance(rows, list) and rows else source

    def source(self, workspace_id: str, source_id: str, *, access_token: str = "") -> ContentSource:
        rows = self._select_one("content_sources", workspace_id, source_id, access_token)
        if not rows:
            raise TenantAccessDenied("content_source", source_id)
        return ContentSource(**rows[0])

    def list_sources(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentSource]:
        rows = self._request(
            "GET",
            "/rest/v1/content_sources?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "project_id": f"eq.{project_id}",
                    "order": "created_at.asc",
                }
            ),
            access_token=access_token,
        )
        return [ContentSource(**row) for row in rows] if isinstance(rows, list) else []

    def save_item(self, item: ContentItem, *, access_token: str = "") -> ContentItem:
        existing = self._select_one("content_items", item.workspace_id, item.id, access_token)
        rows = self._write_record(
            "content_items",
            item.workspace_id,
            item.id,
            _payload(item),
            access_token,
            mutable={
                "title",
                "script",
                "hook",
                "body",
                "description",
                "caption",
                "hashtags",
                "duration_seconds",
                "aspect_ratio",
                "language",
                "status",
                "metadata",
            },
            exists=bool(existing),
        )
        return ContentItem(**rows[0]) if isinstance(rows, list) and rows else item

    def item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> ContentItem:
        rows = self._select_one("content_items", workspace_id, item_id, access_token)
        if not rows:
            raise TenantAccessDenied("content_item", item_id)
        return ContentItem(**rows[0])

    def list_items(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentItem]:
        rows = self._request(
            "GET",
            "/rest/v1/content_items?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "project_id": f"eq.{project_id}",
                    "order": "created_at.asc",
                }
            ),
            access_token=access_token,
        )
        return [ContentItem(**row) for row in rows] if isinstance(rows, list) else []

    def delete_item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> None:
        self.item(workspace_id, item_id, access_token=access_token)
        self._delete("content_items", workspace_id, item_id, access_token)

    def save_target(self, target: PlatformTarget, *, access_token: str = "") -> PlatformTarget:
        existing = self._select_one(
            "platform_targets", target.workspace_id, target.id, access_token
        )
        rows = self._write_record(
            "platform_targets",
            target.workspace_id,
            target.id,
            _payload(target),
            access_token,
            mutable={
                "social_connection_id",
                "scheduled_at",
                "source_timezone",
                "publish_status",
                "provider_post_id",
                "provider_metadata",
                "idempotency_key",
                "attempt_count",
                "last_error_code",
                "last_error_message",
                "published_at",
            },
            exists=bool(existing),
        )
        return PlatformTarget(**rows[0]) if isinstance(rows, list) and rows else target

    def target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> PlatformTarget:
        rows = self._select_one("platform_targets", workspace_id, target_id, access_token)
        if not rows:
            raise TenantAccessDenied("platform_target", target_id)
        return PlatformTarget(**rows[0])

    def list_targets(self, workspace_id: str, item_id: str, *, access_token: str = "") -> list[PlatformTarget]:
        rows = self._request(
            "GET",
            "/rest/v1/platform_targets?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "content_item_id": f"eq.{item_id}",
                    "order": "created_at.asc",
                }
            ),
            access_token=access_token,
        )
        return [PlatformTarget(**row) for row in rows] if isinstance(rows, list) else []

    def delete_target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> None:
        self.target(workspace_id, target_id, access_token=access_token)
        self._delete("platform_targets", workspace_id, target_id, access_token)

    def delete_project(self, workspace_id: str, project_id: str, *, access_token: str = "") -> None:
        # The project FK cascades in PostgreSQL. This explicit method makes local and
        # hosted repository behavior equivalent when project deletion is orchestrated.
        del workspace_id, project_id, access_token

    def _select_one(
        self, table: str, workspace_id: str, resource_id: str, access_token: str
    ) -> list[dict[str, Any]]:
        rows = self._request(
            "GET",
            f"/rest/v1/{table}?"
            + urlencode(
                {
                    "select": "*",
                    "workspace_id": f"eq.{workspace_id}",
                    "id": f"eq.{resource_id}",
                    "limit": "1",
                }
            ),
            access_token=access_token,
        )
        return rows if isinstance(rows, list) else []

    def _delete(self, table: str, workspace_id: str, resource_id: str, access_token: str) -> None:
        self._request(
            "DELETE",
            f"/rest/v1/{table}?"
            + urlencode({"workspace_id": f"eq.{workspace_id}", "id": f"eq.{resource_id}"}),
            access_token=access_token,
            prefer="return=minimal",
        )

    def _write_record(
        self,
        table: str,
        workspace_id: str,
        resource_id: str,
        payload: dict[str, Any],
        access_token: str,
        *,
        mutable: set[str],
        exists: bool,
    ) -> Any:
        if not exists:
            return self._request(
                "POST",
                f"/rest/v1/{table}",
                payload,
                access_token=access_token,
                prefer="return=representation",
            )
        update = {key: value for key, value in payload.items() if key in mutable}
        return self._request(
            "PATCH",
            f"/rest/v1/{table}?"
            + urlencode(
                {"workspace_id": f"eq.{workspace_id}", "id": f"eq.{resource_id}"}
            ),
            update,
            access_token=access_token,
            prefer="return=representation",
        )

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
                str(data.get("message") or "Content database authorization failed."),
                status_code=error.code,
                code=str(data.get("code") or "CONTENT_DATABASE_ERROR"),
            ) from error
        except URLError as error:
            raise AuthProviderError(
                "Content database is temporarily unavailable.",
                status_code=503,
                code="CONTENT_DATABASE_UNAVAILABLE",
            ) from error


def _payload(value: ContentSource | ContentItem | PlatformTarget) -> dict[str, Any]:
    payload = asdict(value)
    payload.pop("created_at", None)
    payload.pop("updated_at", None)
    return payload
