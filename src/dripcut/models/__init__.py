"""Immutable domain objects shared by engines, services and the UI."""

from __future__ import annotations

from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.models.job import Job, JobKind, JobResult, JobStatus
from dripcut.models.media import AudioStream, MediaInfo, VideoStream
from dripcut.models.project import Project, ProjectSummary
from dripcut.models.subtitle import CaptionStyle, SubtitleFormat
from dripcut.models.transcript import Transcript, TranscriptSegment, Word

__all__ = [
    "AudioStream",
    "CaptionStyle",
    "Job",
    "JobKind",
    "JobResult",
    "JobStatus",
    "MediaInfo",
    "Project",
    "ProjectSummary",
    "Segment",
    "SegmentSource",
    "SplitMode",
    "SplitPlan",
    "SubtitleFormat",
    "Transcript",
    "TranscriptSegment",
    "VideoStream",
    "Word",
]
