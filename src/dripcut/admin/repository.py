"""Internal analytics provider contract and deployment selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from dripcut.admin.models import AdminSnapshot


class AdminRepository(Protocol):
    name: str

    def snapshot(self, *, limit: int = 50) -> AdminSnapshot: ...


def build_admin_repository(
    root: Path,
    tenant_provider: str,
    *,
    queue: Any,
) -> AdminRepository:
    if tenant_provider == "supabase":
        from dripcut.admin.supabase import SupabaseAdminRepository

        return SupabaseAdminRepository.from_environment()
    from dripcut.admin.local import LocalAdminRepository

    return LocalAdminRepository(root, queue=queue)
