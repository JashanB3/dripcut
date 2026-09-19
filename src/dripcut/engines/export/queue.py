"""Durable job queue contracts and the lightweight local implementation."""

from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from dripcut.core.errors import DripCutError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.models.job import Job, JobResult, JobStatus
from dripcut.utils.concurrency import OperationCancelled

__all__ = ["JobQueue", "JobStateStore", "JsonJobStateStore", "LocalJobQueue"]

_log = get_logger("engines.export.queue")
_STATE_VERSION = 1


class JobStateStore(ABC):
    """Persistence boundary shared by local, Redis and SQS-backed queues."""

    @abstractmethod
    def load(self) -> list[dict[str, Any]]:
        """Load serialized jobs in submission order."""

    @abstractmethod
    def save(self, jobs: list[dict[str, Any]]) -> None:
        """Atomically replace the persisted job snapshot."""


class JsonJobStateStore(JobStateStore):
    """Atomic JSON state store for development and single-instance hosting."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def load(self) -> list[dict[str, Any]]:
        if self.path is None or not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _log.warning("could not read durable job state", exc_info=True)
            return []
        # Versions before the durable queue stored a bare terminal-history list.
        records = payload.get("jobs", []) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return []
        return [record for record in records if isinstance(record, dict)]

    def save(self, jobs: list[dict[str, Any]]) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary.write_text(
                json.dumps({"version": _STATE_VERSION, "jobs": jobs}, indent=1),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            _log.warning("could not persist durable job state", exc_info=True)


class JobQueue(ABC):
    """Queue contract implemented locally now and by remote workers later."""

    @abstractmethod
    def submit(self, job: Job) -> Job:
        """Persist and enqueue a job, or return its idempotent predecessor."""

    @abstractmethod
    def submit_callable(self, job: Job, work: Callable[[Job], JobResult]) -> Job:
        """Attach local work and enqueue it."""

    @abstractmethod
    def get(self, job_id: str) -> Job | None:
        """Return one job when it exists."""

    @abstractmethod
    def get_by_idempotency_key(self, key: str) -> Job | None:
        """Find a job submitted with a stable external request key."""

    @abstractmethod
    def resume_callable(
        self, job_id: str, work: Callable[[Job], JobResult]
    ) -> Job | None:
        """Reattach local work to an interrupted terminal job and retry it."""

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Request cancellation of queued or running work."""


class LocalJobQueue(JobQueue):
    """Threaded development worker with durable state and bounded concurrency.

    Python callables cannot be reconstructed after a process restart. Interrupted
    jobs are recovered as explicit retryable failures rather than being lost or
    falsely left running. A Redis/SQS worker can implement the same queue contract
    using serialized job handlers and payloads.
    """

    def __init__(
        self,
        events: EventBus,
        *,
        max_workers: int = 1,
        history_file: Path | None = None,
        history_limit: int = 200,
        state_store: JobStateStore | None = None,
        progress_persist_interval: float = 0.25,
    ) -> None:
        self.events = events
        self.max_workers = max(1, int(max_workers))
        self.history_file = history_file
        self.state_store = state_store or JsonJobStateStore(history_file)
        self._history_limit = max(1, int(history_limit))
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="dripcut-job"
        )
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._futures: dict[str, Future[None]] = {}
        self._idempotency: dict[str, str] = {}
        self._last_persisted: dict[str, float] = {}
        self._progress_persist_interval = max(0.05, progress_persist_interval)
        self._lock = threading.RLock()
        self._closed = False
        self._load_state()

    def submit(self, job: Job) -> Job:
        """Persist a job before dispatch so accepted work is never invisible."""
        with self._lock:
            if self._closed:
                raise RuntimeError("The job queue is shutting down.")
            if job.idempotency_key:
                existing = self.get_by_idempotency_key(job.idempotency_key)
                if existing is not None:
                    return existing
            job.max_attempts = max(1, int(job.max_attempts))
            job.bind_change_callback(self._job_changed)
            self._jobs[job.id] = job
            if job.id not in self._order:
                self._order.append(job.id)
            if job.idempotency_key:
                self._idempotency[job.idempotency_key] = job.id
            self._save_state_locked()
            self._futures[job.id] = self._executor.submit(self._run, job)
        self.events.publish(
            EventName.JOB_QUEUED,
            job_id=job.id,
            title=job.title,
            kind=job.kind.value,
        )
        _log.info("queued %s: %s", job.kind.value, job.title)
        return job

    def submit_callable(self, job: Job, work: Callable[[Job], JobResult]) -> Job:
        job.run = work
        return self.submit(job)

    def retry(self, job_id: str) -> Job | None:
        """Retry a terminal local job while its callable remains available."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not job.status.is_terminal or job.run is None or self._closed:
                return None
            job.cancel_token = type(job.cancel_token)()
            job.status = JobStatus.QUEUED
            job.progress = 0.0
            job.stage = "Queued for retry"
            job.started_at = None
            job.finished_at = None
            job.error = None
            job.hint = None
            job.result = None
            job.attempt = 0
            self._save_state_locked()
            self._futures[job.id] = self._executor.submit(self._run, job)
        self.events.publish(EventName.JOB_QUEUED, job_id=job.id, title=job.title)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_by_idempotency_key(self, key: str) -> Job | None:
        with self._lock:
            job_id = self._idempotency.get(key)
            return self._jobs.get(job_id) if job_id else None

    def resume_callable(
        self, job_id: str, work: Callable[[Job], JobResult]
    ) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or not job.status.is_terminal or self._closed:
                return None
            job.run = work
        return self.retry(job_id)

    def all_jobs(self, *, limit: int | None = None, newest_first: bool = True) -> list[Job]:
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in self._order if job_id in self._jobs]
        jobs.sort(key=lambda job: job.created_at, reverse=newest_first)
        return jobs[:limit] if limit else jobs

    def active_jobs(self) -> list[Job]:
        return [job for job in self.all_jobs() if job.is_active]

    def stats(self) -> dict[str, int]:
        counts = {status.value: 0 for status in JobStatus}
        for job in self.all_jobs():
            counts[job.status.value] += 1
        return counts

    @property
    def busy(self) -> bool:
        return bool(self.active_jobs())

    def history(self, limit: int = 50) -> list[dict[str, object]]:
        jobs = [job for job in self.all_jobs() if job.status.is_terminal]
        return [job.to_dict() for job in jobs[:limit]]

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or not job.is_active:
            return False
        job.cancel()
        with self._lock:
            future = self._futures.get(job_id)
            cancelled_before_start = future.cancel() if future is not None else False
            if cancelled_before_start:
                self._finish_cancelled(job)
        return True

    def cancel_all(self) -> int:
        return sum(1 for job in self.active_jobs() if self.cancel(job.id))

    def clear_finished(self) -> int:
        removed = 0
        with self._lock:
            for job_id in list(self._order):
                job = self._jobs.get(job_id)
                if job is not None and job.status.is_terminal:
                    self._jobs.pop(job_id, None)
                    self._futures.pop(job_id, None)
                    self._order.remove(job_id)
                    if job.idempotency_key:
                        self._idempotency.pop(job.idempotency_key, None)
                    removed += 1
            self._save_state_locked()
        return removed

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                pending = any(not future.done() for future in self._futures.values())
            if not pending:
                return True
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.1)

    def shutdown(self, *, cancel_pending: bool = True) -> None:
        with self._lock:
            self._closed = True
        if cancel_pending:
            self.cancel_all()
        self._executor.shutdown(wait=False, cancel_futures=cancel_pending)
        self._save_state()

    def _run(self, job: Job) -> None:
        if job.cancel_token.cancelled:
            self._finish_cancelled(job)
            return

        while job.attempt < job.max_attempts:
            job.attempt += 1
            job.status = JobStatus.RUNNING
            job.started_at = job.started_at or time.time()
            job.finished_at = None
            job.stage = "Starting" if job.attempt == 1 else f"Retry {job.attempt}"
            self._save_state()
            self.events.publish(EventName.JOB_STARTED, job_id=job.id, title=job.title)

            try:
                if job.run is None:
                    raise DripCutError("This job has nothing to do.")
                result = job.run(job)
                job.result = result if isinstance(result, JobResult) else JobResult()
                job.error = None
                job.hint = None
                job.metadata.pop("error_code", None)
                job.metadata.pop("retryable", None)
                job.status = JobStatus.SUCCEEDED
                job.progress = 1.0
                job.stage = "Done"
                self.events.publish(
                    EventName.JOB_SUCCEEDED,
                    job_id=job.id,
                    title=job.title,
                    outputs=[str(path) for path in job.result.outputs],
                    message=job.result.message,
                )
                _log.info("finished %s in %s", job.title, job.elapsed_label)
                break
            except OperationCancelled:
                self._finish_cancelled(job, persist=False)
                break
            except Exception as exc:  # noqa: BLE001 - worker isolation boundary
                will_retry = (
                    job.attempt < job.max_attempts and not job.cancel_token.cancelled
                )
                self._apply_failure(job, exc, terminal=not will_retry)
                if not will_retry:
                    self._publish_failure(job)
                    break
                job.status = JobStatus.QUEUED
                job.stage = f"Retrying ({job.attempt + 1}/{job.max_attempts})"
                self._save_state()
                if job.retry_backoff_seconds and job.cancel_token.wait(job.retry_backoff_seconds):
                    self._finish_cancelled(job, persist=False)
                    break

        job.finished_at = time.time()
        self._save_state()

    def _apply_failure(self, job: Job, exc: Exception, *, terminal: bool = True) -> None:
        # A retry-pending job must remain nonterminal so waiters do not return early.
        job.status = JobStatus.FAILED if terminal else JobStatus.RUNNING
        job.stage = "Failed" if terminal else "Retry pending"
        if isinstance(exc, DripCutError):
            job.error = exc.message
            job.hint = exc.hint
            if error_code := getattr(exc, "code", None):
                job.metadata["error_code"] = str(error_code)
            job.metadata["retryable"] = bool(exc.retryable)
        else:
            job.error = "Something went wrong while rendering."
            job.hint = "Try the render again. If it still fails, contact support with the job ID."
            job.metadata.setdefault("error_code", "UNEXPECTED_WORKER_ERROR")
            job.metadata["retryable"] = True
            _log.exception("unexpected worker failure job_id=%s title=%s", job.id, job.title)
        job.metadata["last_attempt"] = job.attempt

    def _publish_failure(self, job: Job) -> None:
        self.events.publish(
            EventName.JOB_FAILED,
            job_id=job.id,
            title=job.title,
            error=job.error,
            hint=job.hint,
        )
        _log.warning("job failed after %d attempt(s): %s", job.attempt, job.title)

    def _finish_cancelled(self, job: Job, *, persist: bool = True) -> None:
        job.status = JobStatus.CANCELLED
        job.stage = "Cancelled"
        job.finished_at = time.time()
        self.events.publish(EventName.JOB_CANCELLED, job_id=job.id, title=job.title)
        if persist:
            self._save_state()

    def _job_changed(self, job: Job) -> None:
        now = time.monotonic()
        with self._lock:
            last = self._last_persisted.get(job.id, 0.0)
            if not job.status.is_terminal and now - last < self._progress_persist_interval:
                return
            self._last_persisted[job.id] = now
            self._save_state_locked()

    def _load_state(self) -> None:
        recovered = False
        for payload in self.state_store.load()[-self._history_limit :]:
            try:
                job = Job.from_dict(payload)
            except (TypeError, ValueError):
                _log.warning("skipping invalid persisted job", exc_info=True)
                continue
            if job.is_active:
                job.status = JobStatus.FAILED
                job.stage = "Interrupted"
                job.finished_at = time.time()
                job.error = "The worker restarted before this job finished."
                job.hint = "Start this render again. Your source video is still available."
                job.metadata["error_code"] = "WORKER_RESTARTED"
                job.metadata["retryable"] = True
                recovered = True
            job.bind_change_callback(self._job_changed)
            self._jobs[job.id] = job
            self._order.append(job.id)
            if job.idempotency_key:
                self._idempotency[job.idempotency_key] = job.id
        if recovered:
            self._save_state()

    def _save_state(self) -> None:
        with self._lock:
            self._save_state_locked()

    def _save_state_locked(self) -> None:
        ordered = [
            self._jobs[job_id].to_dict()
            for job_id in self._order
            if job_id in self._jobs
        ]
        if len(ordered) > self._history_limit:
            ordered = ordered[-self._history_limit :]
        self.state_store.save(ordered)
