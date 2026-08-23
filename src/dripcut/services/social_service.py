"""Social account readiness and interval scheduling.

The service deliberately stops short of pretending to publish. YouTube and
Instagram both require OAuth/API credentials and platform-specific review before
automated posting can work. DripCut can still prepare a real posting plan today:
which clips, which platform, and when each post should go live.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from dripcut.core.errors import ValidationError
from dripcut.core.paths import AppPaths
from dripcut.utils.fs import ensure_dir, human_size

__all__ = [
    "PlatformName",
    "SocialConnection",
    "ScheduledPost",
    "SocialSchedule",
    "SocialScheduleService",
]

PlatformName = Literal["instagram", "youtube"]


@dataclass(frozen=True, slots=True)
class SocialConnection:
    """Connection readiness for one publishing platform."""

    platform: PlatformName
    label: str
    connected: bool
    configured: bool
    detail: str
    setup_hint: str


@dataclass(frozen=True, slots=True)
class ScheduledPost:
    """One planned publish slot."""

    platform: PlatformName
    clip_name: str
    publish_at: str
    caption: str
    status: str = "draft"


@dataclass(frozen=True, slots=True)
class SocialSchedule:
    """A saved schedule built from the latest DripCut render."""

    id: str
    project_id: str
    archive: str
    archive_name: str
    created_at: float
    posts: list[ScheduledPost]


class SocialScheduleService:
    """Create draft posting schedules from finished ZIP archives."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.schedule_file = paths.projects / "social_schedule.json"

    # ---------------------------------------------------------------- status

    def connections(self) -> list[SocialConnection]:
        """Return Instagram and YouTube connection readiness."""
        youtube_ready = all(
            os.environ.get(name)
            for name in (
                "DRIPCUT_YOUTUBE_CLIENT_ID",
                "DRIPCUT_YOUTUBE_CLIENT_SECRET",
                "DRIPCUT_YOUTUBE_REFRESH_TOKEN",
            )
        )
        instagram_ready = all(
            os.environ.get(name)
            for name in (
                "DRIPCUT_INSTAGRAM_ACCESS_TOKEN",
                "DRIPCUT_INSTAGRAM_BUSINESS_ID",
            )
        )
        return [
            SocialConnection(
                platform="instagram",
                label="Instagram Reels",
                connected=False,
                configured=instagram_ready,
                detail=(
                    "Credentials found. Live OAuth validation and publishing are not enabled yet."
                    if instagram_ready
                    else "Needs a Creator/Business account, Graph API access token, and business id."
                ),
                setup_hint="Set DRIPCUT_INSTAGRAM_ACCESS_TOKEN and DRIPCUT_INSTAGRAM_BUSINESS_ID.",
            ),
            SocialConnection(
                platform="youtube",
                label="YouTube Shorts",
                connected=False,
                configured=youtube_ready,
                detail=(
                    "Credentials found. Live OAuth validation and publishing are not enabled yet."
                    if youtube_ready
                    else "Needs an OAuth client id, client secret, and refresh token."
                ),
                setup_hint=(
                    "Set DRIPCUT_YOUTUBE_CLIENT_ID, DRIPCUT_YOUTUBE_CLIENT_SECRET, "
                    "and DRIPCUT_YOUTUBE_REFRESH_TOKEN."
                ),
            ),
        ]

    def connection_map(self) -> dict[PlatformName, SocialConnection]:
        """Connection status keyed by platform."""
        return {item.platform: item for item in self.connections()}

    # ---------------------------------------------------------------- renders

    def latest_render(self) -> dict[str, object] | None:
        """Read the latest ZIP produced by Make Clips or AI Clips."""
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
        """List video files inside a ZIP archive, newest render first."""
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

    # ---------------------------------------------------------------- schedule

    def create_schedule(
        self,
        *,
        platforms: list[str],
        interval_minutes: int,
        start_at: str,
        caption: str,
    ) -> SocialSchedule:
        """Create and persist a draft posting schedule."""
        selected = [item for item in platforms if item in {"instagram", "youtube"}]
        if not selected:
            raise ValidationError("Choose Instagram, YouTube, or both.")
        if interval_minutes < 5:
            raise ValidationError("Use at least 5 minutes between posts.")
        latest = self.latest_render()
        if latest is None:
            raise ValidationError("Create clips first, then schedule the finished ZIP.")
        archive = Path(str(latest.get("archive", "")))
        return self.create_schedule_for_archive(
            archive=archive,
            project_id=str(latest.get("project_id", "legacy")),
            platforms=platforms,
            interval_minutes=interval_minutes,
            start_at=start_at,
            caption=caption,
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
    ) -> SocialSchedule:
        """Create a durable draft for a specific project ZIP."""
        selected = [item for item in platforms if item in {"instagram", "youtube"}]
        if not selected:
            raise ValidationError("Choose Instagram, YouTube, or both.")
        if interval_minutes < 5:
            raise ValidationError("Use at least 5 minutes between posts.")
        clips = self.clips_in_archive(archive)
        start = self._parse_start(start_at)
        template = (caption or "").strip() or "{clip} #shorts #reels"

        posts: list[ScheduledPost] = []
        slot = 0
        for clip in clips:
            clean_name = Path(clip).stem
            for platform in selected:
                publish_at = start + timedelta(minutes=interval_minutes * slot)
                posts.append(
                    ScheduledPost(
                        platform=platform,  # type: ignore[arg-type]
                        clip_name=clip,
                        publish_at=publish_at.strftime("%Y-%m-%d %H:%M"),
                        caption=template.format(
                            clip=clean_name,
                            platform="Instagram" if platform == "instagram" else "YouTube",
                        ),
                    )
                )
                slot += 1

        schedule = SocialSchedule(
            id=f"schedule-{int(time.time())}",
            project_id=project_id,
            archive=str(archive),
            archive_name=archive.name,
            created_at=time.time(),
            posts=posts,
        )
        self._write(schedule)
        return schedule

    def latest_schedule(self) -> SocialSchedule | None:
        """Return the most recently saved schedule."""
        try:
            data = json.loads(self.schedule_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        try:
            posts = [ScheduledPost(**item) for item in data.get("posts", [])]
            return SocialSchedule(
                id=str(data["id"]),
                project_id=str(data.get("project_id", "legacy")),
                archive=str(data["archive"]),
                archive_name=str(data["archive_name"]),
                created_at=float(data["created_at"]),
                posts=posts,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def latest_summary(self) -> dict[str, object]:
        """Small dashboard-friendly summary."""
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

    def _write(self, schedule: SocialSchedule) -> None:
        ensure_dir(self.schedule_file.parent)
        payload = asdict(schedule)
        tmp = self.schedule_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.schedule_file)

    @staticmethod
    def _parse_start(value: str) -> datetime:
        """Parse a friendly local start time."""
        raw = (value or "").strip()
        if not raw or raw.lower() == "now":
            return datetime.now() + timedelta(minutes=5)
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        raise ValidationError(
            "Use a start time like 2026-08-22 18:30.",
            hint="You can also type 'now' to start five minutes from now.",
        )
