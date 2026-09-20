"""Stable JSON contracts shared by the web client and processing service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorDetail(BaseModel):
    message: str
    hint: str | None = None
    code: str | None = None
    details: object | list[object] | None = None
    request_id: str | None = None
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AuthSignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class PasswordRecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PasswordResetRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)
    access_token: str | None = Field(default=None, max_length=8192)
    refresh_token: str | None = Field(default=None, max_length=8192)


class OAuthTokenRequest(BaseModel):
    access_token: str = Field(min_length=20, max_length=8192)
    refresh_token: str = Field(min_length=1, max_length=8192)


class AuthUserResponse(BaseModel):
    id: str
    email: str
    name: str
    workspace_id: str | None = None
    role: str | None = None
    is_dripcut_admin: bool = False


class AuthSessionResponse(BaseModel):
    authenticated: bool
    provider: str
    user: AuthUserResponse | None = None
    requires_email_confirmation: bool = False
    message: str | None = None


class PasswordRecoveryResponse(BaseModel):
    message: str


class OAuthAuthorizeResponse(BaseModel):
    authorize_url: str


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
    caption_style: Literal["clean", "dynamic", "minimal", "bold"] = "clean"
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
    retryable: bool = False
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    attempt: int = 0
    max_attempts: int = 1
    idempotent_replay: bool = False
    idempotency_key: str | None = Field(default=None, exclude=True)
    artifacts: list[ArtifactResponse] = Field(default_factory=list)
    zip_artifact: ArtifactResponse | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ffmpeg: bool
    ffprobe: bool


class EncoderStatusResponse(BaseModel):
    codec: str
    encoder: str
    provider: str
    hardware: bool


class PerformanceStageResponse(BaseModel):
    name: str
    count: int
    p50_seconds: float
    p95_seconds: float
    max_seconds: float


class OperationsMetricsResponse(BaseModel):
    completed_jobs: int
    failed_jobs: int
    encoder: EncoderStatusResponse
    stages: list[PerformanceStageResponse]


class AdminUserResponse(BaseModel):
    id: str
    email: str
    name: str
    workspace_id: str = ""
    role: str = "user"
    created_at: str = ""
    last_active_at: str = ""


class AdminJobResponse(BaseModel):
    id: str
    title: str
    status: str
    stage: str = ""
    project_id: str = ""
    error_code: str = ""
    error_message: str = ""
    created_at: str = ""
    elapsed_seconds: float = 0


class AdminUsageResponse(BaseModel):
    metric: str
    quantity: float
    unit: str


class AdminOverviewResponse(BaseModel):
    metrics: dict[str, float | int]
    users: list[AdminUserResponse]
    jobs: list[AdminJobResponse]
    errors: list[AdminJobResponse]
    usage: list[AdminUsageResponse]
    generated_at: str


class UsageMetricResponse(BaseModel):
    key: str
    label: str
    used: float
    reserved: float
    limit: float | None
    unit: str
    percent: float
    unlimited: bool = False


class UsageSummaryResponse(BaseModel):
    plan: str
    plan_label: str
    period_start: str
    period_end: str
    reset_at: str
    metrics: list[UsageMetricResponse]


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


class ProjectUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)


class ThumbnailRequest(BaseModel):
    prompt: str = Field(default="", max_length=500)
    target: Literal["youtube", "instagram"] = "youtube"


class ThumbnailBriefResponse(BaseModel):
    headline: str
    visual_focus: str
    emotion: str
    composition: str
    frame_guidance: str
    avoid: list[str]


class ThumbnailRankResponse(BaseModel):
    artifact_id: str
    score: int
    reason: str


class ThumbnailGenerationResponse(BaseModel):
    candidates: list[ArtifactResponse]
    brief: ThumbnailBriefResponse
    ranking: list[ThumbnailRankResponse]


class AIEditPlanRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=3, max_length=1000)


class AIEditActionResponse(BaseModel):
    kind: Literal["selection", "platform", "trim", "format", "captions", "style", "reframe"]
    label: str
    value: str | float | bool


class AIEditPlanResponse(BaseModel):
    source_id: str
    summary: str
    actions: list[AIEditActionResponse]
    segments: list[ClipSegmentRequest]
    output_format: Literal["source", "landscape", "portrait", "square"]
    auto_captions: bool
    platform: Literal["youtube", "instagram"]
    selection: Literal["standard", "viral"]
    count: int
    duration: float
    caption_style: Literal["clean", "dynamic", "minimal", "bold"]
    reframe: Literal["source", "center", "speaker", "blur_background"]


class ViralMomentRequest(BaseModel):
    platform: Literal["youtube", "instagram"]
    target_length: float = Field(default=45, ge=5, le=180)
    max_clips: int = Field(default=8, ge=1, le=20)


class ViralMomentResponse(BaseModel):
    id: str
    start: float
    end: float
    duration: float
    score: int
    hook_score: int
    retention_score: int
    shareability_score: int
    platform: Literal["youtube", "instagram"]
    reason: str
    hook: str


class ViralMomentAnalysisResponse(BaseModel):
    source_id: str
    platform: Literal["youtube", "instagram"]
    model: str
    analysis_version: str
    segments: list[ViralMomentResponse]


class SocialMetadataRequest(BaseModel):
    artifact_id: str | None = Field(default=None, max_length=64)


class SocialMetadataResponse(BaseModel):
    project_id: str
    artifact_id: str | None = None
    youtube_title: str
    youtube_description: str
    youtube_hashtags: list[str]
    instagram_caption: str
    instagram_hashtags: list[str]
    instagram_cta: str
    hook: str
    category: str
    posting_description: str


class SocialConnectionResponse(BaseModel):
    platform: Literal["instagram", "youtube"]
    label: str
    connected: bool
    configured: bool
    detail: str
    setup_hint: str
    channel_id: str = ""
    avatar_url: str = ""


class SocialOAuthStartResponse(BaseModel):
    platform: Literal["instagram", "youtube"]
    authorization_url: str


class SocialDisconnectResponse(BaseModel):
    platform: Literal["instagram", "youtube"]
    disconnected: bool = True


class ScheduleCreateRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    artifact_id: str | None = Field(default=None, max_length=64)
    artifact_ids: list[str] = Field(default_factory=list, max_length=200)
    platforms: list[Literal["instagram", "youtube"]] = Field(min_length=1, max_length=2)
    interval_minutes: int = Field(default=1440, ge=5, le=43200)
    start_at: str = Field(default="now", max_length=64)
    caption: str = Field(default="{clip} #shorts #reels", max_length=2200)
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    publish_mode: Literal["now", "schedule"] = "schedule"
    privacy: Literal["private", "unlisted", "public"] = "private"
    timezone: str = Field(default="UTC", min_length=1, max_length=100)


class SchedulePostUpdateRequest(BaseModel):
    publish_at: str | None = Field(default=None, max_length=40)
    caption: str | None = Field(default=None, max_length=2200)


class ScheduledPostResponse(BaseModel):
    id: str
    platform: Literal["instagram", "youtube"]
    clip_name: str
    publish_at: str
    caption: str
    title: str = ""
    artifact_id: str = ""
    description: str = ""
    privacy: str = "private"
    timezone: str = "UTC"
    publish_mode: str = "schedule"
    attempt_count: int = 0
    last_error_code: str | None = None
    status: str
    external_post_id: str | None = None
    external_url: str | None = None
    error_message: str | None = None


class ScheduleResponse(BaseModel):
    id: str
    project_id: str
    archive_name: str
    created_at: float
    posts: list[ScheduledPostResponse]
    publish_ready: bool


ContentSourceTypeValue = Literal[
    "video_upload", "youtube_url", "script", "ai_script", "ai_prompt"
]
ContentTypeValue = Literal["video_clip", "script", "ai_script", "ai_video"]
ContentStatusValue = Literal[
    "draft", "generating", "review", "ready", "scheduled",
    "partially_published", "published", "failed", "archived",
]
TargetPlatformValue = Literal[
    "youtube", "instagram", "facebook", "tiktok", "bilibili", "linkedin"
]
TargetStatusValue = Literal[
    "draft", "ready", "scheduled", "queued", "uploading",
    "processing", "published", "failed", "cancelled",
]


class ContentSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: ContentSourceTypeValue
    title: str = Field(min_length=1, max_length=180)
    text_content: str | None = Field(default=None, max_length=100_000)
    source_asset_id: str | None = Field(default=None, max_length=64)
    external_url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: Literal["draft", "importing", "ready", "failed"] = "draft"
    rights_confirmed: bool = False

    @model_validator(mode="after")
    def validate_source_payload(self) -> ContentSourceCreateRequest:
        if self.source_type == "video_upload" and not self.source_asset_id:
            raise ValueError("A video upload source requires source_asset_id.")
        if self.source_type == "youtube_url" and not (
            self.source_asset_id or (self.external_url or "").strip()
        ):
            raise ValueError("A YouTube source requires external_url or source_asset_id.")
        if self.source_type in {"script", "ai_script", "ai_prompt"} and not (
            self.text_content or ""
        ).strip():
            raise ValueError("This source type requires text_content.")
        return self


class ContentSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    owner_id: str
    project_id: str
    source_type: ContentSourceTypeValue
    title: str
    text_content: str | None = None
    source_asset_id: str | None = None
    external_url: str | None = None
    metadata: dict[str, Any]
    status: Literal["draft", "importing", "ready", "failed"]
    rights_confirmed: bool
    created_at: str
    updated_at: str


class ContentItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str | None = Field(default=None, max_length=64)
    content_type: ContentTypeValue
    title: str = Field(min_length=1, max_length=180)
    script: str | None = Field(default=None, max_length=100_000)
    hook: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=100_000)
    description: str | None = Field(default=None, max_length=10_000)
    caption: str | None = Field(default=None, max_length=10_000)
    hashtags: list[str] = Field(default_factory=list, max_length=50)
    thumbnail_artifact_id: str | None = Field(default=None, max_length=64)
    video_artifact_id: str | None = Field(default=None, max_length=64)
    audio_artifact_id: str | None = Field(default=None, max_length=64)
    duration_seconds: float | None = Field(default=None, ge=0)
    aspect_ratio: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=40)
    status: ContentStatusValue = "draft"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentItemUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=180)
    script: str | None = Field(default=None, max_length=100_000)
    hook: str | None = Field(default=None, max_length=2000)
    body: str | None = Field(default=None, max_length=100_000)
    description: str | None = Field(default=None, max_length=10_000)
    caption: str | None = Field(default=None, max_length=10_000)
    hashtags: list[str] | None = Field(default=None, max_length=50)
    duration_seconds: float | None = Field(default=None, ge=0)
    aspect_ratio: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=40)
    status: ContentStatusValue | None = None
    metadata: dict[str, Any] | None = None


class ContentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    owner_id: str
    project_id: str
    source_id: str | None = None
    content_type: ContentTypeValue
    title: str
    script: str | None = None
    hook: str | None = None
    body: str | None = None
    description: str | None = None
    caption: str | None = None
    hashtags: list[str]
    thumbnail_artifact_id: str | None = None
    video_artifact_id: str | None = None
    audio_artifact_id: str | None = None
    duration_seconds: float | None = None
    aspect_ratio: str | None = None
    language: str | None = None
    status: ContentStatusValue
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class PlatformTargetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: TargetPlatformValue
    social_connection_id: str | None = Field(default=None, max_length=64)
    scheduled_at: str | None = Field(default=None, max_length=80)
    source_timezone: str | None = Field(default=None, max_length=80)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=200)


class PlatformTargetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    social_connection_id: str | None = Field(default=None, max_length=64)
    scheduled_at: str | None = Field(default=None, max_length=80)
    source_timezone: str | None = Field(default=None, max_length=80)
    publish_status: TargetStatusValue | None = None
    provider_metadata: dict[str, Any] | None = None


class PlatformTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    owner_id: str
    content_item_id: str
    platform: TargetPlatformValue
    social_connection_id: str | None = None
    scheduled_at: str | None = None
    source_timezone: str | None = None
    publish_status: TargetStatusValue
    provider_post_id: str | None = None
    provider_metadata: dict[str, Any]
    idempotency_key: str | None = None
    attempt_count: int
    last_error_code: str | None = None
    last_error_message: str | None = None
    published_at: str | None = None
    created_at: str
    updated_at: str


ScriptActionValue = Literal[
    "rewrite_hook",
    "generate_hooks",
    "shorten",
    "expand",
    "conversational",
    "educational",
    "engaging",
    "rewrite_cta",
    "adapt_youtube",
    "adapt_instagram",
]


class ScriptBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=2, max_length=500)
    platform: Literal["youtube", "instagram"]
    audience: str = Field(min_length=1, max_length=240)
    tone: str = Field(min_length=1, max_length=100)
    language: str = Field(min_length=2, max_length=40)
    target_duration_seconds: int = Field(ge=10, le=600)
    content_goal: str = Field(min_length=1, max_length=300)
    cta: str = Field(default="", max_length=300)
    reference_text: str = Field(default="", max_length=20_000)


class ScriptGenerateRequest(ScriptBriefRequest):
    project_id: str | None = Field(default=None, max_length=64)


class ManualScriptCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=180)
    script: str = Field(min_length=1, max_length=100_000)
    platform: Literal["youtube", "instagram"]
    language: str = Field(min_length=2, max_length=40)
    target_duration_seconds: int = Field(ge=10, le=600)


class ScriptActionRequest(ScriptBriefRequest):
    action: ScriptActionValue


class ScriptWorkspaceResponse(BaseModel):
    source: ContentSourceResponse
    item: ContentItemResponse
    alternate_hooks: list[str] = Field(default_factory=list)


class ProviderCapabilitiesResponse(BaseModel):
    platform: Literal["youtube", "instagram"]
    can_upload_video: bool
    can_publish_short: bool
    can_schedule: bool
    can_publish_thumbnail: bool
    can_edit_metadata: bool
    can_fetch_analytics: bool
    supported_aspect_ratios: list[str]
    max_video_duration_seconds: int | None = None
    supported_content_types: list[str]
