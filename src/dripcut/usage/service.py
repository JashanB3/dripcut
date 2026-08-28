"""High-level quota checks, reservations and usage summaries."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from dripcut.tenancy.models import Principal
from dripcut.usage.entitlements import EntitlementService
from dripcut.usage.models import (
    METRIC_LABELS,
    METRIC_UNITS,
    UsageMetric,
    UsagePeriod,
    UsageReservation,
)
from dripcut.usage.repository import UsageRepository


def current_usage_period(now: datetime | None = None) -> UsagePeriod:
    value = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return UsagePeriod(start=start, end=end)


@dataclass(frozen=True)
class UsageRequest:
    metric: UsageMetric
    quantity: float


class UsageReservationGroup:
    """Idempotently finalize a set of reservations from a worker callback."""

    def __init__(
        self,
        repository: UsageRepository,
        principal: Principal,
        reservations: list[UsageReservation],
    ) -> None:
        self.repository = repository
        self.principal = principal
        self.reservations = tuple(reservations)
        self._state = "reserved"
        self._lock = threading.Lock()

    def commit(self) -> None:
        with self._lock:
            if self._state != "reserved":
                return
            for reservation in self.reservations:
                self.repository.commit(self.principal, reservation.id)
            self._state = "committed"

    def release(self) -> None:
        with self._lock:
            if self._state != "reserved":
                return
            for reservation in self.reservations:
                self.repository.release(self.principal, reservation.id)
            self._state = "released"


class UsageService:
    def __init__(
        self,
        repository: UsageRepository,
        entitlements: EntitlementService | None = None,
    ) -> None:
        self.repository = repository
        self.entitlements = entitlements or EntitlementService()

    def reserve_many(
        self,
        principal: Principal,
        requests: list[UsageRequest],
        *,
        project_id: str | None = None,
    ) -> UsageReservationGroup:
        period = current_usage_period()
        plan = self.repository.current_plan(principal)
        reservations: list[UsageReservation] = []
        try:
            for request in requests:
                if request.quantity <= 0:
                    continue
                reservations.append(
                    self.repository.reserve(
                        principal,
                        request.metric,
                        request.quantity,
                        limit=self.entitlements.limit(plan, request.metric),
                        unit=METRIC_UNITS[request.metric],
                        period=period,
                        project_id=project_id,
                    )
                )
        except Exception:
            for reservation in reservations:
                self.repository.release(principal, reservation.id)
            raise
        return UsageReservationGroup(self.repository, principal, reservations)

    def summary(self, principal: Principal) -> dict[str, object]:
        period = current_usage_period()
        plan = self.repository.current_plan(principal)
        totals = self.repository.totals(principal, period)
        metrics = []
        for metric, label in METRIC_LABELS.items():
            values = totals.get(metric)
            used = values.used if values else 0
            reserved = values.reserved if values else 0
            limit = self.entitlements.limit(plan, metric)
            metrics.append(
                {
                    "key": metric,
                    "label": label,
                    "used": round(used, 4),
                    "reserved": round(reserved, 4),
                    "limit": limit,
                    "unit": METRIC_UNITS[metric],
                    "percent": 0 if limit in (None, 0) else min(100, round((used + reserved) / limit * 100, 2)),
                    "unlimited": limit is None,
                }
            )
        return {
            "plan": plan,
            "plan_label": self.entitlements.plan_label(plan),
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "reset_at": period.end.isoformat(),
            "metrics": metrics,
        }
