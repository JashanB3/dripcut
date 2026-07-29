"""Segments and split plans - the unit of work for clipping and export."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from dripcut.utils.text import truncate
from dripcut.utils.timecode import format_clock, format_timecode

__all__ = ["SplitMode", "SegmentSource", "Segment", "SplitPlan"]


class SplitMode(StrEnum):
    """Available split strategies, mirrored one-to-one by the strategy registry."""

    FIXED = "fixed"
    SCENE = "scene"
    SILENCE = "silence"
    TIMESTAMPS = "timestamps"
    CHAPTERS = "chapters"
    AI_HIGHLIGHT = "ai_highlight"

    @property
    def label(self) -> str:
        """Title shown on the split mode selector."""
        return {
            SplitMode.FIXED: "Fixed length",
            SplitMode.SCENE: "Scene changes",
            SplitMode.SILENCE: "Silence gaps",
            SplitMode.TIMESTAMPS: "Timestamps",
            SplitMode.CHAPTERS: "Chapters",
            SplitMode.AI_HIGHLIGHT: "AI highlights",
        }[self]

    @property
    def description(self) -> str:
        """One-line explanation shown under the selector."""
        return {
            SplitMode.FIXED: "Cut every N seconds. Fast, predictable, no analysis.",
            SplitMode.SCENE: "Cut where the picture changes. Good for b-roll and gameplay.",
            SplitMode.SILENCE: "Cut in the pauses. Good for interviews and voiceover.",
            SplitMode.TIMESTAMPS: "Cut at the timecodes you type in.",
            SplitMode.CHAPTERS: "Cut on the chapter markers already in the file.",
            SplitMode.AI_HIGHLIGHT: "Transcribe, rank, and keep only the strongest moments.",
        }[self]

    @property
    def needs_ai(self) -> bool:
        """True when the mode requires Whisper and a local LLM."""
        return self is SplitMode.AI_HIGHLIGHT


class SegmentSource(StrEnum):
    """Where a segment's boundaries came from - shown as a chip on each card."""

    FIXED = "fixed"
    SCENE = "scene"
    SILENCE = "silence"
    MANUAL = "manual"
    CHAPTER = "chapter"
    AI = "ai"


@dataclass(frozen=True, slots=True)
class Segment:
    """A half-open time range ``[start, end)`` on a source file."""

    start: float
    end: float
    index: int = 0
    title: str = ""
    source: SegmentSource = SegmentSource.MANUAL
    score: float = 0.0
    reason: str = ""
    tags: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"segment end ({self.end}) must be after start ({self.start})")

    @property
    def duration(self) -> float:
        """Length in seconds."""
        return self.end - self.start

    @property
    def label(self) -> str:
        """Short label for cards: ``03 \u00b7 0:30 \u2192 1:00``."""
        return f"{self.index:02d} \u00b7 {format_clock(self.start)} \u2192 {format_clock(self.end)}"

    @property
    def timecode_range(self) -> str:
        """Full precision range used in logs and the plan table."""
        return f"{format_timecode(self.start)} - {format_timecode(self.end)}"

    def display_title(self, fallback_stem: str = "clip") -> str:
        """Title if the strategy set one, otherwise ``stem-01``."""
        return self.title.strip() or f"{fallback_stem}-{self.index:02d}"

    def output_name(self, stem: str, suffix: str = ".mp4", *, pattern: str = "{stem}-{index:03d}") -> str:
        """Render the configured file-name pattern for this segment."""
        rendered = pattern.format(
            stem=stem,
            index=self.index,
            start=format_clock(self.start).replace(":", "-"),
            end=format_clock(self.end).replace(":", "-"),
            title=truncate(self.title or "", 40).replace("/", "-"),
            source=self.source.value,
        )
        return f"{rendered.strip() or stem}{suffix}"

    def shifted(self, offset: float) -> Segment:
        """Return a copy moved by ``offset`` seconds, clamped at zero."""
        start = max(0.0, self.start + offset)
        return Segment(
            start=start,
            end=max(start + 0.05, self.end + offset),
            index=self.index,
            title=self.title,
            source=self.source,
            score=self.score,
            reason=self.reason,
            tags=self.tags,
        )

    def padded(self, before: float, after: float, *, limit: float | None = None) -> Segment:
        """Grow the range by ``before``/``after`` seconds without leaving the media."""
        start = max(0.0, self.start - max(0.0, before))
        end = self.end + max(0.0, after)
        if limit is not None:
            end = min(end, limit)
        if end <= start:
            end = start + 0.05
        return Segment(
            start=start,
            end=end,
            index=self.index,
            title=self.title,
            source=self.source,
            score=self.score,
            reason=self.reason,
            tags=self.tags,
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation stored in project manifests."""
        return {
            "id": self.id,
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "title": self.title,
            "source": self.source.value,
            "score": round(self.score, 4),
            "reason": self.reason,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        """Rebuild a segment from a project manifest."""
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            index=int(data.get("index", 0)),
            title=str(data.get("title", "")),
            source=SegmentSource(data.get("source", "manual")),
            score=float(data.get("score", 0.0)),
            reason=str(data.get("reason", "")),
            tags=tuple(data.get("tags", ())),
            id=str(data.get("id", uuid.uuid4().hex[:12])),
        )


@dataclass(frozen=True, slots=True)
class SplitPlan:
    """The result of planning a split: what would be rendered, and why.

    Planning is always separated from rendering. The user reviews a plan (segment
    count, durations, titles) before a single frame is encoded, which is the
    difference between a tool that feels fast and a tool that wastes ten minutes.
    """

    source: Path
    mode: SplitMode
    segments: tuple[Segment, ...]
    parameters: dict[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        """Number of segments in the plan."""
        return len(self.segments)

    @property
    def total_duration(self) -> float:
        """Summed duration of every segment."""
        return sum(segment.duration for segment in self.segments)

    @property
    def average_duration(self) -> float:
        """Mean segment duration, or zero for an empty plan."""
        return self.total_duration / self.count if self.count else 0.0

    @property
    def shortest(self) -> Segment | None:
        """Shortest segment, useful for warning about sub-second slivers."""
        return min(self.segments, key=lambda s: s.duration, default=None)

    def table_rows(self) -> list[list[Any]]:
        """Rows for the plan review table in the split page."""
        return [
            [
                segment.index,
                format_timecode(segment.start),
                format_timecode(segment.end),
                f"{segment.duration:.2f}s",
                segment.display_title(self.source.stem),
                f"{segment.score:.2f}" if segment.score else "-",
                segment.reason or segment.source.value,
            ]
            for segment in self.segments
        ]

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation stored in project manifests."""
        return {
            "source": str(self.source),
            "mode": self.mode.value,
            "parameters": self.parameters,
            "notes": list(self.notes),
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SplitPlan:
        """Rebuild a plan from a project manifest."""
        return cls(
            source=Path(data["source"]),
            mode=SplitMode(data.get("mode", "fixed")),
            segments=tuple(Segment.from_dict(item) for item in data.get("segments", [])),
            parameters=dict(data.get("parameters", {})),
            notes=tuple(data.get("notes", ())),
        )
