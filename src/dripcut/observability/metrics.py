"""Aggregate bounded render timing telemetry from durable job history."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from dripcut.models.job import Job, JobStatus

_TOTAL_METRIC = "job_total_seconds"


def summarize_pipeline_jobs(jobs: Iterable[Job]) -> dict[str, Any]:
    """Return count, p50, p95, and max timings without exposing job-level data."""
    values: dict[str, list[float]] = defaultdict(list)
    completed = 0
    failed = 0

    for job in jobs:
        if job.status is JobStatus.FAILED:
            failed += 1
        if job.status is not JobStatus.SUCCEEDED:
            continue
        timings = job.metadata.get("pipeline_timings")
        if not isinstance(timings, dict):
            continue
        completed += 1
        if job.elapsed > 0:
            values[_TOTAL_METRIC].append(float(job.elapsed))
        for name, value in timings.items():
            if not name.endswith("_seconds") or isinstance(value, bool):
                continue
            if isinstance(value, int | float) and math.isfinite(float(value)) and value >= 0:
                values[name].append(float(value))

    stages = [
        {
            "name": name,
            "count": len(samples),
            "p50_seconds": round(_percentile(samples, 0.50), 3),
            "p95_seconds": round(_percentile(samples, 0.95), 3),
            "max_seconds": round(max(samples), 3),
        }
        for name, samples in sorted(values.items())
        if samples
    ]
    return {"completed_jobs": completed, "failed_jobs": failed, "stages": stages}


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
