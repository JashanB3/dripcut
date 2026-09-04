"""Universal content values independent of media and publishing providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class ContentSourceType(str, Enum):
    VIDEO_UPLOAD = "video_upload"
    YOUTUBE_URL = "youtube_url"
    SCRIPT = "script"
    AI_SCRIPT = "ai_script"
    AI_PROMPT = "ai_prompt"


class ContentSourceStatus(str, Enum):
    DRAFT = "draft"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


class ContentType(str, Enum):
    VIDEO_CLIP = "video_clip"
    SCRIPT = "script"
    AI_SCRIPT = "ai_script"
    AI_VIDEO = "ai_video"


class ContentItemStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    REVIEW = "review"
    READY = "ready"
    SCHEDULED = "scheduled"
    PARTIALLY_PUBLISHED = "partially_published"
    PUBLISHED = "published"
    FAILED = "failed"
    ARCHIVED = "archived"


class TargetPlatform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"
    BILIBILI = "bilibili"
    LINKEDIN = "linkedin"


class PlatformTargetStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


def new_id() -> str:
    return uuid4().hex


def _content_id(value: str | None) -> str | None:
    """Keep content and legacy media UUIDs stable across PostgREST formatting."""
    if value is None:
        return None
    try:
        return UUID(value).hex
    except ValueError:
        return value


@dataclass(slots=True)
class ContentSource:
    workspace_id: str
    owner_id: str
    project_id: str
    source_type: ContentSourceType
    title: str
    id: str = field(default_factory=new_id)
    text_content: str | None = None
    source_asset_id: str | None = None
    external_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: ContentSourceStatus = ContentSourceStatus.DRAFT
    rights_confirmed: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = _content_id(self.id) or self.id
        self.source_asset_id = _content_id(self.source_asset_id)
        self.source_type = ContentSourceType(self.source_type)
        self.status = ContentSourceStatus(self.status)


@dataclass(slots=True)
class ContentItem:
    workspace_id: str
    owner_id: str
    project_id: str
    content_type: ContentType
    title: str
    id: str = field(default_factory=new_id)
    source_id: str | None = None
    script: str | None = None
    hook: str | None = None
    body: str | None = None
    description: str | None = None
    caption: str | None = None
    hashtags: list[str] = field(default_factory=list)
    thumbnail_artifact_id: str | None = None
    video_artifact_id: str | None = None
    audio_artifact_id: str | None = None
    duration_seconds: float | None = None
    aspect_ratio: str | None = None
    language: str | None = None
    status: ContentItemStatus = ContentItemStatus.DRAFT
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = _content_id(self.id) or self.id
        self.source_id = _content_id(self.source_id)
        self.thumbnail_artifact_id = _content_id(self.thumbnail_artifact_id)
        self.video_artifact_id = _content_id(self.video_artifact_id)
        self.audio_artifact_id = _content_id(self.audio_artifact_id)
        self.content_type = ContentType(self.content_type)
        self.status = ContentItemStatus(self.status)


@dataclass(slots=True)
class PlatformTarget:
    workspace_id: str
    owner_id: str
    content_item_id: str
    platform: TargetPlatform
    id: str = field(default_factory=new_id)
    social_connection_id: str | None = None
    scheduled_at: str | None = None
    source_timezone: str | None = None
    publish_status: PlatformTargetStatus = PlatformTargetStatus.DRAFT
    provider_post_id: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    attempt_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None
    published_at: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = _content_id(self.id) or self.id
        self.content_item_id = _content_id(self.content_item_id) or self.content_item_id
        self.platform = TargetPlatform(self.platform)
        self.publish_status = PlatformTargetStatus(self.publish_status)
