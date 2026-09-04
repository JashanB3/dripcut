"""AI-assisted script workflows backed by the universal content domain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dripcut.content.models import (
    ContentItem,
    ContentItemStatus,
    ContentSource,
    ContentSourceStatus,
    ContentSourceType,
    ContentType,
)
from dripcut.content.service import ContentService
from dripcut.core.errors import ValidationError
from dripcut.engines.ai.provider import (
    AIProvider,
    AlternateHooks,
    ScriptBrief,
    ScriptDraft,
    ScriptRewriteAction,
)
from dripcut.tenancy.models import Principal


@dataclass(frozen=True, slots=True)
class ScriptWorkspace:
    source: ContentSource
    item: ContentItem
    alternate_hooks: tuple[str, ...] = ()


class ScriptStudioService:
    """Create and revise scripts without introducing a parallel persistence model."""

    def __init__(self, content: ContentService, provider: AIProvider) -> None:
        self.content = content
        self.provider = provider

    def create_manual(
        self,
        principal: Principal,
        project_id: str,
        *,
        title: str,
        script: str,
        platform: str,
        language: str,
        target_duration_seconds: int,
    ) -> ScriptWorkspace:
        clean_script = script.strip()
        if not clean_script:
            raise ValidationError("Write or paste a script before saving.")
        source = self.content.create_source(
            principal,
            project_id,
            source_type=ContentSourceType.SCRIPT,
            title=title,
            text_content=clean_script,
            metadata={
                "origin": "manual",
                "platform": platform,
                "language": language,
                "target_duration_seconds": target_duration_seconds,
            },
            status=ContentSourceStatus.READY,
        )
        item = self.content.create_item(
            principal,
            project_id,
            source_id=source.id,
            content_type=ContentType.SCRIPT,
            title=title,
            script=clean_script,
            duration_seconds=target_duration_seconds,
            language=language,
            status=ContentItemStatus.DRAFT,
            metadata={"origin": "manual", "intended_platform": platform},
        )
        return ScriptWorkspace(source=source, item=item)

    def generate(
        self,
        principal: Principal,
        project_id: str,
        brief: ScriptBrief,
    ) -> ScriptWorkspace:
        draft = self.provider.generate_script(brief)
        source = self.content.create_source(
            principal,
            project_id,
            source_type=ContentSourceType.AI_SCRIPT,
            title=draft.title,
            text_content=draft.script,
            metadata=self._provenance(brief, action="generate"),
            status=ContentSourceStatus.READY,
        )
        item = self.content.create_item(
            principal,
            project_id,
            source_id=source.id,
            content_type=ContentType.AI_SCRIPT,
            **self._draft_values(draft, action="generate"),
        )
        return ScriptWorkspace(source=source, item=item)

    def rewrite(
        self,
        principal: Principal,
        item_id: str,
        *,
        action: ScriptRewriteAction,
        brief: ScriptBrief,
    ) -> ScriptWorkspace:
        item = self.content.item(principal, item_id)
        draft = self.provider.rewrite_script(
            self._required_script(item),
            action=action,
            brief=brief,
        )
        return ScriptWorkspace(
            source=self._source_for_item(principal, item),
            item=self._update_from_draft(principal, item, draft, action=action),
        )

    def adapt(
        self,
        principal: Principal,
        item_id: str,
        *,
        platform: str,
        brief: ScriptBrief,
    ) -> ScriptWorkspace:
        item = self.content.item(principal, item_id)
        if platform not in {"youtube", "instagram"}:
            raise ValidationError("Choose YouTube Shorts or Instagram Reels.")
        draft = self.provider.adapt_script_for_platform(
            self._required_script(item),
            platform=platform,  # type: ignore[arg-type]
            brief=brief,
        )
        return ScriptWorkspace(
            source=self._source_for_item(principal, item),
            item=self._update_from_draft(
                principal,
                item,
                draft,
                action=f"adapt_{platform}",
            ),
        )

    def hooks(
        self,
        principal: Principal,
        item_id: str,
        *,
        brief: ScriptBrief,
    ) -> ScriptWorkspace:
        item = self.content.item(principal, item_id)
        result: AlternateHooks = self.provider.generate_hooks(
            self._required_script(item),
            brief=brief,
        )
        metadata = self._updated_metadata(
            item,
            action="generate_hooks",
            extra={"alternate_hooks": result.hooks},
        )
        updated = self.content.update_item(principal, item.id, metadata=metadata)
        return ScriptWorkspace(
            source=self._source_for_item(principal, item),
            item=updated,
            alternate_hooks=tuple(result.hooks),
        )

    def _update_from_draft(
        self,
        principal: Principal,
        item: ContentItem,
        draft: ScriptDraft,
        *,
        action: str,
    ) -> ContentItem:
        values = self._draft_values(draft, action=action, existing=item)
        values.pop("status", None)
        return self.content.update_item(principal, item.id, **values)

    def _draft_values(
        self,
        draft: ScriptDraft,
        *,
        action: str,
        existing: ContentItem | None = None,
    ) -> dict[str, Any]:
        metadata = self._updated_metadata(
            existing,
            action=action,
            extra={
                "intended_platform": draft.platform,
                "sections": [section.model_dump() for section in draft.sections],
                "cta": draft.cta,
                "provider": self.provider.name,
                "model": self.provider.model,
            },
        )
        return {
            "title": draft.title,
            "script": draft.script,
            "hook": draft.hook,
            "body": "\n\n".join(section.text for section in draft.sections),
            "description": draft.description or None,
            "caption": draft.caption or None,
            "hashtags": draft.hashtags,
            "duration_seconds": draft.estimated_duration_seconds,
            "language": draft.language,
            "status": ContentItemStatus.REVIEW,
            "metadata": metadata,
        }

    def _provenance(self, brief: ScriptBrief, *, action: str) -> dict[str, Any]:
        values = brief.model_dump(exclude={"reference_text"})
        return {
            "origin": "ai",
            "action": action,
            "provider": self.provider.name,
            "model": self.provider.model,
            "brief": values,
            "reference_text_supplied": bool(brief.reference_text.strip()),
            "reference_text_characters": len(brief.reference_text),
        }

    @staticmethod
    def _required_script(item: ContentItem) -> str:
        if not item.script or not item.script.strip():
            raise ValidationError("Save a script before using an AI action.")
        return item.script

    def _source_for_item(self, principal: Principal, item: ContentItem) -> ContentSource:
        if not item.source_id:
            raise ValidationError("This script is missing its source record.")
        return self.content.source(principal, item.source_id)

    @staticmethod
    def _updated_metadata(
        item: ContentItem | None,
        *,
        action: str,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = dict(item.metadata) if item else {}
        history = list(metadata.get("ai_action_history") or [])[-19:]
        history.append(action)
        metadata.update(extra)
        metadata["ai_action_history"] = history
        return metadata
