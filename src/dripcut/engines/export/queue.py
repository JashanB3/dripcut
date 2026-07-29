"""The export queue: bounded parallelism, live progress, cancellable jobs.

Concurrency is deliberately low (two workers by default). FFmpeg already uses every
core; running six encodes at once on 8 GB of unified memory makes all six slower and
starves the UI. The queue's job is fairness and visibility, not maximum parallelism.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from dripcut.core.errors import DripCutError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.models.job import Job, JobResult, JobStatus
from dripcut.utils.concurrency import OperationCancelled

__all__ = ["JobQueue"]

_log = get_logger("engines.export.queue")


class JobQueue:
    """Thread-pool backed job runner with an observable history."""

    def __init__(
        self,
        events: EventBus,
        *,
        max_workers: int = 2,
        history_file: Path | None = None,
        history_limit: int = 200,
    ) -> None:
        self.events = events
        self.max_workers = max(1, int(max_workers))
        self.history_file = history_file
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers, thread_name_prefix="dripcut-job"
        )
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._futures: dict[str, Future[None]] = {}
        self._history: deque[dict[str, object]] = deque(maxlen=history_limit)
        self._lock = threading.RLock()
        self._load_history()

    # -------------------------------------------------------------- submission

    def submit(self, job: Job) -> Job:
        """Queue a job and return it immediately."""
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._futures[job.id] = self._executor.submit(self._run, job)
        self.events.publish(EventName.JOB_QUEUED, job_id=job.id, title=job.title, kind=job.kind.value)
        _log.info("queued %s: %s", job.kind.value, job.title)
        return job

    def submit_callable(
        self,
        job: Job,
        work: Callable[[Job], JobResult],
    ) -> Job:
        """Attach ``work`` to ``job`` and queue it."""
        job.run = work
        return self.submit(job)

    # ------------------------------------------------------------------ queries

    def get(self, job_id: str) -> Job | None:
        """Look up a job by id."""
        with self._lock:
            return self._jobs.get(job_id)

    def all_jobs(self, *, limit: int | None = None, newest_first: bool = True) -> list[Job]:
        """Every job still held in memory."""
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in self._order if job_id in self._jobs]
        jobs.sort(key=lambda job: job.created_at, reverse=newest_first)
        return jobs[:limit] if limit else jobs

    def active_jobs(self) -> list[Job]:
        """Jobs that are queued or running."""
        return [job for job in self.all_jobs() if job.is_active]

    def stats(self) -> dict[str, int]:
        """Counts by status, for the status bar."""
        counts = {status.value: 0 for status in JobStatus}
        for job in self.all_jobs():
            counts[job.status.value] += 1
        return counts

    @property
    def busy(self) -> bool:
        """True when anything is queued or running."""
        return bool(self.active_jobs())

    def history(self, limit: int = 50) -> list[dict[str, object]]:
        """Persisted records of finished jobs, newest first."""
        with self._lock:
            return list(self._history)[-limit:][::-1]

    # ------------------------------------------------------------------ control

    def cancel(self, job_id: str) -> bool:
        """Cancel one job. Returns True when the job existed and was active."""
        job = self.get(job_id)
        if job is None or not job.is_active:
            return False
        job.cancel()
        with self._lock:
            future = self._futures.get(job_id)
        if future is not None:
            future.cancel()  # only succeeds if it has not started
        if job.status is JobStatus.CANCELLED:
            self.events.publish(EventName.JOB_CANCELLED, job_id=job.id, title=job.title)
        return True

    def cancel_all(self) -> int:
        """Cancel every active job. Returns how many were cancelled."""
        return sum(1 for job in self.active_jobs() if self.cancel(job.id))

    def clear_finished(self) -> int:
        """Drop terminal jobs from memory. Returns how many were removed."""
        removed = 0
        with self._lock:
            for job_id in list(self._order):
                job = self._jobs.get(job_id)
                if job is not None and job.status.is_terminal:
                    self._jobs.pop(job_id, None)
                    self._futures.pop(job_id, None)
                    self._order.remove(job_id)
                    removed += 1
        return removed

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the queue drains. Returns True if it drained in time."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.busy:
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.1)
        return True

    def shutdown(self, *, cancel_pending: bool = True) -> None:
        """Stop accepting work and let running jobs finish."""
        if cancel_pending:
            self.cancel_all()
        self._executor.shutdown(wait=False, cancel_futures=cancel_pending)
        self._save_history()

    # ----------------------------------------------------------------- internals

    def _run(self, job: Job) -> None:
        """Execute one job on a worker thread, translating outcomes into events."""
        if job.cancel_token.cancelled:
            job.status = JobStatus.CANCELLED
            job.finished_at = time.time()
            self.events.publish(EventName.JOB_CANCELLED, job_id=job.id, title=job.title)
            return

        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.stage = job.stage or "Starting"
        self.events.publish(EventName.JOB_STARTED, job_id=job.id, title=job.title)

        try:
            if job.run is None:
                raise DripCutError("This job has nothing to do.")
            result = job.run(job)
            job.result = result if isinstance(result, JobResult) else JobResult()
            job.status = JobStatus.SUCCEEDED
            job.progress = 1.0
            job.stage = "Done"
            self.events.publish(
                EventName.JOB_SUCCEEDED,
                job_id=job.id,
                title=job.title,
                outputs=[str(p) for p in job.result.outputs],
                message=job.result.message,
            )
            _log.info("finished %s in %s", job.title, job.elapsed_label)
        except OperationCancelled:
            job.status = JobStatus.CANCELLED
            job.stage = "Cancelled"
            self.events.publish(EventName.JOB_CANCELLED, job_id=job.id, title=job.title)
            _log.info("cancelled %s", job.title)
        except DripCutError as exc:
            job.status = JobStatus.FAILED
            job.error = exc.message
            job.hint = exc.hint
            job.stage = "Failed"
            self.events.publish(
                EventName.JOB_FAILED, job_id=job.id, title=job.title, error=exc.message, hint=exc.hint
            )
            _log.warning("job failed: %s (%s)", job.title, exc)
        except Exception as exc:  # noqa: BLE001 - last line of defence
            job.status = JobStatus.FAILED
            job.error = "Something went wrong while rendering."
            job.hint = str(exc)[:200]
            job.stage = "Failed"
            self.events.publish(
                EventName.JOB_FAILED, job_id=job.id, title=job.title, error=job.error, hint=job.hint
            )
            _log.exception("unexpected job failure: %s", job.title)
        finally:
            job.finished_at = time.time()
            self._record(job)

    def _record(self, job: Job) -> None:
        """Append a finished job to the history and persist it."""
        with self._lock:
            self._history.append(job.to_dict())
        self._save_history()

    def _load_history(self) -> None:
        """Read the job history written by a previous session."""
        if not self.history_file or not self.history_file.exists():
            return
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data[-self._history.maxlen :]:
                    if isinstance(entry, dict):
                        self._history.append(entry)
        except (json.JSONDecodeError, OSError):
            _log.debug("could not read job history", exc_info=True)

    def _save_history(self) -> None:
        """Persist the history atomically; failures are non-fatal."""
        if not self.history_file:
            return
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_file.with_suffix(".json.tmp")
            with self._lock:
                payload = list(self._history)
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.history_file)
        except OSError:
            _log.debug("could not write job history", exc_info=True)
