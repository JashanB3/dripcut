"""Repeatable no-AI clipping smoke test with first-result and resource timings."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure DripCut source registration and portrait clip rendering."
    )
    parser.add_argument("source", type=Path, help="A real MP4/MOV/WebM source video.")
    parser.add_argument("--durations", type=float, nargs="+", default=[15, 30, 45, 60])
    parser.add_argument("--count", type=int, default=1, help="Clips to render per duration.")
    parser.add_argument(
        "--output-format",
        choices=("source", "landscape", "portrait", "square"),
        default="portrait",
    )
    return parser.parse_args()


def _usage() -> tuple[float, int]:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime
    rss = max(own.ru_maxrss, children.ru_maxrss)
    divisor = 1024 if sys.platform != "darwin" else 1024 * 1024
    return cpu, int(rss / divisor)


def _configure_isolated_runtime(home: Path) -> None:
    values = {
        "DRIPCUT_HOME": str(home),
        "DRIPCUT_OUTPUT": str(home / "output"),
        "DRIPCUT_TEMP": str(home / "tmp"),
        "DRIPCUT_STORAGE_PROVIDER": "local",
        "DRIPCUT_AUTH_REQUIRED": "false",
        "DRIPCUT_MVP_PROFILE": "1",
        "DRIPCUT_CREATE_ZIP": "false",
        "DRIPCUT_RENDER_PROFILE": "720p",
        "DRIPCUT_FFMPEG_PRESET": "ultrafast",
        "DRIPCUT_MAX_OUTPUT_FPS": "30",
        "DRIPCUT_HARDWARE_ACCEL": "false",
        "DRIPCUT_MAX_WORKERS": "1",
        "DRIPCUT_MAX_CONCURRENT_VIDEO_JOBS": "1",
    }
    os.environ.update(values)


def _wait(service: Any, job_id: str) -> tuple[Any, float | None]:
    started = time.monotonic()
    first_artifact: float | None = None
    while True:
        job = service.jobs.get(job_id)
        if job is None:
            raise RuntimeError(f"Job {job_id} disappeared.")
        if first_artifact is None and service.artifacts.list_for_job(job_id):
            first_artifact = time.monotonic() - started
        if job.status.value in {"succeeded", "failed", "cancelled"}:
            return job, first_artifact
        time.sleep(0.05)


def main() -> int:
    args = _arguments()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        print(f"Source video not found: {source}", file=sys.stderr)
        return 2
    if args.count < 1 or any(duration <= 0 for duration in args.durations):
        print("Count and durations must be positive.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="dripcut-performance-") as temporary:
        _configure_isolated_runtime(Path(temporary))
        # Import after environment isolation so this script never writes to a
        # developer or production DripCut workspace.
        from dripcut.api.app import build_service
        from dripcut.api.contracts import RenderRequest, StandardPlanRequest

        service = build_service()
        results: list[dict[str, Any]] = []
        try:
            import_started = time.monotonic()
            with source.open("rb") as stream:
                imported = service.import_upload(source.name, stream)
            source_import_seconds = time.monotonic() - import_started

            for duration in args.durations:
                maximum = max(1, int((imported.duration + duration - 0.001) // duration))
                count = min(args.count, maximum)
                plan = service.standard_plan(
                    imported.id,
                    StandardPlanRequest(duration=duration, count=count),
                )
                request = RenderRequest(
                    source_id=imported.id,
                    segments=plan.segments,
                    output_format=args.output_format,
                    portrait_mode="center_crop",
                    auto_captions=False,
                    platforms=["youtube"],
                )
                cpu_before, rss_before = _usage()
                started = time.monotonic()
                queued = service.create_render(request)
                job, first_artifact = _wait(service, queued.id)
                wall = time.monotonic() - started
                cpu_after, rss_after = _usage()
                if job.status.value != "succeeded":
                    raise RuntimeError(job.error or f"Render {job.id} failed.")
                results.append(
                    {
                        "clip_duration_seconds": duration,
                        "clip_count": count,
                        "first_artifact_seconds": (
                            round(first_artifact, 3) if first_artifact is not None else None
                        ),
                        "total_seconds": round(wall, 3),
                        "cpu_seconds": round(cpu_after - cpu_before, 3),
                        "average_cpu_percent": round(
                            (cpu_after - cpu_before) / max(wall, 0.001) * 100, 1
                        ),
                        "peak_rss_mb": max(rss_before, rss_after),
                        "pipeline_timings": dict(
                            (job.result.data if job.result else {}).get("pipeline_timings", {})
                        ),
                    }
                )
        finally:
            queue = service.container.try_resolve("queue")
            if queue is not None:
                queue.shutdown(cancel_pending=False)

    print(
        json.dumps(
            {
                "source": str(source),
                "source_duration_seconds": round(imported.duration, 3),
                "source_import_seconds": round(source_import_seconds, 3),
                "profile": {
                    "output_format": args.output_format,
                    "resolution": "720p",
                    "max_output_fps": 30,
                    "preset": "ultrafast",
                    "captions": False,
                },
                "results": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
