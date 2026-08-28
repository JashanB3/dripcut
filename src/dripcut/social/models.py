"""Provider-neutral social publishing values."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

PlatformName = Literal["instagram", "youtube"]
PostStatus = Literal["draft", "scheduled", "uploading", "published", "failed"]


@dataclass(frozen=True, slots=True)
class SocialCredentials:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    token_type: str = "Bearer"
    scopes: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SocialCredentials:
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=(
                str(payload["refresh_token"]) if payload.get("refresh_token") else None
            ),
            expires_at=(float(payload["expires_at"]) if payload.get("expires_at") else None),
            token_type=str(payload.get("token_type") or "Bearer"),
            scopes=tuple(str(value) for value in payload.get("scopes", [])),
            extra={str(key): str(value) for key, value in payload.get("extra", {}).items()},
        )


@dataclass(slots=True)
class SocialAccount:
    workspace_id: str
    owner_id: str
    platform: PlatformName
    external_account_id: str
    display_name: str
    encrypted_credentials: str
    status: str = "connected"
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class OAuthResult:
    external_account_id: str
    display_name: str
    credentials: SocialCredentials


@dataclass(frozen=True, slots=True)
class PublishResult:
    external_post_id: str
    url: str | None = None
    credentials: SocialCredentials | None = None


@dataclass(slots=True)
class ScheduledPost:
    platform: PlatformName
    clip_name: str
    publish_at: str
    caption: str
    status: PostStatus = "draft"
    id: str = field(default_factory=lambda: str(uuid4()))
    schedule_id: str = ""
    workspace_id: str = "local"
    owner_id: str = "local"
    project_id: str = "legacy"
    archive: str = ""
    title: str = ""
    external_post_id: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class SocialSchedule:
    id: str
    project_id: str
    archive: str
    archive_name: str
    created_at: float
    posts: list[ScheduledPost]
    workspace_id: str = "local"
    owner_id: str = "local"
