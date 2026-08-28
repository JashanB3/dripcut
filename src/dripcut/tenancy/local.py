"""Atomic JSON tenant repository for local development."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from dripcut.auth.models import AuthUser
from dripcut.tenancy.models import Principal, ResourceKind, TenantAccessDenied
from dripcut.utils.fs import ensure_dir


class LocalTenantRepository:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.database = self.root / "tenants.json"
        self._lock = threading.RLock()

    def principal_for(self, user: AuthUser, access_token: str) -> Principal:
        admin_emails = {
            value.strip().lower()
            for value in os.environ.get("DRIPCUT_ADMIN_EMAILS", "").split(",")
            if value.strip()
        }
        is_dripcut_admin = user.email.strip().lower() in admin_emails
        with self._lock:
            data = self._read()
            membership = data["memberships"].get(user.id)
            if not membership:
                workspace_id = str(uuid4())
                now = time.time()
                data["profiles"][user.id] = {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "created_at": now,
                    "updated_at": now,
                    "is_dripcut_admin": is_dripcut_admin,
                }
                data["workspaces"][workspace_id] = {
                    "id": workspace_id,
                    "name": f"{user.name}'s workspace",
                    "owner_id": user.id,
                    "created_at": now,
                    "updated_at": now,
                }
                membership = {"workspace_id": workspace_id, "role": "owner"}
                data["memberships"][user.id] = membership
                self._write(data)
            else:
                profile = data["profiles"].setdefault(user.id, {})
                profile.update({"id": user.id, "email": user.email, "name": user.name, "updated_at": time.time(), "is_dripcut_admin": is_dripcut_admin})
                self._write(data)
        return Principal(
            user=user,
            workspace_id=str(membership["workspace_id"]),
            role=str(membership["role"]),  # type: ignore[arg-type]
            access_token=access_token,
            is_dripcut_admin=is_dripcut_admin,
        )

    def register(
        self,
        principal: Principal,
        kind: ResourceKind,
        resource_id: str,
        *,
        project_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            data = self._read()
            key = f"{kind}:{resource_id}"
            existing = data["resources"].get(key)
            if existing and existing["workspace_id"] != principal.workspace_id:
                raise TenantAccessDenied(kind, resource_id)
            data["resources"][key] = {
                "kind": kind,
                "id": resource_id,
                "workspace_id": principal.workspace_id,
                "owner_id": principal.user.id,
                "project_id": project_id,
                "attributes": attributes or {},
                "updated_at": time.time(),
                "created_at": existing.get("created_at", time.time()) if existing else time.time(),
            }
            self._write(data)

    def can_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> bool:
        row = self._read()["resources"].get(f"{kind}:{resource_id}")
        return bool(row and row.get("workspace_id") == principal.workspace_id)

    def require_access(self, principal: Principal, kind: ResourceKind, resource_id: str) -> None:
        if not self.can_access(principal, kind, resource_id):
            raise TenantAccessDenied(kind, resource_id)

    def project_ids(self, principal: Principal) -> set[str]:
        return {
            str(row["id"])
            for row in self._read()["resources"].values()
            if row.get("kind") == "project" and row.get("workspace_id") == principal.workspace_id
        }

    def delete_project(self, principal: Principal, project_id: str) -> None:
        self.require_access(principal, "project", project_id)
        with self._lock:
            data = self._read()
            data["resources"] = {
                key: row
                for key, row in data["resources"].items()
                if not (
                    row.get("workspace_id") == principal.workspace_id
                    and (row.get("id") == project_id or row.get("project_id") == project_id)
                )
            }
            self._write(data)

    def _read(self) -> dict[str, Any]:
        empty: dict[str, Any] = {
            "profiles": {},
            "workspaces": {},
            "memberships": {},
            "resources": {},
        }
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
