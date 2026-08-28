"""Central plan limits with environment-based deployment overrides."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

from dripcut.usage.models import UsageMetric

PlanName = str

DEFAULT_PLAN_LIMITS: dict[PlanName, dict[UsageMetric, float | None]] = {
    "free": {
        "video_processing_minutes": 10,
        "ai_viral_analyses": 3,
        "transcription_minutes": 10,
        "thumbnail_generations": 4,
        "ai_editor_actions": 10,
        "scheduled_posts": 3,
        "youtube_imports": 3,
        "storage_bytes": 10 * 1024**3,
    },
    "creator": {
        "video_processing_minutes": 300,
        "ai_viral_analyses": 100,
        "transcription_minutes": 300,
        "thumbnail_generations": 100,
        "ai_editor_actions": 300,
        "scheduled_posts": 100,
        "youtube_imports": 100,
        "storage_bytes": 100 * 1024**3,
    },
    "pro": {
        "video_processing_minutes": 1200,
        "ai_viral_analyses": 500,
        "transcription_minutes": 1200,
        "thumbnail_generations": 500,
        "ai_editor_actions": 1500,
        "scheduled_posts": 500,
        "youtube_imports": 500,
        "storage_bytes": 500 * 1024**3,
    },
}


class EntitlementService:
    """Resolve every plan limit from one backend-owned configuration."""

    def __init__(self, limits: dict[PlanName, dict[UsageMetric, float | None]] | None = None) -> None:
        self._limits = limits or self._from_environment()

    @classmethod
    def _from_environment(cls) -> dict[PlanName, dict[UsageMetric, float | None]]:
        limits = deepcopy(DEFAULT_PLAN_LIMITS)
        configured = os.environ.get("DRIPCUT_PLAN_ENTITLEMENTS_JSON", "").strip()
        if not configured:
            return limits
        try:
            overrides: dict[str, Any] = json.loads(configured)
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("DRIPCUT_PLAN_ENTITLEMENTS_JSON must be valid JSON.") from error
        for plan, values in overrides.items():
            if not isinstance(values, dict):
                raise RuntimeError(f"Entitlements for {plan!r} must be a JSON object.")
            target = limits.setdefault(str(plan).lower(), deepcopy(limits["free"]))
            for metric, value in values.items():
                if metric not in target:
                    raise RuntimeError(f"Unknown usage entitlement: {metric}")
                if value is not None and (not isinstance(value, (int, float)) or value < 0):
                    raise RuntimeError(f"Entitlement {plan}.{metric} must be non-negative or null.")
                target[metric] = None if value is None else float(value)  # type: ignore[literal-required]
        return limits

    def limit(self, plan: PlanName, metric: UsageMetric) -> float | None:
        values = self._limits.get(plan.lower()) or self._limits["free"]
        return values[metric]

    def plan_label(self, plan: PlanName) -> str:
        return plan.strip().title() or "Free"

    def plans(self) -> tuple[str, ...]:
        return tuple(self._limits)
