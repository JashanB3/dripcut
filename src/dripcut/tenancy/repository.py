"""Tenant repository contract and provider selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from dripcut.auth.models import AuthUser
from dripcut.tenancy.models import Principal, ResourceKind


class TenantRepository(Protocol):
    name: str

    def principal_for(self, user: AuthUser, access_token: str) -> Principal: ...

    def register(
        self,
        principal: Principal,
        kind: ResourceKind,
        resource_id: str,
        *,
        project_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None: ...

    def can_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> bool: ...

    def require_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> None: ...

    def project_ids(self, principal: Principal) -> set[str]: ...

    def delete_project(self, principal: Principal, project_id: str) -> None: ...


def build_tenant_repository(root: Path, auth_provider_name: str) -> TenantRepository:
    configured = os.environ.get("DRIPCUT_TENANT_PROVIDER", "").strip().lower()
    provider = configured or ("supabase" if auth_provider_name == "supabase" else "local")
    if provider == "supabase":
        from dripcut.tenancy.supabase import SupabaseTenantRepository

        return SupabaseTenantRepository.from_environment()
    if provider != "local":
        raise RuntimeError(f"Unsupported DRIPCUT_TENANT_PROVIDER: {provider}")
    if auth_provider_name != "local":
        raise RuntimeError("Local tenant persistence may only be paired with local authentication.")
    from dripcut.tenancy.local import LocalTenantRepository

    return LocalTenantRepository(root / "tenancy")
