"""Tenant-safe orchestration for provider-neutral content records."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from dripcut.content.models import (
    ContentItem,
    ContentItemStatus,
    ContentSource,
    ContentSourceStatus,
    ContentSourceType,
    ContentType,
    PlatformTarget,
    TargetPlatform,
    new_id,
)
from dripcut.content.repository import ContentRepository
from dripcut.core.errors import ValidationError
from dripcut.social.store import SocialStore
from dripcut.tenancy.models import Principal, TenantAccessDenied
from dripcut.tenancy.repository import TenantRepository

MAX_METADATA_BYTES = 16 * 1024
MAX_TEXT_LENGTH = 100_000


class ContentService:
    """Maintain content relationships without owning rendering or publishing."""

    def __init__(
        self,
        repository: ContentRepository,
        tenants: TenantRepository,
        *,
        social_store: SocialStore | None = None,
        source_project_id: Callable[[str], str | None] | None = None,
        artifact_project_id: Callable[[str], str | None] | None = None,
    ) -> None:
        self.repository = repository
        self.tenants = tenants
        self.social_store = social_store
        self.source_project_id = source_project_id
        self.artifact_project_id = artifact_project_id

    def create_source(
        self,
        principal: Principal,
        project_id: str,
        *,
        source_type: ContentSourceType,
        title: str,
        text_content: str | None = None,
        source_asset_id: str | None = None,
        external_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: ContentSourceStatus = ContentSourceStatus.DRAFT,
        rights_confirmed: bool = False,
        source_id: str | None = None,
    ) -> ContentSource:
        self.tenants.require_access(principal, "project", project_id)
        clean_title = _required_text(title, "Content source title", 180)
        clean_text = _optional_text(text_content, "Source text", MAX_TEXT_LENGTH)
        clean_url = _optional_text(external_url, "External URL", 2048)
        clean_metadata = validate_metadata(metadata or {})
        if source_asset_id:
            self.tenants.require_access(principal, "source", source_asset_id)
            self._require_project_match(
                source_asset_id,
                project_id,
                self.source_project_id,
                "source video",
            )
        if source_type is ContentSourceType.VIDEO_UPLOAD and not source_asset_id:
            raise ValidationError("A video upload source must reference an imported video.")
        if source_type is ContentSourceType.YOUTUBE_URL and not (clean_url or source_asset_id):
            raise ValidationError("A YouTube source requires a URL or imported video.")
        if source_type in {
            ContentSourceType.SCRIPT,
            ContentSourceType.AI_SCRIPT,
            ContentSourceType.AI_PROMPT,
        } and not clean_text:
            raise ValidationError("This content source requires text.")
        source = ContentSource(
            id=source_id or new_id(),
            workspace_id=principal.workspace_id,
            owner_id=principal.user.id,
            project_id=project_id,
            source_type=source_type,
            title=clean_title,
            text_content=clean_text,
            source_asset_id=source_asset_id,
            external_url=clean_url,
            metadata=clean_metadata,
            status=status,
            rights_confirmed=rights_confirmed,
        )
        return self.repository.save_source(source, access_token=principal.access_token)

    def ensure_media_source(
        self,
        principal: Principal,
        *,
        project_id: str,
        source_asset_id: str,
        kind: str,
        title: str,
        external_url: str | None = None,
    ) -> ContentSource:
        try:
            return self.repository.source(
                principal.workspace_id, source_asset_id, access_token=principal.access_token
            )
        except TenantAccessDenied:
            return self.create_source(
                principal,
                project_id,
                source_type=(
                    ContentSourceType.YOUTUBE_URL
                    if kind == "youtube"
                    else ContentSourceType.VIDEO_UPLOAD
                ),
                title=title,
                source_asset_id=source_asset_id,
                external_url=external_url,
                metadata={"compatibility": "source_assets"},
                status=ContentSourceStatus.READY,
                rights_confirmed=kind != "youtube",
                source_id=source_asset_id,
            )

    def source(self, principal: Principal, source_id: str) -> ContentSource:
        return self.repository.source(
            principal.workspace_id, source_id, access_token=principal.access_token
        )

    def create_item(
        self,
        principal: Principal,
        project_id: str,
        *,
        content_type: ContentType,
        title: str,
        source_id: str | None = None,
        script: str | None = None,
        hook: str | None = None,
        body: str | None = None,
        description: str | None = None,
        caption: str | None = None,
        hashtags: list[str] | None = None,
        thumbnail_artifact_id: str | None = None,
        video_artifact_id: str | None = None,
        audio_artifact_id: str | None = None,
        duration_seconds: float | None = None,
        aspect_ratio: str | None = None,
        language: str | None = None,
        status: ContentItemStatus = ContentItemStatus.DRAFT,
        metadata: dict[str, Any] | None = None,
        item_id: str | None = None,
    ) -> ContentItem:
        self.tenants.require_access(principal, "project", project_id)
        if source_id:
            source = self.source(principal, source_id)
            if source.project_id != project_id:
                raise TenantAccessDenied("content_source", source_id)
        for artifact_id in (
            thumbnail_artifact_id,
            video_artifact_id,
            audio_artifact_id,
        ):
            if artifact_id:
                self._require_artifact(principal, project_id, artifact_id)
        item = ContentItem(
            id=item_id or new_id(),
            workspace_id=principal.workspace_id,
            owner_id=principal.user.id,
            project_id=project_id,
            source_id=source_id,
            content_type=content_type,
            title=_required_text(title, "Content title", 180),
            script=_optional_text(script, "Script", MAX_TEXT_LENGTH),
            hook=_optional_text(hook, "Hook", 2000),
            body=_optional_text(body, "Content body", MAX_TEXT_LENGTH),
            description=_optional_text(description, "Description", 10_000),
            caption=_optional_text(caption, "Caption", 10_000),
            hashtags=_clean_hashtags(hashtags or []),
            thumbnail_artifact_id=thumbnail_artifact_id,
            video_artifact_id=video_artifact_id,
            audio_artifact_id=audio_artifact_id,
            duration_seconds=duration_seconds,
            aspect_ratio=_optional_text(aspect_ratio, "Aspect ratio", 20),
            language=_optional_text(language, "Language", 40),
            status=status,
            metadata=validate_metadata(metadata or {}),
        )
        return self.repository.save_item(item, access_token=principal.access_token)

    def ensure_rendered_clip(
        self,
        principal: Principal,
        *,
        project_id: str,
        source_id: str | None,
        artifact_id: str,
        title: str,
        duration_seconds: float | None,
        output_format: str,
        captions_enabled: bool,
        job_id: str,
        index: int | None,
    ) -> ContentItem:
        try:
            return self.item(principal, artifact_id)
        except TenantAccessDenied:
            aspect_ratio = {
                "portrait": "9:16",
                "square": "1:1",
                "landscape": "16:9",
            }.get(output_format)
            return self.create_item(
                principal,
                project_id,
                item_id=artifact_id,
                source_id=source_id,
                content_type=ContentType.VIDEO_CLIP,
                title=title,
                video_artifact_id=artifact_id,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                status=ContentItemStatus.READY,
                metadata={
                    "compatibility": "artifacts",
                    "job_id": job_id,
                    "clip_index": index,
                    "captions_enabled": captions_enabled,
                },
            )

    def list_project_content(self, principal: Principal, project_id: str) -> list[ContentItem]:
        self.tenants.require_access(principal, "project", project_id)
        return self.repository.list_items(
            principal.workspace_id, project_id, access_token=principal.access_token
        )

    def item(self, principal: Principal, item_id: str) -> ContentItem:
        return self.repository.item(
            principal.workspace_id, item_id, access_token=principal.access_token
        )

    def update_item(self, principal: Principal, item_id: str, **updates: Any) -> ContentItem:
        item = self.item(principal, item_id)
        allowed = {
            "title",
            "script",
            "hook",
            "body",
            "description",
            "caption",
            "hashtags",
            "duration_seconds",
            "aspect_ratio",
            "language",
            "status",
            "metadata",
        }
        unexpected = set(updates) - allowed
        if unexpected:
            raise ValidationError("Protected content fields cannot be changed.")
        clean = dict(updates)
        if "title" in clean:
            clean["title"] = _required_text(clean["title"], "Content title", 180)
        for field_name, limit in {
            "script": MAX_TEXT_LENGTH,
            "hook": 2000,
            "body": MAX_TEXT_LENGTH,
            "description": 10_000,
            "caption": 10_000,
            "aspect_ratio": 20,
            "language": 40,
        }.items():
            if field_name in clean:
                clean[field_name] = _optional_text(
                    clean[field_name], field_name.replace("_", " ").title(), limit
                )
        if "hashtags" in clean:
            clean["hashtags"] = _clean_hashtags(clean["hashtags"] or [])
        if "metadata" in clean:
            clean["metadata"] = validate_metadata(clean["metadata"] or {})
        updated = replace(item, **clean)
        return self.repository.save_item(updated, access_token=principal.access_token)

    def delete_item(self, principal: Principal, item_id: str) -> None:
        item = self.item(principal, item_id)
        self._require_delete_permission(principal, item.owner_id, "content_item", item_id)
        self.repository.delete_item(
            principal.workspace_id, item_id, access_token=principal.access_token
        )

    def create_target(
        self,
        principal: Principal,
        item_id: str,
        *,
        platform: TargetPlatform,
        social_connection_id: str | None = None,
        scheduled_at: str | None = None,
        source_timezone: str | None = None,
        provider_metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PlatformTarget:
        self.item(principal, item_id)
        self._validate_connection(principal, platform, social_connection_id)
        target = PlatformTarget(
            workspace_id=principal.workspace_id,
            owner_id=principal.user.id,
            content_item_id=item_id,
            platform=platform,
            social_connection_id=social_connection_id,
            scheduled_at=_optional_text(scheduled_at, "Schedule time", 80),
            source_timezone=_optional_text(source_timezone, "Source timezone", 80),
            provider_metadata=validate_metadata(provider_metadata or {}),
            idempotency_key=_optional_text(idempotency_key, "Idempotency key", 200),
        )
        return self.repository.save_target(target, access_token=principal.access_token)

    def list_targets(self, principal: Principal, item_id: str) -> list[PlatformTarget]:
        self.item(principal, item_id)
        return self.repository.list_targets(
            principal.workspace_id, item_id, access_token=principal.access_token
        )

    def update_target(self, principal: Principal, item_id: str, target_id: str, **updates: Any) -> PlatformTarget:
        self.item(principal, item_id)
        target = self.repository.target(
            principal.workspace_id, target_id, access_token=principal.access_token
        )
        if target.content_item_id != item_id:
            raise TenantAccessDenied("platform_target", target_id)
        allowed = {
            "social_connection_id",
            "scheduled_at",
            "source_timezone",
            "publish_status",
            "provider_metadata",
        }
        if set(updates) - allowed:
            raise ValidationError("Protected platform target fields cannot be changed.")
        clean = dict(updates)
        connection_id = clean.get("social_connection_id", target.social_connection_id)
        self._validate_connection(principal, target.platform, connection_id)
        if "provider_metadata" in clean:
            clean["provider_metadata"] = validate_metadata(clean["provider_metadata"] or {})
        for field_name, label in {
            "social_connection_id": "Social connection",
            "scheduled_at": "Schedule time",
            "source_timezone": "Source timezone",
        }.items():
            if field_name in clean:
                clean[field_name] = _optional_text(clean[field_name], label, 200)
        updated = replace(target, **clean)
        return self.repository.save_target(updated, access_token=principal.access_token)

    def delete_target(self, principal: Principal, item_id: str, target_id: str) -> None:
        target = self.repository.target(
            principal.workspace_id, target_id, access_token=principal.access_token
        )
        if target.content_item_id != item_id:
            raise TenantAccessDenied("platform_target", target_id)
        self._require_delete_permission(
            principal, target.owner_id, "platform_target", target_id
        )
        self.repository.delete_target(
            principal.workspace_id, target_id, access_token=principal.access_token
        )

    def delete_project(self, principal: Principal, project_id: str) -> None:
        self.tenants.require_access(principal, "project", project_id)
        self.repository.delete_project(
            principal.workspace_id, project_id, access_token=principal.access_token
        )

    def _require_artifact(self, principal: Principal, project_id: str, artifact_id: str) -> None:
        self.tenants.require_access(principal, "artifact", artifact_id)
        self._require_project_match(
            artifact_id,
            project_id,
            self.artifact_project_id,
            "artifact",
        )

    @staticmethod
    def _require_project_match(
        resource_id: str,
        project_id: str,
        resolver: Callable[[str], str | None] | None,
        label: str,
    ) -> None:
        if resolver is not None and resolver(resource_id) != project_id:
            raise ValidationError(f"That {label} does not belong to this project.")

    def _validate_connection(
        self,
        principal: Principal,
        platform: TargetPlatform,
        social_connection_id: str | None,
    ) -> None:
        if not social_connection_id:
            return
        if platform.value not in {"youtube", "instagram"} or self.social_store is None:
            raise ValidationError("That platform does not have a supported social connection yet.")
        account = self.social_store.account(
            principal.workspace_id,
            platform.value,  # type: ignore[arg-type]
            access_token=principal.access_token,
        )
        if account is None or account.id != social_connection_id:
            raise TenantAccessDenied("platform_target", social_connection_id)

    @staticmethod
    def _require_delete_permission(
        principal: Principal,
        owner_id: str,
        kind: str,
        resource_id: str,
    ) -> None:
        if owner_id != principal.user.id and principal.role not in {"owner", "admin"}:
            raise TenantAccessDenied(kind, resource_id)


def validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValidationError("Metadata must be a JSON object.")
    _validate_json_value(metadata, depth=0)
    try:
        encoded = json.dumps(metadata, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as error:
        raise ValidationError("Metadata must contain only JSON values.") from error
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValidationError("Metadata is too large.", hint="Keep metadata below 16 KB.")
    return metadata


def _validate_json_value(value: Any, *, depth: int) -> None:
    if depth > 5:
        raise ValidationError("Metadata is nested too deeply.")
    if value is None or isinstance(value, str | int | float | bool):
        if isinstance(value, str) and len(value) > 2000:
            raise ValidationError("A metadata value is too long.")
        return
    if isinstance(value, list):
        if len(value) > 100:
            raise ValidationError("A metadata list has too many entries.")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValidationError("Metadata has too many fields.")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 100:
                raise ValidationError("Metadata keys must be short strings.")
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValidationError("Metadata must contain only JSON values.")


def _required_text(value: Any, label: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{label} is required.")
    if len(text) > limit:
        raise ValidationError(f"{label} is too long.")
    return text


def _optional_text(value: Any, label: str, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) > limit:
        raise ValidationError(f"{label} is too long.")
    return text or None


def _clean_hashtags(values: list[Any]) -> list[str]:
    if len(values) > 50:
        raise ValidationError("Use no more than 50 hashtags.")
    cleaned: list[str] = []
    for value in values:
        tag = str(value).strip().lstrip("#")
        if not tag:
            continue
        if len(tag) > 100:
            raise ValidationError("A hashtag is too long.")
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned
