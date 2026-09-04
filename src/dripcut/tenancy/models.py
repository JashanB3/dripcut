"""Provider-neutral tenant identity values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dripcut.auth.models import AuthUser

ResourceKind = Literal["project", "source", "job", "artifact"]


@dataclass(frozen=True, slots=True)
class Principal:
    user: AuthUser
    workspace_id: str
    role: Literal["owner", "admin", "member", "user"]
    access_token: str
    is_dripcut_admin: bool = False


class TenantAccessDenied(Exception):
    """Raised when a resource is absent from the caller's authorized workspace."""

    def __init__(self, kind: str, resource_id: str) -> None:
        super().__init__(f"{kind}:{resource_id} is not available")
        self.kind = kind
        self.resource_id = resource_id
