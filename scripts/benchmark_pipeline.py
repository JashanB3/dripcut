"""Run an honest repeatable DripCut transcription and render benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from dripcut.api.app import build_service
from dripcut.api.contracts import RenderRequest, StandardPlanRequest


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark source import, transcription, caption rendering, and cache reuse."
    )
    parser.add_argument("source", type=Path, help="A spoken source video, ideally 10 minutes.")
    parser.add_argument("--clip-duration", type=float, default=30.0)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument(
        "--output-format",
        choices=("source", "landscape", "portrait", "square"),
        default="portrait",
    )
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument(
        "--keep-existing-cache",
        action="store_true",
        help="Do not clear this source/provider transcript before run 1.",
    )
    parser.add_argument(
        "--allow-local",
        action="store_true",
        help="Permit local Whisper when GROQ_API_KEY is not configured.",
    )
    return parser.parse_args()


def _wait_for_job(service: Any, job_id: str) -> Any:
    while True:
        job = service.jobs.get(job_id)
        if job is None:
            raise RuntimeError(f"Benchmark job {job_id} disappeared.")
        if job.status.value in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.25)


def main() -> int:
    args = _arguments()
    source = args.source.expanduser().resolve()
    if not source.is_file():
        print(f"Source video not found: {source}", file=sys.stderr)
        return 2
    if args.runs < 1 or args.count < 1 or args.clip_duration <= 0:
        print("Runs, count, and clip duration must be positive.", file=sys.stderr)
        return 2

    service = build_service()
    provider = service.container.ai.active_transcription_provider
    if provider.name != "groq" and not args.allow_local:
        print(
            "CONFIGURATION REQUIRED: set GROQ_API_KEY on the backend, then rerun. "
            "Use --allow-local only when intentionally benchmarking local Whisper.",
            file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    try:
        if not args.keep_existing_cache:
            service.container.ai.cache_path(source, provider).unlink(missing_ok=True)
        for run_number in range(1, args.runs + 1):
            total_started = time.monotonic()
            import_started = time.monotonic()
            with source.open("rb") as stream:
                imported = service.import_upload(source.name, stream)
            source_import_seconds = round(time.monotonic() - import_started, 3)
            plan = service.standard_plan(
                imported.id,
                StandardPlanRequest(duration=args.clip_duration, count=args.count),
            )
            request = RenderRequest(
                source_id=imported.id,
                segments=plan.segments,
                output_format=args.output_format,
                portrait_mode="center_crop",
                auto_captions=True,
            )
            queued = service.create_render(request)
            job = _wait_for_job(service, queued.id)
            if job.status.value != "succeeded":
                raise RuntimeError(job.error or f"Benchmark run {run_number} failed.")
            pipeline = dict(job.result.data.get("pipeline_timings", {}))
            outputs = [
                {
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                }
                for path in job.result.outputs
                if path.is_file()
            ]
            results.append(
                {
                    "run": run_number,
                    "provider": provider.name,
                    "model": provider.model,
                    "source_duration_seconds": imported.duration,
                    "source_import_seconds": source_import_seconds,
                    **pipeline,
                    "render_job_seconds": round(job.elapsed, 3),
                    "total_seconds": round(time.monotonic() - total_started, 3),
                    "outputs": outputs,
                }
            )
    finally:
        queue = service.container.try_resolve("queue")
        if queue is not None:
            queue.shutdown(cancel_pending=False)

    print(json.dumps({"source": str(source), "runs": results}, indent=2))
    if not 540 <= results[0]["source_duration_seconds"] <= 660:
        print(
            "NOTE: the source is not approximately 10 minutes; do not use these numbers "
            "as the requested 10-minute benchmark.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
