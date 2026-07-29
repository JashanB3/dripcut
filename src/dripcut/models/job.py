"""Jobs: the unit tracked by the export queue and shown in the queue panel."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from dripcut.utils.concurrency import CancelToken
from dripcut.utils.timecode import format_duration

__all__ = ["JobStatus", "JobKind", "JobResult", "Job"]


class JobStatus(StrEnum):
    """Lifecycle of a queued job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True when no further transition is possible."""
        return self in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}

    @property
    def icon(self) -> str:
        """Glyph used in the queue list."""
        return {
            JobStatus.QUEUED: "\u25cb",
            JobStatus.RUNNING: "\u25d4",
            JobStatus.SUCCEEDED: "\u25cf",
            JobStatus.FAILED: "\u2715",
            JobStatus.CANCELLED: "\u2013",
        }[self]


class JobKind(StrEnum):
    """What a job does - drives grouping and the icon in the queue."""

    TRIM = "trim"
    SPLIT = "split"
    MERGE = "merge"
    CONVERT = "convert"
    COMPRESS = "compress"
    RESIZE = "resize"
    CROP = "crop"
    ROTATE = "rotate"
    GIF = "gif"
    FRAMES = "frames"
    AUDIO = "audio"
    WATERMARK = "watermark"
    FPS = "fps"
    SUBTITLES = "subtitles"
    BURN = "burn"
    TRANSCRIBE = "transcribe"
    ANALYSE = "analyse"
    BATCH = "batch"
    PLUGIN = "plugin"


@dataclass(slots=True)
class JobResult:
    """Outcome of a finished job."""

    outputs: list[Path] = field(default_factory=list)
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def primary(self) -> Path | None:
        """First produced file, if any."""
        return self.outputs[0] if self.outputs else None


@dataclass(slots=True)
class Job:
    """A tracked unit of work.

    ``run`` is a callable taking ``(job)`` and returning a :class:`JobResult`. The
    queue owns scheduling; the job owns its own progress and cancellation state so
    the UI can poll a single object.
    """

    kind: JobKind
    title: str
    run: Any = field(repr=False, default=None)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    stage: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    hint: str | None = None
    result: JobResult | None = None
    source: Path | None = None
    project_id: str | None = None
    cancel_token: CancelToken = field(default_factory=CancelToken, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        """Seconds spent running (or so far, if still running)."""
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return max(0.0, end - self.started_at)

    @property
    def elapsed_label(self) -> str:
        """Human elapsed time for the queue row."""
        return format_duration(self.elapsed)

    @property
    def percent(self) -> int:
        """Progress as an integer 0-100."""
        return int(round(max(0.0, min(1.0, self.progress)) * 100))

    @property
    def is_active(self) -> bool:
        """True while queued or running."""
        return not self.status.is_terminal

    def set_progress(self, value: float, stage: str = "") -> None:
        """Update progress, clamping to ``[0, 1]``."""
        self.progress = max(0.0, min(1.0, float(value)))
        if stage:
            self.stage = stage

    def cancel(self) -> None:
        """Request cancellation; a queued job flips immediately."""
        self.cancel_token.cancel()
        if self.status is JobStatus.QUEUED:
            self.status = JobStatus.CANCELLED
            self.finished_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation persisted to the job history."""
        return {
            "id": self.id,
            "kind": self.kind.value,
            "title": self.title,
            "status": self.status.value,
            "progress": round(self.progress, 3),
            "stage": self.stage,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "source": str(self.source) if self.source else None,
            "project_id": self.project_id,
            "outputs": [str(p) for p in (self.result.outputs if self.result else [])],
            "message": self.result.message if self.result else "",
        }
