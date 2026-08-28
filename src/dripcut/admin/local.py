"""Development analytics assembled from private local persistence."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dripcut.admin.models import AdminJob, AdminSnapshot, AdminUsage, AdminUser


def _read(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback
    return value if isinstance(value, dict) else fallback


def _iso(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


class LocalAdminRepository:
    name = "local"

    def __init__(self, root: Path, *, queue: Any) -> None:
        self.root = root
        self.queue = queue

    def snapshot(self, *, limit: int = 50) -> AdminSnapshot:
        now = datetime.now(UTC)
        tenant = _read(
            self.root / "tenancy" / "tenants.json",
            {"profiles": {}, "memberships": {}, "resources": {}},
        )
        usage_data = _read(
            self.root / "usage" / "usage.json",
            {"events": []},
        )
        social = _read(
            self.root / "social" / "social.json",
            {"schedules": {}},
        )
        profiles = tenant.get("profiles", {})
        memberships = tenant.get("memberships", {})
        resources = list(tenant.get("resources", {}).values())
        valid_profiles = [profile for profile in profiles.values() if isinstance(profile, dict)]
        users = [
            AdminUser(
                id=str(profile.get("id") or user_id),
                email=str(profile.get("email") or ""),
                name=str(profile.get("name") or ""),
                workspace_id=str(memberships.get(user_id, {}).get("workspace_id") or ""),
                role=str(memberships.get(user_id, {}).get("role") or "user"),
                created_at=_iso(profile.get("created_at")),
                last_active_at=_iso(profile.get("updated_at")),
            )
            for user_id, profile in profiles.items()
            if isinstance(profile, dict)
        ]
        users.sort(key=lambda item: item.created_at, reverse=True)

        jobs = [self._job(item) for item in self.queue.all_jobs(limit=limit)]
        usage_totals: dict[tuple[str, str], float] = defaultdict(float)
        for event in usage_data.get("events", []):
            if not isinstance(event, dict):
                continue
            key = (str(event.get("metric") or event.get("event_type") or "unknown"), str(event.get("unit") or ""))
            usage_totals[key] += float(event.get("quantity") or 0)
        usage = [
            AdminUsage(metric=metric, quantity=round(quantity, 3), unit=unit)
            for (metric, unit), quantity in sorted(usage_totals.items())
        ]
        posts = [
            post
            for schedule in social.get("schedules", {}).values()
            if isinstance(schedule, dict)
            for post in schedule.get("posts", [])
            if isinstance(post, dict)
        ]
        source_rows = [row for row in resources if row.get("kind") == "source"]
        project_rows = [row for row in resources if row.get("kind") == "project"]
        artifact_rows = [row for row in resources if row.get("kind") == "artifact"]
        totals = dict(usage_totals)
        new_cutoff = (now - timedelta(days=7)).timestamp()
        active_cutoff = (now - timedelta(days=30)).timestamp()
        completed = [job for job in jobs if job.status == "succeeded"]
        failed = [job for job in jobs if job.status == "failed"]
        ai_requests = sum(
            quantity
            for (metric, _unit), quantity in usage_totals.items()
            if metric in {"ai_viral_analyses", "ai_editor_actions", "thumbnail_generations"}
        )
        storage_bytes = sum(
            int(row.get("attributes", {}).get("size_bytes") or 0)
            for row in [*source_rows, *artifact_rows]
        )
        metrics: dict[str, float | int] = {
            "total_users": len(users),
            "new_users_7d": sum(
                float(profile.get("created_at") or 0) >= new_cutoff for profile in valid_profiles
            ),
            "active_users_30d": sum(
                float(profile.get("updated_at") or 0) >= active_cutoff for profile in valid_profiles
            ),
            "projects_created": len(project_rows),
            "videos_processed": len(completed),
            "processing_minutes": round(totals.get(("video_processing_minutes", "minutes"), 0), 3),
            "render_jobs": len(jobs),
            "failed_jobs": len(failed),
            "ai_requests": round(ai_requests, 3),
            "transcription_minutes": round(totals.get(("transcription_minutes", "minutes"), 0), 3),
            "storage_bytes": storage_bytes,
            "scheduled_posts": sum(post.get("status") in {"scheduled", "uploading"} for post in posts),
            "published_posts": sum(post.get("status") == "published" for post in posts),
            "estimated_provider_units": round(ai_requests + totals.get(("transcription_minutes", "minutes"), 0), 3),
        }
        return AdminSnapshot(
            metrics=metrics,
            users=users[:limit],
            jobs=jobs,
            errors=failed[:limit],
            usage=usage,
            generated_at=now.isoformat(),
        )

    @staticmethod
    def _job(job: Any) -> AdminJob:
        return AdminJob(
            id=str(job.id),
            title=str(job.title),
            status=str(job.status),
            stage=str(job.stage),
            project_id=str(job.project_id or ""),
            error_code=str(job.metadata.get("error_code") or ""),
            error_message=str(job.error or ""),
            created_at=_iso(job.created_at),
            elapsed_seconds=round(float(job.elapsed), 3),
        )
