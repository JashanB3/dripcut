"""Acquisition-job persistence behind a local test implementation and Supabase RPCs."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx

from dripcut.acquisition.models import AcquisitionJob, AcquisitionStatus


class AcquisitionRepository(Protocol):
    def create(self, job: AcquisitionJob) -> AcquisitionJob: ...
    def get(self, job_id: str) -> AcquisitionJob | None: ...
    def claim_next(self, worker_id: str, lease_seconds: int) -> AcquisitionJob | None: ...
    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int, *, status: AcquisitionStatus) -> AcquisitionJob: ...
    def complete(self, job_id: str, worker_id: str, *, storage_key: str, metadata: dict[str, object]) -> AcquisitionJob: ...
    def fail(self, job_id: str, worker_id: str, *, code: str, message: str, retryable: bool) -> AcquisitionJob: ...
    def cancel(self, job_id: str) -> AcquisitionJob: ...
    def heartbeat_worker(self, worker_id: str, *, current_job_id: str | None, status: str, version: str) -> None: ...
    def worker_status(self, worker_id: str) -> dict[str, object] | None: ...


class LocalAcquisitionRepository:
    """Lock-protected implementation used in tests and local API development."""

    def __init__(self) -> None:
        self._jobs: dict[str, AcquisitionJob] = {}
        self._workers: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def create(self, job: AcquisitionJob) -> AcquisitionJob:
        with self._lock:
            self._jobs[job.id] = job
            return job

    def get(self, job_id: str) -> AcquisitionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def claim_next(self, worker_id: str, lease_seconds: int) -> AcquisitionJob | None:
        now = time.time()
        with self._lock:
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at):
                expired = job.lease_expires_at is not None and job.lease_expires_at <= now
                if job.status is AcquisitionStatus.CLAIMED and expired:
                    job.status, job.lease_owner = AcquisitionStatus.QUEUED, None
                if job.status is not AcquisitionStatus.QUEUED:
                    continue
                if job.attempt_count >= job.max_attempts:
                    job.status, job.completed_at = AcquisitionStatus.FAILED, now
                    continue
                job.status = AcquisitionStatus.CLAIMED
                job.attempt_count += 1
                job.lease_owner = worker_id
                job.lease_expires_at = now + lease_seconds
                job.heartbeat_at = now
                job.started_at = job.started_at or now
                return job
        return None

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int, *, status: AcquisitionStatus) -> AcquisitionJob:
        with self._lock:
            job = self._owned(job_id, worker_id)
            job.status, job.heartbeat_at = status, time.time()
            job.lease_expires_at = job.heartbeat_at + lease_seconds
            return job

    def complete(self, job_id: str, worker_id: str, *, storage_key: str, metadata: dict[str, object]) -> AcquisitionJob:
        with self._lock:
            job = self._jobs[job_id]
            if job.status is AcquisitionStatus.COMPLETED:
                return job
            job = self._owned(job_id, worker_id)
            job.status, job.output_storage_key, job.metadata = AcquisitionStatus.COMPLETED, storage_key, dict(metadata)
            job.completed_at, job.lease_expires_at = time.time(), None
            return job

    def fail(self, job_id: str, worker_id: str, *, code: str, message: str, retryable: bool) -> AcquisitionJob:
        with self._lock:
            job = self._owned(job_id, worker_id)
            job.error_code, job.error_message, job.lease_owner, job.lease_expires_at = code, message, None, None
            if retryable and job.attempt_count < job.max_attempts:
                job.status = AcquisitionStatus.QUEUED
            else:
                job.status, job.completed_at = AcquisitionStatus.FAILED, time.time()
            return job

    def cancel(self, job_id: str) -> AcquisitionJob:
        with self._lock:
            job = self._jobs[job_id]
            if not job.is_terminal:
                job.status, job.completed_at = AcquisitionStatus.CANCELLED, time.time()
            return job

    def heartbeat_worker(self, worker_id: str, *, current_job_id: str | None, status: str, version: str) -> None:
        with self._lock:
            self._workers[worker_id] = {"id": worker_id, "current_job_id": current_job_id, "status": status, "version": version, "last_seen_at": time.time()}

    def worker_status(self, worker_id: str) -> dict[str, object] | None:
        with self._lock:
            return self._workers.get(worker_id)

    def _owned(self, job_id: str, worker_id: str) -> AcquisitionJob:
        job = self._jobs[job_id]
        if job.lease_owner != worker_id or job.lease_expires_at is None or job.lease_expires_at <= time.time():
            raise PermissionError("The acquisition job lease is no longer valid.")
        return job


class SupabaseAcquisitionRepository:
    """Server-side repository. Claiming occurs in PostgreSQL, never in Python."""

    def __init__(self, url: str, service_key: str) -> None:
        self.url, self.service_key = url.rstrip("/"), service_key

    @classmethod
    def from_environment(cls) -> SupabaseAcquisitionRepository:
        url, key = os.environ.get("SUPABASE_URL", "").strip(), os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        if not url or not key:
            raise RuntimeError("Supabase URL and service-role key are required for worker acquisition mode.")
        return cls(url, key)

    def create(self, job: AcquisitionJob) -> AcquisitionJob:
        row = self._request("POST", "/rest/v1/acquisition_jobs", self._payload(job), prefer="return=representation")[0]
        return self._job(row)

    def get(self, job_id: str) -> AcquisitionJob | None:
        rows = self._request("GET", f"/rest/v1/acquisition_jobs?id=eq.{job_id}&limit=1")
        return self._job(rows[0]) if rows else None

    def claim_next(self, worker_id: str, lease_seconds: int) -> AcquisitionJob | None:
        rows = self._request("POST", "/rest/v1/rpc/claim_acquisition_job", {"p_worker_id": worker_id, "p_lease_seconds": lease_seconds})
        return self._job(rows[0]) if rows else None

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int, *, status: AcquisitionStatus) -> AcquisitionJob:
        rows = self._request("POST", "/rest/v1/rpc/heartbeat_acquisition_job", {"p_job_id": job_id, "p_worker_id": worker_id, "p_lease_seconds": lease_seconds, "p_status": status.value})
        return self._job(rows[0])

    def complete(self, job_id: str, worker_id: str, *, storage_key: str, metadata: dict[str, object]) -> AcquisitionJob:
        rows = self._request("POST", "/rest/v1/rpc/complete_acquisition_job", {"p_job_id": job_id, "p_worker_id": worker_id, "p_storage_key": storage_key, "p_metadata": metadata})
        return self._job(rows[0])

    def fail(self, job_id: str, worker_id: str, *, code: str, message: str, retryable: bool) -> AcquisitionJob:
        rows = self._request("POST", "/rest/v1/rpc/fail_acquisition_job", {"p_job_id": job_id, "p_worker_id": worker_id, "p_error_code": code, "p_error_message": message, "p_retryable": retryable})
        return self._job(rows[0])

    def cancel(self, job_id: str) -> AcquisitionJob:
        rows = self._request("PATCH", f"/rest/v1/acquisition_jobs?id=eq.{job_id}&status=in.(queued,claimed)", {"status": "cancelled"}, prefer="return=representation")
        return self._job(rows[0])

    def heartbeat_worker(self, worker_id: str, *, current_job_id: str | None, status: str, version: str) -> None:
        self._request("POST", "/rest/v1/acquisition_workers?on_conflict=id", {
            "id": worker_id, "current_job_id": current_job_id, "status": status, "version": version,
            "last_seen_at": datetime.now(tz=UTC).isoformat(),
        }, prefer="resolution=merge-duplicates,return=minimal")

    def worker_status(self, worker_id: str) -> dict[str, object] | None:
        rows = self._request("GET", f"/rest/v1/acquisition_workers?id=eq.{worker_id}&limit=1")
        return rows[0] if rows else None

    def _request(self, method: str, path: str, payload: dict[str, object] | None = None, *, prefer: str | None = None) -> list[dict[str, object]]:
        headers = {"apikey": self.service_key, "Authorization": f"Bearer {self.service_key}"}
        if prefer:
            headers["Prefer"] = prefer
        response = httpx.request(method, f"{self.url}{path}", json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        value = response.json()
        return value if isinstance(value, list) else []

    @staticmethod
    def _job(row: dict[str, object]) -> AcquisitionJob:
        value = dict(row)
        for field in ("lease_expires_at", "heartbeat_at", "created_at", "started_at", "completed_at"):
            raw = value.get(field)
            if isinstance(raw, str):
                value[field] = __import__("datetime").datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        return AcquisitionJob.from_dict(value)

    @staticmethod
    def _payload(job: AcquisitionJob) -> dict[str, object]:
        value = job.to_dict()
        for field in ("lease_expires_at", "heartbeat_at", "created_at", "started_at", "completed_at"):
            raw = value.get(field)
            if isinstance(raw, int | float):
                value[field] = datetime.fromtimestamp(raw, tz=UTC).isoformat()
        return value


def build_acquisition_repository() -> AcquisitionRepository:
    if os.environ.get("DRIPCUT_YOUTUBE_ACQUISITION_MODE", "local").strip().lower() == "worker":
        return SupabaseAcquisitionRepository.from_environment()
    return LocalAcquisitionRepository()
