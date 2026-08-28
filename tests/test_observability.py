"""Tests for privacy-safe aggregate performance telemetry."""

from dripcut.models.job import Job, JobKind, JobStatus
from dripcut.observability.metrics import summarize_pipeline_jobs


def _completed_job(total: float, render: float) -> Job:
    job = Job(kind=JobKind.SPLIT, title="render")
    job.status = JobStatus.SUCCEEDED
    job.started_at = 100.0
    job.finished_at = 100.0 + total
    job.metadata["pipeline_timings"] = {
        "clip_render_seconds": render,
        "zip_seconds": 1.0,
        "transcript_cache_hit": False,
        "clip_transcript_segments": 42,
    }
    return job


def test_pipeline_summary_reports_percentiles_without_job_content() -> None:
    summary = summarize_pipeline_jobs(
        [_completed_job(10, 5), _completed_job(20, 15), _completed_job(30, 25)]
    )

    assert summary["completed_jobs"] == 3
    render = next(
        stage for stage in summary["stages"] if stage["name"] == "clip_render_seconds"
    )
    assert render == {
        "name": "clip_render_seconds",
        "count": 3,
        "p50_seconds": 15.0,
        "p95_seconds": 24.0,
        "max_seconds": 25.0,
    }
    names = {stage["name"] for stage in summary["stages"]}
    assert "clip_transcript_segments" not in names
    assert "transcript_cache_hit" not in names
