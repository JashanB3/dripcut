"""Usage entitlement, reservation and API enforcement tests."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
from dripcut.auth.local import LocalAuthProvider
from dripcut.auth.models import AuthUser
from dripcut.tenancy.local import LocalTenantRepository
from dripcut.tenancy.models import Principal
from dripcut.usage.entitlements import DEFAULT_PLAN_LIMITS, EntitlementService
from dripcut.usage.local import LocalUsageRepository
from dripcut.usage.models import QuotaExceeded
from dripcut.usage.service import UsageRequest, UsageService


def _principal() -> Principal:
    return Principal(
        user=AuthUser(id="usage-user", email="usage@example.test", name="Usage User"),
        workspace_id="usage-workspace",
        role="owner",
        access_token="local-token",
    )


def _entitlements(video_minutes: float) -> EntitlementService:
    limits = deepcopy(DEFAULT_PLAN_LIMITS)
    limits["free"]["video_processing_minutes"] = video_minutes
    return EntitlementService(limits)


def test_local_reservations_prevent_concurrent_quota_bypass(tmp_path: Path) -> None:
    service = UsageService(
        LocalUsageRepository(tmp_path / "usage"),
        _entitlements(video_minutes=1),
    )
    principal = _principal()

    def reserve() -> object:
        try:
            return service.reserve_many(
                principal,
                [UsageRequest("video_processing_minutes", 0.75)],
            )
        except QuotaExceeded as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: reserve(), range(2)))

    groups = [result for result in results if not isinstance(result, QuotaExceeded)]
    errors = [result for result in results if isinstance(result, QuotaExceeded)]
    assert len(groups) == 1
    assert len(errors) == 1
    summary = service.summary(principal)
    video = next(
        item
        for item in summary["metrics"]
        if item["key"] == "video_processing_minutes"
    )
    assert video["used"] == 0
    assert video["reserved"] == 0.75

    groups[0].commit()
    video = next(
        item
        for item in service.summary(principal)["metrics"]
        if item["key"] == "video_processing_minutes"
    )
    assert video["used"] == 0.75
    assert video["reserved"] == 0


def test_usage_endpoint_and_render_quota_enforcement(
    container, sample_video: Path
) -> None:
    state_root = container.paths.projects / "web-usage-test"
    usage = UsageService(
        LocalUsageRepository(state_root / "usage"),
        _entitlements(video_minutes=0.05),
    )
    app = create_app(
        build_service(container),
        auth_provider=LocalAuthProvider(state_root / "auth"),
        tenant_repository=LocalTenantRepository(state_root / "tenancy"),
        usage_service=usage,
        require_auth=True,
    )

    with TestClient(app) as client:
        signup = client.post(
            "/api/auth/signup",
            json={
                "name": "Quota User",
                "email": "quota@example.test",
                "password": "correct-horse",
            },
        )
        assert signup.status_code == 201, signup.text
        with sample_video.open("rb") as source_file:
            uploaded = client.post(
                "/api/sources/upload",
                files={"video": ("quota.mp4", source_file, "video/mp4")},
            )
        assert uploaded.status_code == 201, uploaded.text
        source = uploaded.json()

        usage_response = client.get("/api/usage")
        assert usage_response.status_code == 200
        payload = usage_response.json()
        assert payload["plan"] == "free"
        assert payload["reset_at"] == payload["period_end"]
        storage = next(item for item in payload["metrics"] if item["key"] == "storage_bytes")
        assert storage["used"] == sample_video.stat().st_size

        too_large = client.post(
            f"/api/sources/{source['id']}/standard-plan",
            json={"duration": 4, "count": 1},
        ).json()
        rejected = client.post(
            "/api/jobs/clips",
            json={"source_id": source["id"], "segments": too_large["segments"]},
        )
        assert rejected.status_code == 429
        assert rejected.json()["error"]["code"] == "QUOTA_EXCEEDED"

        accepted_plan = client.post(
            f"/api/sources/{source['id']}/standard-plan",
            json={"duration": 2, "count": 1},
        ).json()
        created = client.post(
            "/api/jobs/clips",
            json={"source_id": source["id"], "segments": accepted_plan["segments"]},
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        deadline = time.monotonic() + 20
        finished = None
        while time.monotonic() < deadline:
            finished = client.get(f"/api/jobs/{job_id}").json()
            if finished["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert finished and finished["status"] == "succeeded", finished

        video = next(
            item
            for item in client.get("/api/usage").json()["metrics"]
            if item["key"] == "video_processing_minutes"
        )
        assert video["used"] == pytest.approx(2 / 60, abs=0.0001)
        assert video["reserved"] == 0
