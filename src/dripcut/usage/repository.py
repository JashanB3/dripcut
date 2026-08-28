"""Usage repository contract and deployment provider selection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from dripcut.tenancy.models import Principal
from dripcut.usage.models import UsageMetric, UsagePeriod, UsageReservation, UsageTotals


class UsageRepository(Protocol):
    name: str

    def current_plan(self, principal: Principal) -> str: ...

    def reserve(
        self,
        principal: Principal,
        metric: UsageMetric,
        quantity: float,
        *,
        limit: float | None,
        unit: str,
        period: UsagePeriod,
        project_id: str | None = None,
    ) -> UsageReservation: ...

    def commit(
        self,
        principal: Principal,
        reservation_id: str,
        *,
        actual_quantity: float | None = None,
    ) -> None: ...

    def release(self, principal: Principal, reservation_id: str) -> None: ...

    def totals(
        self, principal: Principal, period: UsagePeriod
    ) -> dict[UsageMetric, UsageTotals]: ...


def build_usage_repository(root: Path, tenant_provider_name: str) -> UsageRepository:
    configured = os.environ.get("DRIPCUT_USAGE_PROVIDER", "").strip().lower()
    provider = configured or tenant_provider_name
    if provider == "supabase":
        from dripcut.usage.supabase import SupabaseUsageRepository

        return SupabaseUsageRepository.from_environment()
    if provider != "local":
        raise RuntimeError(f"Unsupported DRIPCUT_USAGE_PROVIDER: {provider}")
    from dripcut.usage.local import LocalUsageRepository

    return LocalUsageRepository(root / "usage")
