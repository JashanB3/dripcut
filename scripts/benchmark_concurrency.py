"""Measure safe queue behavior for several simultaneously submitted render jobs."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path
from typing import Any

from dripcut.api.app import build_service
from dripcut.api.contracts import RenderRequest, StandardPlanRequest


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--clip-duration", type=float, default=15.0)
    parser.add_argument("--job-counts", type=int, nargs="+", default=[1, 3, 5])
    return parser.parse_args()


def _usage() -> tuple[float, float, int]:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return (
        own.ru_utime + children.ru_utime,
        own.ru_stime + children.ru_stime,
        max(own.ru_maxrss, children.ru_maxrss),
    )


def _rss_megabytes(value: int) -> float:
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 1)


def main() -> int:
    args = _arguments()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        print(f"Source video not found: {source}", file=sys.stderr)
        return 2
    service = build_service()
    try:
        with source.open("rb") as stream:
            imported = service.import_upload(source.name, stream)
        source_record = service.sources.get(imported.id)
        service.container.ai.transcribe(
            source_record.path,
            source_asset_id=source_record.id,
        )
        plan = service.standard_plan(
            imported.id,
            StandardPlanRequest(duration=args.clip_duration, count=1),
        )
        request = RenderRequest(
            source_id=imported.id,
            segments=plan.segments,
            output_format="portrait",
            portrait_mode="center_crop",
            auto_captions=True,
        )
        results: list[dict[str, Any]] = []
        for count in args.job_counts:
            before_user, before_system, before_memory = _usage()
            started = time.monotonic()
            jobs = [service.create_render(request) for _ in range(count)]
            peak_running = 0
            peak_queued = 0
            while True:
                current = [service.jobs.get(item.id) for item in jobs]
                running = sum(job is not None and job.status.value == "running" for job in current)
                queued = sum(job is not None and job.status.value == "queued" for job in current)
                peak_running = max(peak_running, running)
                peak_queued = max(peak_queued, queued)
                if all(
                    job is not None
                    and job.status.value in {"succeeded", "failed", "cancelled"}
                    for job in current
                ):
                    break
                time.sleep(0.1)
            wall = time.monotonic() - started
            after_user, after_system, after_memory = _usage()
            failed = [
                job.id
                for job in current
                if job is not None and job.status.value != "succeeded"
            ]
            cpu_seconds = (after_user - before_user) + (after_system - before_system)
            results.append(
                {
                    "submitted_jobs": count,
                    "clip_duration_seconds": args.clip_duration,
                    "wall_seconds": round(wall, 3),
                    "peak_running_jobs": peak_running,
                    "peak_queued_jobs": peak_queued,
                    "cpu_user_seconds": round(after_user - before_user, 3),
                    "cpu_system_seconds": round(after_system - before_system, 3),
                    "average_cpu_percent": round(cpu_seconds / max(wall, 0.001) * 100, 1),
                    "peak_rss_mb": _rss_megabytes(max(before_memory, after_memory)),
                    "failures": failed,
                }
            )
        print(json.dumps({"source": str(source), "results": results}, indent=2))
        return 0
    finally:
        queue = service.container.try_resolve("queue")
        if queue is not None:
            queue.shutdown(cancel_pending=False)


if __name__ == "__main__":
    raise SystemExit(main())
