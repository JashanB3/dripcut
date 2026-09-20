"""Security regression tests for cross-workspace API access."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from dripcut.api.app import build_service, create_app
from dripcut.auth.local import LocalAuthProvider
from dripcut.auth.models import AuthUser
from dripcut.tenancy.local import LocalTenantRepository
from dripcut.tenancy.models import Principal


def _signup(client: TestClient, name: str, email: str) -> None:
    response = client.post(
        "/api/auth/signup",
        json={"name": name, "email": email, "password": "correct-horse"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["authenticated"] is True


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("render did not finish")


def test_local_auth_lifecycle(container) -> None:
    service = build_service(container)
    state_root = container.paths.projects / "web-auth-lifecycle-test"
    app = create_app(
        service,
        auth_provider=LocalAuthProvider(state_root / "auth"),
        tenant_repository=LocalTenantRepository(state_root / "tenancy"),
        require_auth=True,
    )

    with TestClient(app) as client:
        assert client.get("/api/auth/session").json()["authenticated"] is False
        _signup(client, "Lifecycle User", "lifecycle@example.test")
        session = client.get("/api/auth/session")
        assert session.status_code == 200
        assert session.json()["user"]["email"] == "lifecycle@example.test"
        refreshed = client.post("/api/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["authenticated"] is True

        assert client.post("/api/auth/logout").status_code == 204
        assert client.get("/api/auth/session").json()["authenticated"] is False
        assert client.post(
            "/api/auth/login",
            json={"email": "lifecycle@example.test", "password": "wrong-password"},
        ).status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"email": "lifecycle@example.test", "password": "correct-horse"},
        )
        assert login.status_code == 200
        recovery = client.post(
            "/api/auth/forgot-password",
            json={"email": "lifecycle@example.test"},
        )
        assert recovery.status_code == 200
        assert "If an account exists" in recovery.json()["message"]

        reset = client.post(
            "/api/auth/reset-password",
            json={"password": "updated-horse"},
        )
        assert reset.status_code == 200
        assert reset.json()["authenticated"] is True
        assert client.post("/api/auth/logout").status_code == 204
        assert client.post(
            "/api/auth/login",
            json={"email": "lifecycle@example.test", "password": "correct-horse"},
        ).status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"email": "lifecycle@example.test", "password": "updated-horse"},
        ).status_code == 200


def test_repeated_authenticated_requests_reuse_a_short_lived_principal(container) -> None:
    class CountingAuth:
        name = "local"

        def __init__(self, delegate: LocalAuthProvider) -> None:
            self.delegate = delegate
            self.get_user_calls = 0

        def get_user(self, access_token: str) -> AuthUser:
            self.get_user_calls += 1
            return self.delegate.get_user(access_token)

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

    class CountingTenants:
        name = "local"

        def __init__(self, delegate: LocalTenantRepository) -> None:
            self.delegate = delegate
            self.principal_calls = 0

        def principal_for(self, user: AuthUser, access_token: str) -> Principal:
            self.principal_calls += 1
            return self.delegate.principal_for(user, access_token)

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

    state_root = container.paths.projects / "principal-cache-test"
    auth = CountingAuth(LocalAuthProvider(state_root / "auth"))
    tenants = CountingTenants(LocalTenantRepository(state_root / "tenancy"))
    app = create_app(
        build_service(container),
        auth_provider=auth,
        tenant_repository=tenants,
        require_auth=True,
    )

    with TestClient(app) as client:
        _signup(client, "Cache User", "cache@example.test")
        token = client.cookies.get("dripcut_access")
        assert token
        calls_after_signup = tenants.principal_calls

        assert client.get("/api/projects").status_code == 200
        assert client.get("/api/projects").status_code == 200
        assert auth.get_user_calls == 1
        assert tenants.principal_calls == calls_after_signup + 1

        assert client.post("/api/auth/logout").status_code == 204
        rejected = client.get(
            "/api/projects", headers={"Authorization": f"Bearer {token}"}
        )
        # The local stateless provider does not revoke signed tokens, but the
        # request must be revalidated rather than served from the principal cache.
        assert rejected.status_code == 200
        assert auth.get_user_calls == 2
        assert tenants.principal_calls == calls_after_signup + 2


def test_project_ownership_survives_backend_restart(container, sample_video: Path) -> None:
    state_root = container.paths.projects / "web-restart-test"
    auth_root = state_root / "auth"
    tenancy_root = state_root / "tenancy"
    first_app = create_app(
        build_service(container),
        auth_provider=LocalAuthProvider(auth_root),
        tenant_repository=LocalTenantRepository(tenancy_root),
        require_auth=True,
    )

    with TestClient(first_app) as client:
        _signup(client, "Restart User", "restart@example.test")
        with sample_video.open("rb") as source:
            uploaded = client.post(
                "/api/sources/upload",
                files={"video": ("restart.mp4", source, "video/mp4")},
            )
        assert uploaded.status_code == 201, uploaded.text
        project_id = uploaded.json()["project_id"]
        assert [project["id"] for project in client.get("/api/projects").json()] == [
            project_id
        ]

    restarted_app = create_app(
        build_service(container),
        auth_provider=LocalAuthProvider(auth_root),
        tenant_repository=LocalTenantRepository(tenancy_root),
        require_auth=True,
    )
    with TestClient(restarted_app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "restart@example.test", "password": "correct-horse"},
        )
        assert login.status_code == 200
        projects = client.get("/api/projects")
        assert projects.status_code == 200
        assert [project["id"] for project in projects.json()] == [project_id]


def test_source_request_repairs_a_missing_source_tenant_index(container, sample_video: Path) -> None:
    """A completed remote import must remain usable if its source index lags."""
    state_root = container.paths.projects / "source-index-recovery-test"
    tenants = LocalTenantRepository(state_root / "tenancy")
    app = create_app(
        build_service(container),
        auth_provider=LocalAuthProvider(state_root / "auth"),
        tenant_repository=tenants,
        require_auth=True,
    )

    with TestClient(app) as client:
        _signup(client, "Recovery User", "recovery@example.test")
        with sample_video.open("rb") as source:
            uploaded = client.post(
                "/api/sources/upload",
                files={"video": ("recovery.mp4", source, "video/mp4")},
            )
        assert uploaded.status_code == 201, uploaded.text
        source_id = uploaded.json()["id"]

        # Simulate the short interval after a worker reports success but before
        # its durable source index is visible to the web request.
        data = tenants._read()
        del data["resources"][f"source:{source_id}"]
        tenants._write(data)

        recovered = client.get(f"/api/sources/{source_id}")

    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == source_id


def test_cross_workspace_project_and_artifact_access_is_denied(
    container, sample_video: Path
) -> None:
    service = build_service(container)
    state_root = container.paths.projects / "web-security-test"
    app = create_app(
        service,
        auth_provider=LocalAuthProvider(state_root / "auth"),
        tenant_repository=LocalTenantRepository(state_root / "tenancy"),
        require_auth=True,
    )

    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        _signup(client, "User A", "user-a@example.test")
        with sample_video.open("rb") as source:
            uploaded = client.post(
                "/api/sources/upload",
                files={"video": ("private-a.mp4", source, "video/mp4")},
            )
        assert uploaded.status_code == 201, uploaded.text
        source_a = uploaded.json()
        project_a = source_a["project_id"]
        assert project_a in {
            project["id"] for project in client.get("/api/projects").json()
        }
        planned = client.post(
            f"/api/sources/{source_a['id']}/standard-plan",
            json={"duration": 2, "count": 1},
        ).json()
        created = client.post(
            "/api/jobs/clips",
            json={"source_id": source_a["id"], "segments": planned["segments"]},
        )
        assert created.status_code == 202, created.text
        job_a = created.json()["id"]
        finished = _wait(client, job_a)
        assert finished["status"] == "succeeded", finished
        artifact_a = finished["zip_artifact"]["id"]

        assert client.post("/api/auth/logout").status_code == 204
        _signup(client, "User B", "user-b@example.test")

        assert client.get("/api/projects").json() == []
        assert client.get(f"/api/projects/{project_a}").status_code == 404
        assert client.patch(f"/api/projects/{project_a}", json={"title": "Stolen"}).status_code == 404
        assert client.delete(f"/api/projects/{project_a}").status_code == 404
        assert client.get(f"/api/sources/{source_a['id']}").status_code == 404
        assert client.post(
            "/api/jobs/clips",
            json={"source_id": source_a["id"], "segments": planned["segments"]},
        ).status_code == 404
        assert client.post(
            "/api/schedules",
            json={
                "project_id": project_a,
                "platforms": ["youtube"],
                "interval_minutes": 60,
                "start_at": "now",
                "caption": "Private project",
            },
        ).status_code == 404
        assert client.get(f"/api/jobs/{job_a}").status_code == 404
        assert client.get(f"/api/artifacts/{artifact_a}/download").status_code == 404
