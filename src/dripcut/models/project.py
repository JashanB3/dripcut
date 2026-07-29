"""Projects: the persisted record of a source file and everything derived from it."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dripcut.models.clip import SplitPlan
from dripcut.models.subtitle import CaptionStyle
from dripcut.utils.fs import slugify
from dripcut.utils.timecode import format_clock

__all__ = ["Project", "ProjectSummary"]

MANIFEST_VERSION = 1


@dataclass(slots=True)
class Project:
    """A workspace document.

    A project is a directory containing ``project.json`` plus caches (transcript,
    proxy, waveform, exported clips). It exists so a user can close DripCut mid
    edit, come back, and find the plan, transcript and caption style exactly as
    they left them - without any of it having left the machine.
    """

    name: str
    source_path: Path | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    duration: float = 0.0
    thumbnail: Path | None = None
    plan: SplitPlan | None = None
    caption_style: CaptionStyle = field(default_factory=CaptionStyle)
    transcript_file: Path | None = None
    outputs: list[Path] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    version: int = MANIFEST_VERSION

    @property
    def slug(self) -> str:
        """Filesystem-safe name used for output files."""
        return slugify(self.name)

    @property
    def source_name(self) -> str:
        """Source file name, or a placeholder for an empty project."""
        return self.source_path.name if self.source_path else "No media"

    @property
    def has_transcript(self) -> bool:
        """True when a transcript cache exists on disk."""
        return self.transcript_file is not None and Path(self.transcript_file).exists()

    @property
    def clip_count(self) -> int:
        """Number of planned segments."""
        return self.plan.count if self.plan else 0

    @property
    def duration_label(self) -> str:
        """Compact source duration."""
        return format_clock(self.duration)

    def touch(self) -> None:
        """Mark the project as modified now."""
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly manifest."""
        return {
            "version": self.version,
            "id": self.id,
            "name": self.name,
            "source_path": str(self.source_path) if self.source_path else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "duration": round(self.duration, 3),
            "thumbnail": str(self.thumbnail) if self.thumbnail else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "caption_style": self.caption_style.to_dict(),
            "transcript_file": str(self.transcript_file) if self.transcript_file else None,
            "outputs": [str(p) for p in self.outputs],
            "tags": list(self.tags),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Rebuild a project from its manifest, tolerating older versions."""
        plan_data = data.get("plan")
        return cls(
            name=str(data.get("name", "Untitled")),
            source_path=Path(data["source_path"]) if data.get("source_path") else None,
            id=str(data.get("id", uuid.uuid4().hex[:12])),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            duration=float(data.get("duration", 0.0)),
            thumbnail=Path(data["thumbnail"]) if data.get("thumbnail") else None,
            plan=SplitPlan.from_dict(plan_data) if plan_data else None,
            caption_style=CaptionStyle.from_dict(data.get("caption_style", {})),
            transcript_file=Path(data["transcript_file"]) if data.get("transcript_file") else None,
            outputs=[Path(p) for p in data.get("outputs", [])],
            tags=list(data.get("tags", [])),
            notes=str(data.get("notes", "")),
            version=int(data.get("version", MANIFEST_VERSION)),
        )

    def summary(self) -> ProjectSummary:
        """Lightweight view rendered by the dashboard and project list."""
        return ProjectSummary(
            id=self.id,
            name=self.name,
            source_name=self.source_name,
            duration=self.duration,
            clip_count=self.clip_count,
            updated_at=self.updated_at,
            thumbnail=self.thumbnail,
            has_transcript=self.has_transcript,
            tags=tuple(self.tags),
        )


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """Read-only project card data - cheap to build, safe to cache in the UI."""

    id: str
    name: str
    source_name: str
    duration: float
    clip_count: int
    updated_at: float
    thumbnail: Path | None = None
    has_transcript: bool = False
    tags: tuple[str, ...] = ()

    @property
    def duration_label(self) -> str:
        """Compact duration."""
        return format_clock(self.duration)

    @property
    def updated_label(self) -> str:
        """Relative modification time, e.g. ``4h ago``."""
        delta = max(0.0, time.time() - self.updated_at)
        if delta < 60:
            return "just now"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        if delta < 7 * 86400:
            return f"{int(delta // 86400)}d ago"
        return time.strftime("%d %b %Y", time.localtime(self.updated_at))
