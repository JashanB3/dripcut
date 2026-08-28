"""Provider-neutral values exposed by the internal admin API."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AdminUser:
    id: str
    email: str
    name: str
    workspace_id: str = ""
    role: str = "user"
    created_at: str = ""
    last_active_at: str = ""


@dataclass(frozen=True, slots=True)
class AdminJob:
    id: str
    title: str
    status: str
    stage: str = ""
    project_id: str = ""
    error_code: str = ""
    error_message: str = ""
    created_at: str = ""
    elapsed_seconds: float = 0


@dataclass(frozen=True, slots=True)
class AdminUsage:
    metric: str
    quantity: float
    unit: str


@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    metrics: dict[str, float | int]
    users: list[AdminUser] = field(default_factory=list)
    jobs: list[AdminJob] = field(default_factory=list)
    errors: list[AdminJob] = field(default_factory=list)
    usage: list[AdminUsage] = field(default_factory=list)
    generated_at: str = ""
