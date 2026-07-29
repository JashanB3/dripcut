"""Export layer: presets, the job queue, and job creation through the service."""

from __future__ import annotations

import time

import pytest

from dripcut.core.errors import ValidationError
from dripcut.engines.export.presets import EXPORT_PRESETS, get_preset, preset_names
from dripcut.engines.export.queue import JobQueue
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


def _queue(paths, **kwargs) -> JobQueue:
    from dripcut.core.events import EventBus

    return JobQueue(EventBus(), history_file=paths.history_file, **kwargs)


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


def test_batch_rejects_an_empty_list(container) -> None:
    with pytest.raises(ValidationError):
        container.export.queue_batch([], "resize")


@needs_ffmpeg
def test_batch_rejects_an_unknown_operation(container, media) -> None:
    with pytest.raises(ValidationError):
        container.export.queue_batch([media], "teleport")
