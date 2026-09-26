from __future__ import annotations

import threading
import time

import pytest

from dripcut.acquisition.models import AcquisitionJob, AcquisitionStatus
from dripcut.acquisition.repository import LocalAcquisitionRepository


def _job() -> AcquisitionJob:
    return AcquisitionJob(workspace_id="workspace", owner_id="owner", project_id="project", source_url="https://www.youtube.com/watch?v=abc123")


def test_claim_is_atomic_when_two_workers_poll() -> None:
    repository = LocalAcquisitionRepository()
    repository.create(_job())
    claimed: list[AcquisitionJob | None] = []
    threads = [threading.Thread(target=lambda name=name: claimed.append(repository.claim_next(name, 60))) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len([job for job in claimed if job]) == 1


def test_expired_lease_is_claimable_again() -> None:
    repository = LocalAcquisitionRepository()
    job = repository.create(_job())
    assert repository.claim_next("one", 30)
    job.lease_expires_at = time.time() - 1
    claimed = repository.claim_next("two", 30)
    assert claimed and claimed.lease_owner == "two"
    assert claimed.attempt_count == 2


def test_heartbeat_requires_current_owner_and_renews_lease() -> None:
    repository = LocalAcquisitionRepository()
    job = repository.create(_job())
    repository.claim_next("one", 30)
    renewed = repository.heartbeat(job.id, "one", 60, status=AcquisitionStatus.RUNNING)
    assert renewed.status is AcquisitionStatus.RUNNING
    assert renewed.lease_expires_at and renewed.lease_expires_at > time.time() + 45
    with pytest.raises(PermissionError):
        repository.heartbeat(job.id, "two", 60, status=AcquisitionStatus.RUNNING)


def test_retry_then_terminal_failure_is_bounded() -> None:
    repository = LocalAcquisitionRepository()
    job = repository.create(_job())
    repository.claim_next("one", 60)
    retried = repository.fail(job.id, "one", code="TIMEOUT", message="timeout", retryable=True)
    assert retried.status is AcquisitionStatus.QUEUED
    repository.claim_next("two", 60)
    failed = repository.fail(job.id, "two", code="TIMEOUT", message="timeout", retryable=True)
    assert failed.status is AcquisitionStatus.FAILED


def test_completion_is_idempotent_and_cancellation_stops_claiming() -> None:
    repository = LocalAcquisitionRepository()
    job = repository.create(_job())
    repository.claim_next("one", 60)
    completed = repository.complete(job.id, "one", storage_key=f"acquisitions/{job.id}/source.mp4", metadata={"title": "Demo"})
    assert repository.complete(job.id, "one", storage_key=completed.output_storage_key or "", metadata={}).status is AcquisitionStatus.COMPLETED
    cancelled = repository.create(_job())
    repository.cancel(cancelled.id)
    assert repository.claim_next("two", 60) is None


def test_idle_worker_heartbeat_is_visible_without_a_job() -> None:
    repository = LocalAcquisitionRepository()
    repository.heartbeat_worker("mac-1", current_job_id=None, status="idle", version="1")
    status = repository.worker_status("mac-1")
    assert status and status["status"] == "idle"
