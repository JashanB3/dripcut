"""Shared usage and quota value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from dripcut.core.errors import DripCutError

UsageMetric = Literal[
    "video_processing_minutes",
    "ai_viral_analyses",
    "transcription_minutes",
    "thumbnail_generations",
    "ai_editor_actions",
    "scheduled_posts",
    "youtube_imports",
    "storage_bytes",
]

METRIC_LABELS: dict[UsageMetric, str] = {
    "video_processing_minutes": "Video processing",
    "ai_viral_analyses": "AI viral analyses",
    "transcription_minutes": "Transcription",
    "thumbnail_generations": "AI thumbnails",
    "ai_editor_actions": "AI Editor actions",
    "scheduled_posts": "Scheduling",
    "youtube_imports": "YouTube imports",
    "storage_bytes": "Storage",
}

METRIC_UNITS: dict[UsageMetric, str] = {
    "video_processing_minutes": "minutes",
    "ai_viral_analyses": "analyses",
    "transcription_minutes": "minutes",
    "thumbnail_generations": "generations",
    "ai_editor_actions": "actions",
    "scheduled_posts": "posts",
    "youtube_imports": "imports",
    "storage_bytes": "bytes",
}


@dataclass(frozen=True)
class UsagePeriod:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class UsageReservation:
    id: str
    metric: UsageMetric
    quantity: float
    unit: str


@dataclass(frozen=True)
class UsageTotals:
    used: float = 0
    reserved: float = 0


class QuotaExceeded(DripCutError):
    """A workspace has exhausted an entitlement for the current period."""

    code = "QUOTA_EXCEEDED"

    def __init__(
        self,
        metric: UsageMetric,
        *,
        used: float,
        requested: float,
        limit: float,
    ) -> None:
        label = METRIC_LABELS[metric]
        super().__init__(
            f"Your {label.lower()} allowance has been reached.",
            hint="Open Usage to review your plan or wait for the next reset.",
        )
        self.metric = metric
        self.used = used
        self.requested = requested
        self.limit = limit
