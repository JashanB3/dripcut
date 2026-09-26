"""Small serialisable model for a worker-owned source acquisition."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AcquisitionStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class AcquisitionJob:
    workspace_id: str
    owner_id: str
    project_id: str
    source_url: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_type: str = "youtube"
    status: AcquisitionStatus = AcquisitionStatus.QUEUED
    attempt_count: int = 0
    max_attempts: int = 2
    lease_owner: str | None = None
    lease_expires_at: float | None = None
    heartbeat_at: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    output_storage_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {AcquisitionStatus.COMPLETED, AcquisitionStatus.FAILED, AcquisitionStatus.CANCELLED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "workspace_id": self.workspace_id, "owner_id": self.owner_id,
            "project_id": self.project_id, "source_url": self.source_url, "source_type": self.source_type,
            "status": self.status.value, "attempt_count": self.attempt_count, "max_attempts": self.max_attempts,
            "lease_owner": self.lease_owner, "lease_expires_at": self.lease_expires_at,
            "heartbeat_at": self.heartbeat_at, "error_code": self.error_code,
            "error_message": self.error_message, "output_storage_key": self.output_storage_key,
            "metadata": self.metadata, "created_at": self.created_at, "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AcquisitionJob:
        payload = dict(value)
        payload["status"] = AcquisitionStatus(payload.get("status", AcquisitionStatus.QUEUED))
        payload["metadata"] = dict(payload.get("metadata") or {})
        return cls(**payload)
