"""Thread-safe local usage accounting for development and tests."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from dripcut.tenancy.models import Principal
from dripcut.usage.models import (
    QuotaExceeded,
    UsageMetric,
    UsagePeriod,
    UsageReservation,
    UsageTotals,
)
from dripcut.utils.fs import ensure_dir


class LocalUsageRepository:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.database = self.root / "usage.json"
        self._lock = threading.RLock()

    def current_plan(self, principal: Principal) -> str:
        with self._lock:
            data = self._read()
            return str(
                data["plans"].get(principal.workspace_id)
                or os.environ.get("DRIPCUT_LOCAL_PLAN", "free")
            ).lower()

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
    ) -> UsageReservation:
        if quantity < 0:
            raise ValueError("Usage reservation quantity cannot be negative.")
        with self._lock:
            data = self._read()
            now = time.time()
            totals = self._totals(data, principal.workspace_id, period, now=now).get(
                metric, UsageTotals()
            )
            consumed = totals.used + totals.reserved
            if limit is not None and consumed + quantity > limit + 1e-9:
                raise QuotaExceeded(
                    metric,
                    used=consumed,
                    requested=quantity,
                    limit=limit,
                )
            reservation_id = str(uuid4())
            data["reservations"][reservation_id] = {
                "id": reservation_id,
                "workspace_id": principal.workspace_id,
                "owner_id": principal.user.id,
                "project_id": project_id,
                "metric": metric,
                "quantity": quantity,
                "unit": unit,
                "status": "reserved",
                "period_start": period.start.timestamp(),
                "period_end": period.end.timestamp(),
                "expires_at": now + 24 * 3600,
                "created_at": now,
            }
            self._write(data)
            return UsageReservation(reservation_id, metric, quantity, unit)

    def commit(
        self,
        principal: Principal,
        reservation_id: str,
        *,
        actual_quantity: float | None = None,
    ) -> None:
        with self._lock:
            data = self._read()
            row = data["reservations"].get(reservation_id)
            if not row or row.get("workspace_id") != principal.workspace_id:
                return
            if row.get("status") != "reserved":
                return
            quantity = float(row["quantity"] if actual_quantity is None else actual_quantity)
            if quantity < 0 or quantity > float(row["quantity"]) + 1e-9:
                raise ValueError("Actual usage must be between zero and the reserved quantity.")
            row["status"] = "committed"
            row["committed_at"] = time.time()
            data["events"].append(
                {
                    "id": str(uuid4()),
                    "workspace_id": principal.workspace_id,
                    "owner_id": principal.user.id,
                    "project_id": row.get("project_id"),
                    "metric": row["metric"],
                    "quantity": quantity,
                    "unit": row["unit"],
                    "reservation_id": reservation_id,
                    "created_at": time.time(),
                }
            )
            self._write(data)

    def release(self, principal: Principal, reservation_id: str) -> None:
        with self._lock:
            data = self._read()
            row = data["reservations"].get(reservation_id)
            if not row or row.get("workspace_id") != principal.workspace_id:
                return
            if row.get("status") == "reserved":
                row["status"] = "released"
                row["released_at"] = time.time()
                self._write(data)

    def totals(
        self, principal: Principal, period: UsagePeriod
    ) -> dict[UsageMetric, UsageTotals]:
        with self._lock:
            return self._totals(
                self._read(), principal.workspace_id, period, now=time.time()
            )

    def _totals(
        self,
        data: dict[str, Any],
        workspace_id: str,
        period: UsagePeriod,
        *,
        now: float,
    ) -> dict[UsageMetric, UsageTotals]:
        start = period.start.replace(tzinfo=timezone.utc).timestamp()
        end = period.end.replace(tzinfo=timezone.utc).timestamp()
        values: dict[UsageMetric, list[float]] = {}
        for event in data["events"]:
            created = float(event.get("created_at", 0))
            if event.get("workspace_id") != workspace_id or not start <= created < end:
                continue
            metric = event["metric"]
            values.setdefault(metric, [0, 0])[0] += float(event.get("quantity", 0))
        for reservation in data["reservations"].values():
            if (
                reservation.get("workspace_id") != workspace_id
                or reservation.get("status") != "reserved"
                or float(reservation.get("expires_at", 0)) <= now
            ):
                continue
            created = float(reservation.get("created_at", 0))
            if not start <= created < end:
                continue
            metric = reservation["metric"]
            values.setdefault(metric, [0, 0])[1] += float(reservation.get("quantity", 0))
        return {
            metric: UsageTotals(used=amounts[0], reserved=amounts[1])
            for metric, amounts in values.items()
        }

    def _read(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"plans": {}, "events": [], "reservations": {}}
        if not self.database.exists():
            return empty
        try:
            data = json.loads(self.database.read_text(encoding="utf-8"))
            for key, value in empty.items():
                data.setdefault(key, value)
            return data
        except (OSError, json.JSONDecodeError, TypeError):
            return empty

    def _write(self, data: dict[str, Any]) -> None:
        temporary = self.database.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.database)
