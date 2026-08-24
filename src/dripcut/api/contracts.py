"""Stable JSON contracts shared by the web client and processing service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    message: str
    hint: str | None = None
    code: str | None = None
    details: object | list[object] | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class SourceAssetResponse(BaseModel):
    id: str
    kind: Literal["upload", "youtube"]
    name: str
    title: str
    duration: float
    width: int
    height: int
    mime_type: str
    size_bytes: int
    channel: str | None = None
    youtube_url: str | None = None
    media_url: str
    poster_url: str | None = None
    project_id: str | None = None
    max_clip_count: int | None = None


class YouTubeImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    rights_confirmed: bool = False


class ClipSegmentRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    index: int = Field(ge=1, le=1000)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    strategy: Literal["standard", "ai"] = "standard"


class StandardPlanRequest(BaseModel):
    duration: float = Field(ge=1, le=3600)
    count: int | Literal["max"] = "max"


class StandardPlanResponse(BaseModel):
    duration: float
    requested_count: int
    max_count: int
    segments: list[ClipSegmentRequest]


class RenderRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    segments: list[ClipSegmentRequest] = Field(min_length=1, max_length=1000)
    container: Literal["mp4", "mov"] = "mp4"
    output_format: Literal["source", "landscape", "portrait", "square"] = "source"
    portrait_mode: Literal["ai_tracking", "center_crop", "blur_background"] = "center_crop"
    auto_captions: bool = False
    platforms: list[Literal["youtube", "instagram"]] = Field(default_factory=list, max_length=2)
    fast_mode: bool = True


class ArtifactResponse(BaseModel):
    id: str
    job_id: str
    kind: Literal["clip", "zip", "thumbnail"]
    name: str
    size_bytes: int
    mime_type: str
    index: int | None = None
    duration: float | None = None
    output_format: str = "source"
    captions_enabled: bool = False
    stream_url: str | None = None
    download_url: str


class JobResponse(BaseModel):
    id: str
    source_id: str
    project_id: str = ""
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: float
    percent: int
    stage: str
    elapsed: float
    error: str | None = None
    error_code: str | None = None
    hint: str | None = None
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    zip_artifact: ArtifactResponse | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ffmpeg: bool
    ffprobe: bool


class YouTubeDiagnosticsResponse(BaseModel):
    yt_dlp_version: str
    ffmpeg_available: bool
    ffprobe_available: bool
    js_runtime: str | None
    js_runtime_version: str | None
    node_available: bool
    ejs_version: str | None
    js_challenge_support_active: bool
    po_token_provider_available: bool
    po_token_provider_configured: bool
    cookie_fallback_configured: bool
    proxy_configured: bool
    strategies: list[str]
    last_successful_strategy: str | None
    last_failure_class: str | None
    last_http_status: int | None
    last_login_required: bool | None
    last_attempted_strategies: list[str]


class ProjectResponse(BaseModel):
    id: str
    title: str
    project_type: str
    source_asset_id: str | None = None
    thumbnail_url: str | None = None
    created_at: float
    updated_at: float
    status: str
    platform: str
    output_format: str
    clip_count: int
    artifact_ids: list[str] = Field(default_factory=list)
    download_artifact_id: str | None = None
    scheduling_status: str
    latest_job_id: str | None = None
    captions_enabled: bool = False
    workflow_route: str = "auto-clip"


class ProjectDetailResponse(ProjectResponse):
    source: SourceAssetResponse | None = None


class ThumbnailRequest(BaseModel):
    prompt: str = Field(default="", max_length=500)
    target: Literal["youtube", "instagram"] = "youtube"


class AIEditPlanRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=3, max_length=1000)


class AIEditActionResponse(BaseModel):
    kind: Literal["trim", "format", "captions"]
    label: str
    value: str | float | bool


class AIEditPlanResponse(BaseModel):
    source_id: str
    summary: str
    actions: list[AIEditActionResponse]
    segments: list[ClipSegmentRequest]
    output_format: Literal["source", "landscape", "portrait", "square"]
    auto_captions: bool


class SocialConnectionResponse(BaseModel):
    platform: Literal["instagram", "youtube"]
    label: str
    connected: bool
    configured: bool
    detail: str
    setup_hint: str


class ScheduleCreateRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    platforms: list[Literal["instagram", "youtube"]] = Field(min_length=1, max_length=2)
    interval_minutes: int = Field(ge=5, le=43200)
    start_at: str = Field(default="now", max_length=40)
    caption: str = Field(default="{clip} #shorts #reels", max_length=2200)


class ScheduledPostResponse(BaseModel):
    platform: Literal["instagram", "youtube"]
    clip_name: str
    publish_at: str
    caption: str
    status: str


class ScheduleResponse(BaseModel):
    id: str
    project_id: str
    archive_name: str
    created_at: float
    posts: list[ScheduledPostResponse]
    publish_ready: bool
