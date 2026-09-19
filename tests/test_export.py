"""Export layer: presets, the job queue, and job creation through the service."""

from __future__ import annotations

import time

import pytest

from dripcut.core.errors import ValidationError
from dripcut.engines.export.presets import EXPORT_PRESETS, get_preset, preset_names
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.engines.video.encode import Quality
from dripcut.models.job import Job, JobKind, JobResult, JobStatus
from tests.conftest import needs_ffmpeg


def test_ten_presets_are_registered() -> None:
    assert len(EXPORT_PRESETS) == 10
    assert "Source quality" in preset_names()


@pytest.mark.parametrize("name", list(EXPORT_PRESETS))
def test_every_preset_is_coherent(name: str) -> None:
    preset = get_preset(name)
    assert preset.container
    assert preset.description
    if preset.height:
        assert preset.width, "a preset that fixes a height must fix a width too"


def test_vertical_preset_is_portrait() -> None:
    preset = get_preset("Vertical 1080x1920")
    assert preset.width == 1080 and preset.height == 1920


def test_audio_preset_is_flagged() -> None:
    assert get_preset("Audio only (M4A)").audio_only is True


def _queue(paths, **kwargs) -> LocalJobQueue:
    from dripcut.core.events import EventBus

    return LocalJobQueue(EventBus(), history_file=paths.history_file, **kwargs)


def test_queue_runs_a_job(paths) -> None:
    queue = _queue(paths)
    try:
        job = queue.submit(
            Job(kind=JobKind.TRIM, title="unit", run=lambda _job: JobResult(message="done"))
        )
        assert queue.wait(timeout=10)
        assert job.status is JobStatus.SUCCEEDED
        assert job.result.message == "done"
    finally:
        queue.shutdown()


def test_queue_records_failures_without_raising(paths) -> None:
    queue = _queue(paths)
    try:
        def explode(job: Job) -> JobResult:
            raise ValidationError("nope", hint="try again")

        job = queue.submit(Job(kind=JobKind.TRIM, title="bad", run=explode))
        assert queue.wait(timeout=10)
        assert job.status is JobStatus.FAILED
        assert "nope" in (job.error or "")
        assert job.hint
        assert job.metadata["error_code"] == "VALIDATION_ERROR"
        assert job.metadata["retryable"] is False
    finally:
        queue.shutdown()


def test_queue_hides_unexpected_worker_details(paths) -> None:
    queue = _queue(paths)
    try:
        def explode(_job: Job) -> JobResult:
            raise RuntimeError("/private/path provider-secret-detail")

        job = queue.submit(Job(kind=JobKind.TRIM, title="unexpected", run=explode))
        assert queue.wait(timeout=10)
        assert job.status is JobStatus.FAILED
        assert job.error == "Something went wrong while rendering."
        assert "private/path" not in (job.hint or "")
        assert "provider-secret-detail" not in (job.hint or "")
        assert job.metadata["error_code"] == "UNEXPECTED_WORKER_ERROR"
        assert job.metadata["retryable"] is True
    finally:
        queue.shutdown()


def test_queue_reports_progress(paths) -> None:
    queue = _queue(paths)
    try:
        def slow(job: Job) -> JobResult:
            for step in range(1, 4):
                job.set_progress(step / 3, f"step {step}")
            return JobResult(message="ok")

        job = queue.submit(Job(kind=JobKind.SPLIT, title="progress", run=slow))
        assert queue.wait(timeout=10)
        assert job.percent == 100
    finally:
        queue.shutdown()


def test_job_progress_does_not_regress_after_a_retry() -> None:
    job = Job(kind=JobKind.SPLIT, title="progress")

    job.set_progress(0.52, "Rendering clip 4")
    job.set_progress(0.38, "Retrying clip 4")

    assert job.progress == 0.52
    assert job.stage == "Retrying clip 4"


def test_stats_count_every_status(paths) -> None:
    queue = _queue(paths)
    try:
        queue.submit(Job(kind=JobKind.TRIM, title="one", run=lambda _job: JobResult()))
        queue.wait(timeout=10)
        stats = queue.stats()
        assert stats["succeeded"] >= 1
        assert set(stats) >= {status.value for status in JobStatus}
    finally:
        queue.shutdown()


def test_cancelling_an_unknown_id_is_false(paths) -> None:
    queue = _queue(paths)
    try:
        assert queue.cancel("does-not-exist") is False
    finally:
        queue.shutdown()


def test_clear_finished_empties_the_table(paths) -> None:
    queue = _queue(paths)
    try:
        queue.submit(Job(kind=JobKind.TRIM, title="one", run=lambda _job: JobResult()))
        queue.wait(timeout=10)
        assert queue.clear_finished() >= 1
        assert not [job for job in queue.all_jobs() if job.status.is_terminal]
    finally:
        queue.shutdown()


def test_history_persists_to_disk(paths) -> None:
    queue = _queue(paths)
    try:
        queue.submit(Job(kind=JobKind.TRIM, title="remembered", run=lambda _job: JobResult()))
        queue.wait(timeout=10)
    finally:
        queue.shutdown()
    assert paths.history_file.exists()


def test_queue_deduplicates_idempotent_submissions(paths) -> None:
    queue = _queue(paths)
    calls: list[str] = []
    try:
        first = Job(
            kind=JobKind.TRIM,
            title="first",
            idempotency_key="workspace:request-123",
            run=lambda _job: calls.append("ran") or JobResult(),
        )
        duplicate = Job(
            kind=JobKind.TRIM,
            title="duplicate",
            idempotency_key="workspace:request-123",
            run=lambda _job: calls.append("duplicate") or JobResult(),
        )
        assert queue.submit(first) is first
        assert queue.submit(duplicate) is first
        assert queue.wait(timeout=10)
        assert calls == ["ran"]
    finally:
        queue.shutdown()


def test_queue_retries_transient_work(paths) -> None:
    queue = _queue(paths)
    attempts: list[int] = []
    try:
        def flaky(_job: Job) -> JobResult:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("temporary failure")
            return JobResult(message="recovered")

        job = queue.submit(
            Job(kind=JobKind.TRIM, title="retry", run=flaky, max_attempts=2)
        )
        assert queue.wait(timeout=10)
        assert job.status is JobStatus.SUCCEEDED
        assert job.attempt == 2
        assert job.result and job.result.message == "recovered"
        assert job.error is None
        assert job.hint is None
        assert "error_code" not in job.metadata
        assert "retryable" not in job.metadata
    finally:
        queue.shutdown()


def test_queue_recovers_interrupted_state_as_retryable_failure(paths) -> None:
    from dripcut.core.events import EventBus
    from dripcut.engines.export.queue import JsonJobStateStore, LocalJobQueue

    interrupted = Job(kind=JobKind.SPLIT, title="interrupted")
    JsonJobStateStore(paths.history_file).save([interrupted.to_dict()])

    queue = LocalJobQueue(EventBus(), history_file=paths.history_file)
    try:
        recovered = queue.get(interrupted.id)
        assert recovered is not None
        assert recovered.status is JobStatus.FAILED
        assert recovered.metadata["error_code"] == "WORKER_RESTARTED"
        assert recovered.metadata["retryable"] is True
    finally:
        queue.shutdown()


def test_worker_limit_is_respected(paths) -> None:
    queue = _queue(paths, max_workers=1)
    running: list[int] = []
    try:
        def hold(job: Job) -> JobResult:
            running.append(1)
            time.sleep(0.2)
            assert len(running) <= 1, "two jobs ran at once with max_workers=1"
            running.pop()
            return JobResult()

        for index in range(3):
            queue.submit(Job(kind=JobKind.TRIM, title=f"job {index}", run=hold))
        assert queue.wait(timeout=20)
    finally:
        queue.shutdown()


@needs_ffmpeg
def test_service_queues_a_real_trim(container, media) -> None:
    job = container.export.queue_trim(media, start=0.0, end=1.0, quality=Quality.SMALL)
    assert container.resolve("queue").wait(timeout=90)
    assert job.status is JobStatus.SUCCEEDED, job.error
    assert job.result.outputs and job.result.outputs[0].exists()


@needs_ffmpeg
def test_service_queues_a_preset_export(container, media) -> None:
    job = container.export.queue_preset_export(media, "Audio only (M4A)")
    assert container.resolve("queue").wait(timeout=90)
    assert job.status is JobStatus.SUCCEEDED, job.error


def test_split_zip_archive_contains_every_clip(tmp_path) -> None:
    from zipfile import ZipFile

    from dripcut.services.split_service import SplitService

    destination = tmp_path / "clips"
    destination.mkdir()
    clips = []
    for index in range(2):
        clip = destination / f"clip-{index:03d}.mp4"
        clip.write_bytes(f"clip {index}".encode())
        clips.append(clip)

    archive = SplitService._zip_outputs(
        clips,
        destination,
        stem="Sample Video",
        output_format="portrait",
        portrait_mode="ai_tracking",
    )

    assert archive.exists()
    assert archive.name.startswith("Sample Video-portrait-ai_tracking")
    with ZipFile(archive) as handle:
        assert sorted(handle.namelist()) == sorted(clip.name for clip in clips)


def test_batch_rejects_an_empty_list(container) -> None:
    with pytest.raises(ValidationError):
        container.export.queue_batch([], "resize")


@needs_ffmpeg
def test_batch_rejects_an_unknown_operation(container, media) -> None:
    with pytest.raises(ValidationError):
        container.export.queue_batch([media], "teleport")
