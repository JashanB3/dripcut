"""Supabase-backed atomic quota reservations and usage events."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dripcut.auth.models import AuthProviderError
from dripcut.supabase_http import supabase_ssl_context
from dripcut.tenancy.models import Principal
from dripcut.usage.models import (
    QuotaExceeded,
    UsageMetric,
    UsagePeriod,
    UsageReservation,
    UsageTotals,
)


class SupabaseUsageRepository:
    name = "supabase"

    def __init__(self, url: str, anon_key: str) -> None:
        self.url = url.rstrip("/")
        self.anon_key = anon_key

    @classmethod
    def from_environment(cls) -> SupabaseUsageRepository:
        url = os.environ.get("SUPABASE_URL", "").strip()
        key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
        return cls(url, key)

    def current_plan(self, principal: Principal) -> str:
        query = urlencode(
            {
                "select": "plan",
                "workspace_id": f"eq.{principal.workspace_id}",
                "status": "in.(active,trialing)",
                "limit": "1",
            }
        )
        rows = self._request(
            "GET", f"/rest/v1/subscriptions?{query}", access_token=principal.access_token
        )
        if isinstance(rows, list) and rows:
            return str(rows[0].get("plan") or "free").lower()
        return "free"

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
        payload = {
            "p_workspace_id": principal.workspace_id,
            "p_project_id": project_id,
            "p_metric": metric,
            "p_quantity": quantity,
            "p_unit": unit,
            "p_limit": limit,
            "p_period_start": period.start.isoformat(),
            "p_period_end": period.end.isoformat(),
        }
        try:
            reservation_id = self._request(
                "POST",
                "/rest/v1/rpc/reserve_workspace_usage",
                payload,
                access_token=principal.access_token,
            )
        except AuthProviderError as error:
            if error.code == "P0001" and "QUOTA_EXCEEDED" in error.message:
                used = self.totals(principal, period).get(metric, UsageTotals())
                raise QuotaExceeded(
                    metric,
                    used=used.used + used.reserved,
                    requested=quantity,
                    limit=float(limit or 0),
                ) from error
            raise
        return UsageReservation(str(reservation_id), metric, quantity, unit)

    def commit(
        self,
        principal: Principal,
        reservation_id: str,
        *,
        actual_quantity: float | None = None,
    ) -> None:
        self._request(
            "POST",
            "/rest/v1/rpc/commit_workspace_usage",
            {
                "p_reservation_id": reservation_id,
                "p_actual_quantity": actual_quantity,
            },
            access_token=principal.access_token,
        )

    def release(self, principal: Principal, reservation_id: str) -> None:
        self._request(
            "POST",
            "/rest/v1/rpc/release_workspace_usage",
            {"p_reservation_id": reservation_id},
            access_token=principal.access_token,
        )

    def totals(
        self, principal: Principal, period: UsagePeriod
    ) -> dict[UsageMetric, UsageTotals]:
        filters = {
            "select": "event_type,quantity",
            "workspace_id": f"eq.{principal.workspace_id}",
            "created_at": f"gte.{period.start.isoformat()}",
            "and": f"(created_at.lt.{period.end.isoformat()})",
        }
        events = self._request(
            "GET",
            "/rest/v1/usage_events?" + urlencode(filters),
            access_token=principal.access_token,
        )
        reservations = self._request(
            "GET",
            "/rest/v1/usage_reservations?"
            + urlencode(
                {
                    "select": "metric,quantity",
                    "workspace_id": f"eq.{principal.workspace_id}",
                    "status": "eq.reserved",
                    "expires_at": f"gt.{datetime.now().astimezone().isoformat()}",
                    "created_at": f"gte.{period.start.isoformat()}",
                    "and": f"(created_at.lt.{period.end.isoformat()})",
                }
            ),
            access_token=principal.access_token,
        )
        values: dict[UsageMetric, list[float]] = {}
        for row in events if isinstance(events, list) else []:
            metric = row.get("event_type")
            values.setdefault(metric, [0, 0])[0] += float(row.get("quantity") or 0)
        for row in reservations if isinstance(reservations, list) else []:
            metric = row.get("metric")
            values.setdefault(metric, [0, 0])[1] += float(row.get("quantity") or 0)
        return {
            metric: UsageTotals(used=amounts[0], reserved=amounts[1])
            for metric, amounts in values.items()
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        access_token: str,
    ) -> Any:
        headers = {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        request = Request(f"{self.url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(
                request,
                timeout=20,
                context=supabase_ssl_context(),
            ) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as error:
            try:
                data = json.loads(error.read())
            except (json.JSONDecodeError, OSError):
                data = {}
            raise AuthProviderError(
                str(data.get("message") or "Usage service authorization failed."),
                status_code=error.code,
                code=str(data.get("code") or "SUPABASE_USAGE_ERROR"),
            ) from error
        except URLError as error:
            raise AuthProviderError(
                "Usage service is temporarily unavailable.",
                status_code=503,
                code="USAGE_SERVICE_UNAVAILABLE",
            ) from error
