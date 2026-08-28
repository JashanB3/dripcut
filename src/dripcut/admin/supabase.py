"""Service-role analytics for the internal production admin area."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.admin.models import AdminJob, AdminSnapshot, AdminUsage, AdminUser
from dripcut.auth.models import AuthProviderError
from dripcut.supabase_http import supabase_ssl_context


def _timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class SupabaseAdminRepository:
    name = "supabase"

    def __init__(self, url: str, anon_key: str, service_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key
        self.service_key = service_key

    @classmethod
    def from_environment(cls) -> SupabaseAdminRepository:
        url = os.environ.get("SUPABASE_URL", "").strip()
        anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not anon or not service:
            raise RuntimeError("Supabase admin analytics require URL, anon key, and service-role key.")
        return cls(url, anon, service)

    def snapshot(self, *, limit: int = 50) -> AdminSnapshot:
        now = datetime.now(UTC)
        profiles = self._rows("profiles", "id,email,display_name,created_at,updated_at", limit=5000)
        memberships = self._rows("workspace_members", "user_id,workspace_id,role", limit=5000)
        projects = self._rows("projects", "id", limit=5000)
        sources = self._rows("source_assets", "id,size_bytes", limit=5000)
        artifacts = self._rows("artifacts", "id,size_bytes", limit=5000)
        jobs_data = self._rows(
            "render_jobs",
            "id,project_id,status,stage,error_code,error_message,created_at,started_at,finished_at",
            limit=5000,
            order="created_at.desc",
        )
        events = self._rows("usage_events", "event_type,quantity,unit", limit=10000)
        posts = self._rows("scheduled_posts", "status", limit=10000)
        member_by_user = {str(row.get("user_id")): row for row in memberships}
        users = [
            AdminUser(
                id=str(row.get("id") or ""),
                email=str(row.get("email") or ""),
                name=str(row.get("display_name") or ""),
                workspace_id=str(member_by_user.get(str(row.get("id")), {}).get("workspace_id") or ""),
                role=str(member_by_user.get(str(row.get("id")), {}).get("role") or "user"),
                created_at=str(row.get("created_at") or ""),
                last_active_at=str(row.get("updated_at") or ""),
            )
            for row in profiles
        ]
        jobs = [self._job(row) for row in jobs_data]
        usage_totals: dict[tuple[str, str], float] = defaultdict(float)
        for event in events:
            usage_totals[(str(event.get("event_type") or "unknown"), str(event.get("unit") or ""))] += float(event.get("quantity") or 0)
        usage = [AdminUsage(metric=metric, quantity=round(value, 3), unit=unit) for (metric, unit), value in sorted(usage_totals.items())]
        new_cutoff = now - timedelta(days=7)
        active_cutoff = now - timedelta(days=30)
        failed = [job for job in jobs if job.status == "failed"]
        ai_requests = sum(value for (metric, _), value in usage_totals.items() if metric in {"ai_viral_analyses", "ai_editor_actions", "thumbnail_generations"})
        processing_minutes = sum(value for (metric, _), value in usage_totals.items() if metric == "video_processing_minutes")
        transcription_minutes = sum(value for (metric, _), value in usage_totals.items() if metric == "transcription_minutes")
        metrics: dict[str, float | int] = {
            "total_users": len(users),
            "new_users_7d": sum(bool((created := _timestamp(row.get("created_at"))) and created >= new_cutoff) for row in profiles),
            "active_users_30d": sum(bool((updated := _timestamp(row.get("updated_at"))) and updated >= active_cutoff) for row in profiles),
            "projects_created": len(projects),
            "videos_processed": sum(job.status == "succeeded" for job in jobs),
            "processing_minutes": round(processing_minutes, 3),
            "render_jobs": len(jobs),
            "failed_jobs": len(failed),
            "ai_requests": round(ai_requests, 3),
            "transcription_minutes": round(transcription_minutes, 3),
            "storage_bytes": sum(int(row.get("size_bytes") or 0) for row in [*sources, *artifacts]),
            "scheduled_posts": sum(row.get("status") in {"scheduled", "uploading"} for row in posts),
            "published_posts": sum(row.get("status") == "published" for row in posts),
            "estimated_provider_units": round(ai_requests + transcription_minutes, 3),
        }
        return AdminSnapshot(metrics=metrics, users=users[:limit], jobs=jobs[:limit], errors=failed[:limit], usage=usage, generated_at=now.isoformat())

    @staticmethod
    def _job(row: dict[str, Any]) -> AdminJob:
        started = _timestamp(row.get("started_at"))
        finished = _timestamp(row.get("finished_at"))
        elapsed = max(0.0, (finished - started).total_seconds()) if started and finished else 0.0
        return AdminJob(
            id=str(row.get("id") or ""),
            title="Render job",
            status=str(row.get("status") or "unknown"),
            stage=str(row.get("stage") or ""),
            project_id=str(row.get("project_id") or ""),
            error_code=str(row.get("error_code") or ""),
            error_message=str(row.get("error_message") or ""),
            created_at=str(row.get("created_at") or ""),
            elapsed_seconds=round(elapsed, 3),
        )

    def _rows(self, table: str, select: str, *, limit: int, order: str = "") -> list[dict[str, Any]]:
        params = {"select": select, "limit": str(limit)}
        if order:
            params["order"] = order
        request = Request(
            f"{self.url}/rest/v1/{table}?{urlencode(params)}",
            headers={
                "apikey": self.anon_key,
                "Authorization": f"Bearer {self.service_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=20, context=supabase_ssl_context()) as response:  # noqa: S310
                payload = json.loads(response.read() or b"[]")
                return payload if isinstance(payload, list) else []
        except HTTPError as error:
            raise AuthProviderError("Admin analytics query failed.", status_code=error.code, code="ADMIN_QUERY_FAILED") from error
        except (URLError, json.JSONDecodeError) as error:
            raise AuthProviderError("Admin analytics are temporarily unavailable.", status_code=503, code="ADMIN_UNAVAILABLE") from error
