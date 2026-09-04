"""Atomic tenant-scoped local persistence for universal content."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dripcut.content.models import ContentItem, ContentSource, PlatformTarget
from dripcut.tenancy.models import TenantAccessDenied
from dripcut.utils.fs import ensure_dir


def _now() -> str:
    return datetime.now(UTC).isoformat()


class LocalContentRepository:
    name = "local"

    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.database = self.root / "content.json"
        self._lock = threading.RLock()

    def save_source(self, source: ContentSource, *, access_token: str = "") -> ContentSource:
        del access_token
        with self._lock:
            data = self._read()
            existing = data["sources"].get(source.id)
            if existing:
                self._guard_owner(existing, source.workspace_id, "content_source", source.id)
            source.created_at = str(existing.get("created_at")) if existing else source.created_at or _now()
            source.updated_at = _now()
            data["sources"][source.id] = asdict(source)
            self._write(data)
        return source

    def source(self, workspace_id: str, source_id: str, *, access_token: str = "") -> ContentSource:
        del access_token
        row = self._read()["sources"].get(source_id)
        self._guard_owner(row, workspace_id, "content_source", source_id)
        return ContentSource(**row)

    def list_sources(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentSource]:
        del access_token
        rows = [
            ContentSource(**row)
            for row in self._read()["sources"].values()
            if row.get("workspace_id") == workspace_id and row.get("project_id") == project_id
        ]
        return sorted(rows, key=lambda value: value.created_at)

    def save_item(self, item: ContentItem, *, access_token: str = "") -> ContentItem:
        del access_token
        with self._lock:
            data = self._read()
            existing = data["items"].get(item.id)
            if existing:
                self._guard_owner(existing, item.workspace_id, "content_item", item.id)
            if item.source_id:
                source = data["sources"].get(item.source_id)
                self._guard_owner(source, item.workspace_id, "content_source", item.source_id)
                if source.get("project_id") != item.project_id:
                    raise TenantAccessDenied("content_source", item.source_id)
            item.created_at = str(existing.get("created_at")) if existing else item.created_at or _now()
            item.updated_at = _now()
            data["items"][item.id] = asdict(item)
            self._write(data)
        return item

    def item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> ContentItem:
        del access_token
        row = self._read()["items"].get(item_id)
        self._guard_owner(row, workspace_id, "content_item", item_id)
        return ContentItem(**row)

    def list_items(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentItem]:
        del access_token
        rows = [
            ContentItem(**row)
            for row in self._read()["items"].values()
            if row.get("workspace_id") == workspace_id and row.get("project_id") == project_id
        ]
        return sorted(rows, key=lambda value: value.created_at)

    def delete_item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            self._guard_owner(data["items"].get(item_id), workspace_id, "content_item", item_id)
            data["items"].pop(item_id)
            data["targets"] = {
                key: row for key, row in data["targets"].items() if row.get("content_item_id") != item_id
            }
            self._write(data)

    def save_target(self, target: PlatformTarget, *, access_token: str = "") -> PlatformTarget:
        del access_token
        with self._lock:
            data = self._read()
            existing = data["targets"].get(target.id)
            if existing:
                self._guard_owner(existing, target.workspace_id, "platform_target", target.id)
            item = data["items"].get(target.content_item_id)
            self._guard_owner(item, target.workspace_id, "content_item", target.content_item_id)
            target.created_at = str(existing.get("created_at")) if existing else target.created_at or _now()
            target.updated_at = _now()
            data["targets"][target.id] = asdict(target)
            self._write(data)
        return target

    def target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> PlatformTarget:
        del access_token
        row = self._read()["targets"].get(target_id)
        self._guard_owner(row, workspace_id, "platform_target", target_id)
        return PlatformTarget(**row)

    def list_targets(self, workspace_id: str, item_id: str, *, access_token: str = "") -> list[PlatformTarget]:
        del access_token
        item = self._read()["items"].get(item_id)
        self._guard_owner(item, workspace_id, "content_item", item_id)
        rows = [
            PlatformTarget(**row)
            for row in self._read()["targets"].values()
            if row.get("workspace_id") == workspace_id and row.get("content_item_id") == item_id
        ]
        return sorted(rows, key=lambda value: value.created_at)

    def delete_target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            self._guard_owner(data["targets"].get(target_id), workspace_id, "platform_target", target_id)
            data["targets"].pop(target_id)
            self._write(data)

    def delete_project(self, workspace_id: str, project_id: str, *, access_token: str = "") -> None:
        del access_token
        with self._lock:
            data = self._read()
            source_ids = {
                key for key, row in data["sources"].items()
                if row.get("workspace_id") == workspace_id and row.get("project_id") == project_id
            }
            item_ids = {
                key for key, row in data["items"].items()
                if row.get("workspace_id") == workspace_id and row.get("project_id") == project_id
            }
            data["sources"] = {key: row for key, row in data["sources"].items() if key not in source_ids}
            data["items"] = {key: row for key, row in data["items"].items() if key not in item_ids}
            data["targets"] = {
                key: row for key, row in data["targets"].items()
                if row.get("content_item_id") not in item_ids
            }
            self._write(data)

    @staticmethod
    def _guard_owner(row: dict[str, Any] | None, workspace_id: str, kind: str, resource_id: str) -> None:
        if not row or row.get("workspace_id") != workspace_id:
            raise TenantAccessDenied(kind, resource_id)

    def _read(self) -> dict[str, dict[str, Any]]:
        empty: dict[str, dict[str, Any]] = {"sources": {}, "items": {}, "targets": {}}
        if not self.database.exists():
            return empty
        try:
            data = json.loads(self.database.read_text(encoding="utf-8"))
            for key in empty:
                data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError, TypeError):
            return empty

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        temporary = self.database.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(self.database)
