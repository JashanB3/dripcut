"""Persistence contract and provider selection for universal content."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from dripcut.content.models import ContentItem, ContentSource, PlatformTarget


class ContentRepository(Protocol):
    name: str

    def save_source(self, source: ContentSource, *, access_token: str = "") -> ContentSource: ...

    def source(self, workspace_id: str, source_id: str, *, access_token: str = "") -> ContentSource: ...

    def list_sources(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentSource]: ...

    def save_item(self, item: ContentItem, *, access_token: str = "") -> ContentItem: ...

    def item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> ContentItem: ...

    def list_items(self, workspace_id: str, project_id: str, *, access_token: str = "") -> list[ContentItem]: ...

    def delete_item(self, workspace_id: str, item_id: str, *, access_token: str = "") -> None: ...

    def save_target(self, target: PlatformTarget, *, access_token: str = "") -> PlatformTarget: ...

    def target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> PlatformTarget: ...

    def list_targets(self, workspace_id: str, item_id: str, *, access_token: str = "") -> list[PlatformTarget]: ...

    def delete_target(self, workspace_id: str, target_id: str, *, access_token: str = "") -> None: ...

    def delete_project(self, workspace_id: str, project_id: str, *, access_token: str = "") -> None: ...


def build_content_repository(root: Path, tenant_provider_name: str) -> ContentRepository:
    configured = os.environ.get("DRIPCUT_CONTENT_STORE", "").strip().lower()
    provider = configured or ("supabase" if tenant_provider_name == "supabase" else "local")
    if provider == "supabase":
        from dripcut.content.supabase import SupabaseContentRepository

        return SupabaseContentRepository.from_environment()
    if provider != "local":
        raise RuntimeError(f"Unsupported DRIPCUT_CONTENT_STORE: {provider}")
    if tenant_provider_name != "local":
        raise RuntimeError("Local content persistence may only be paired with local tenancy.")
    from dripcut.content.local import LocalContentRepository

    return LocalContentRepository(root / "content")
