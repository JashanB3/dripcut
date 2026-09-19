"""FastAPI routes for source import, background rendering and downloads."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from dripcut.admin.repository import build_admin_repository
from dripcut.api.contracts import (
    AdminOverviewResponse,
    AIEditPlanRequest,
    AIEditPlanResponse,
    AuthLoginRequest,
    AuthSessionResponse,
    AuthSignupRequest,
    AuthUserResponse,
    ContentItemCreateRequest,
    ContentItemResponse,
    ContentItemUpdateRequest,
    ContentSourceCreateRequest,
    ContentSourceResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    JobResponse,
    ManualScriptCreateRequest,
    OAuthAuthorizeResponse,
    OAuthTokenRequest,
    OperationsMetricsResponse,
    PasswordRecoveryRequest,
    PasswordRecoveryResponse,
    PasswordResetRequest,
    PlatformTargetCreateRequest,
    PlatformTargetResponse,
    PlatformTargetUpdateRequest,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectUpdateRequest,
    ProviderCapabilitiesResponse,
    RenderRequest,
    ScheduleCreateRequest,
    SchedulePostUpdateRequest,
    ScheduleResponse,
    ScriptActionRequest,
    ScriptGenerateRequest,
    ScriptWorkspaceResponse,
    SocialConnectionResponse,
    SocialDisconnectResponse,
    SocialMetadataRequest,
    SocialMetadataResponse,
    SocialOAuthStartResponse,
    SourceAssetResponse,
    StandardPlanRequest,
    StandardPlanResponse,
    ThumbnailGenerationResponse,
    ThumbnailRequest,
    UsageSummaryResponse,
    ViralMomentAnalysisResponse,
    ViralMomentRequest,
    YouTubeDiagnosticsResponse,
    YouTubeImportRequest,
)
from dripcut.api.service import WebClipService
from dripcut.api.stores import (
    LocalArtifactStore,
    LocalSourceAssetStore,
    ObjectJobStateStore,
    QueueJobStore,
)
from dripcut.auth.models import AuthProviderError, AuthResult
from dripcut.auth.provider import AuthProvider, build_auth_provider
from dripcut.content.models import (
    ContentItemStatus,
    ContentSourceStatus,
    ContentSourceType,
    ContentType,
    PlatformTargetStatus,
    TargetPlatform,
)
from dripcut.content.repository import build_content_repository
from dripcut.content.service import ContentService
from dripcut.core.bootstrap import build_container
from dripcut.core.container import ServiceContainer
from dripcut.core.errors import DripCutError
from dripcut.engines.ai.provider import ScriptBrief, ScriptRewriteAction
from dripcut.engines.export.queue import LocalJobQueue
from dripcut.observability.metrics import summarize_pipeline_jobs
from dripcut.security.rate_limit import InMemoryRateLimiter
from dripcut.services.script_service import ScriptStudioService, ScriptWorkspace
from dripcut.social.store import build_social_store
from dripcut.storage.models import UploadRejected
from dripcut.storage.provider import build_storage_provider
from dripcut.tenancy.models import Principal, TenantAccessDenied
from dripcut.tenancy.repository import TenantRepository, build_tenant_repository
from dripcut.usage.models import QuotaExceeded
from dripcut.usage.repository import build_usage_repository
from dripcut.usage.service import UsageRequest, UsageService

logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    """Resolve production CORS origins while retaining the local variable name."""
    configured = os.environ.get("DRIPCUT_ALLOWED_ORIGINS") or os.environ.get(
        "DRIPCUT_CORS_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    return [value.strip() for value in configured.split(",") if value.strip()]


def _production_mode() -> bool:
    return os.environ.get("DRIPCUT_ENV", "development").strip().lower() in {
        "production",
        "prod",
    }


def _csrf_protection_enabled() -> bool:
    configured = os.environ.get("DRIPCUT_CSRF_PROTECTION")
    if configured is not None:
        return configured.strip().lower() not in {"0", "false", "no", "off"}
    return _production_mode()


def _rate_limit_for(request: Request) -> tuple[str, int] | None:
    """Classify only authentication and resource-intensive API requests."""
    if request.method != "POST":
        return None
    path = request.url.path
    if path in {
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/refresh",
    }:
        return "auth", int(os.environ.get("DRIPCUT_RATE_LIMIT_AUTH", "30"))
    expensive = (
        path in {
            "/api/jobs/clips",
            "/api/jobs/youtube",
            "/api/sources/youtube",
            "/api/ai/edit-plan",
            "/api/scripts/generate",
        }
        or path.startswith("/api/scripts/")
        or path.endswith("/viral-moments")
        or path.endswith("/thumbnails")
        or path.endswith("/social-metadata")
    )
    if expensive:
        return "expensive", int(os.environ.get("DRIPCUT_RATE_LIMIT_EXPENSIVE", "30"))
    if path == "/api/sources/upload":
        return "upload", int(os.environ.get("DRIPCUT_RATE_LIMIT_UPLOAD", "20"))
    return None


def _csrf_error(request: Request, allowed_origins: set[str]) -> str | None:
    """Protect cookie-authenticated mutations with strict production Origin checks."""
    if not _csrf_protection_enabled() or request.method in {"GET", "HEAD", "OPTIONS"}:
        return None
    if not request.url.path.startswith("/api/"):
        return None
    has_cookie_session = bool(request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE))
    has_bearer = request.headers.get("authorization", "").lower().startswith("bearer ")
    if not has_cookie_session or has_bearer:
        return None
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        return "A browser Origin header is required for this authenticated request."
    if origin not in allowed_origins:
        return "This request came from an untrusted origin."
    return None


def _request_headers(
    request: Request, headers: Mapping[str, str] | None = None
) -> dict[str, str]:
    result = dict(headers or {})
    result["x-request-id"] = getattr(request.state, "request_id", "unknown")
    result["cache-control"] = "private, no-store"
    return result


def _error_content(
    *,
    code: str,
    message: str,
    request: Request,
    hint: str | None = None,
    details: object | list[object] | None = None,
    retryable: bool = False,
) -> dict[str, object]:
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            hint=hint,
            details=details,
            request_id=getattr(request.state, "request_id", None),
            retryable=retryable,
        )
    ).model_dump(exclude_none=True)


def build_service(container: ServiceContainer | None = None) -> WebClipService:
    resolved = container or build_container(load_plugins=False)
    root = resolved.paths.projects / "web"
    storage = build_storage_provider(root / "objects")
    resolved.social.storage = storage
    resolved.projects.configure_storage(storage)
    web_queue = LocalJobQueue(
        resolved.events,
        max_workers=resolved.settings.video.max_workers,
        history_file=resolved.paths.history_file,
        state_store=ObjectJobStateStore(storage, resolved.paths.history_file),
        progress_persist_interval=2.0,
    )
    max_upload_bytes = int(resolved.settings.server.max_upload_mb) * 1024 * 1024
    return WebClipService(
        resolved,
        LocalSourceAssetStore(root, storage, max_bytes=max_upload_bytes),
        LocalArtifactStore(root, storage),
        QueueJobStore(web_queue),
    )


ACCESS_COOKIE = "dripcut_access"
REFRESH_COOKIE = "dripcut_refresh"


def _auth_required() -> bool:
    configured = os.environ.get("DRIPCUT_AUTH_REQUIRED")
    if configured is not None:
        return configured.strip().lower() not in {"0", "false", "no", "off"}
    return not os.environ.get("PYTEST_CURRENT_TEST")


def _frontend_url(path: str = "") -> str:
    root = os.environ.get("DRIPCUT_FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
    return f"{root}{path}"


def _social_callback_url(platform: str) -> str:
    root = os.environ.get("DRIPCUT_PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{root}/api/social/{platform}/callback"


def _set_session_cookies(response: Response, result: AuthResult) -> None:
    if result.tokens is None:
        return
    secure = os.environ.get("DRIPCUT_COOKIE_SECURE", "").strip().lower() in {
        "1", "true", "yes", "on"
    } or os.environ.get("DRIPCUT_ENV", "").strip().lower() in {"production", "prod"}
    response.set_cookie(
        ACCESS_COOKIE,
        result.tokens.access_token,
        max_age=result.tokens.expires_in,
        secure=secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        result.tokens.refresh_token,
        max_age=30 * 86400,
        secure=secure,
        httponly=True,
        samesite="lax",
        path="/api/auth",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


def create_app(
    service: WebClipService | None = None,
    *,
    auth_provider: AuthProvider | None = None,
    tenant_repository: TenantRepository | None = None,
    usage_service: UsageService | None = None,
    require_auth: bool | None = None,
) -> FastAPI:
    clip_service = service or build_service()
    web_root = clip_service.container.paths.projects / "web"
    auth = auth_provider or build_auth_provider(web_root)
    tenants = tenant_repository or build_tenant_repository(web_root, auth.name)
    usage = usage_service or UsageService(build_usage_repository(web_root, tenants.name))
    admin_repository = build_admin_repository(
        web_root,
        tenants.name,
        queue=clip_service.container.resolve("queue"),
    )
    social = clip_service.container.social
    social.store = build_social_store(web_root, tenants.name)
    content_repository = build_content_repository(web_root, tenants.name)

    def source_project_id(source_id: str) -> str | None:
        return clip_service.get_source(source_id).project_id

    def artifact_project_id(artifact_id: str) -> str | None:
        artifact = clip_service.get_artifact(artifact_id)
        return clip_service.job_response(artifact.job_id).project_id or None

    content = ContentService(
        content_repository,
        tenants,
        social_store=social.store,
        source_project_id=source_project_id,
        artifact_project_id=artifact_project_id,
    )
    script_studio = ScriptStudioService(content, clip_service.container.ai.content_provider)
    auth_is_required = _auth_required() if require_auth is None else require_auth
    allowed_origins = {origin.rstrip("/") for origin in _allowed_origins()}
    rate_limiter = InMemoryRateLimiter(
        window_seconds=int(os.environ.get("DRIPCUT_RATE_LIMIT_WINDOW_SECONDS", "60"))
    )
    development_session: AuthResult | None = None
    if not auth_is_required and auth.name == "local":
        try:
            development_session = auth.login(email="developer@dripcut.local", password="dripcut-local")
        except AuthProviderError:
            development_session = auth.signup(
                name="Local Developer",
                email="developer@dripcut.local",
                password="dripcut-local",
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        social.start_worker()
        yield
        social.shutdown()
        queue = clip_service.container.try_resolve("queue")
        if queue is not None:
            queue.shutdown(cancel_pending=False)

    app = FastAPI(title="DripCut API", version="1.0.0", lifespan=lifespan)
    app.state.clip_service = clip_service
    app.state.auth_provider = auth
    app.state.tenant_repository = tenants
    app.state.usage_service = usage
    app.state.admin_repository = admin_repository
    app.state.content_service = content
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid4().hex
        started = time.monotonic()
        if csrf_message := _csrf_error(request, allowed_origins):
            return JSONResponse(
                status_code=403,
                headers=_request_headers(request),
                content=_error_content(
                    request=request,
                    code="CSRF_ORIGIN_REJECTED",
                    message=csrf_message,
                ),
            )
        if classification := _rate_limit_for(request):
            scope, limit = classification
            client_host = request.client.host if request.client else "unknown"
            result = rate_limiter.check(f"{scope}:{client_host}", limit=limit)
            if not result.allowed:
                return JSONResponse(
                    status_code=429,
                    headers={
                        **_request_headers(request),
                        "retry-after": str(result.retry_after),
                        "x-ratelimit-limit": str(result.limit),
                        "x-ratelimit-remaining": "0",
                    },
                    content=_error_content(
                        request=request,
                        code="RATE_LIMITED",
                        message="Too many requests. Please wait a moment and try again.",
                        retryable=True,
                    ),
                )
        response = await call_next(request)
        response.headers.update(_request_headers(request))
        logger.info(
            "api_request request_id=%s method=%s path=%s status=%s duration_ms=%s user_id=%s workspace_id=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            round((time.monotonic() - started) * 1000, 2),
            getattr(request.state, "user_id", "anonymous"),
            getattr(request.state, "workspace_id", "none"),
        )
        return response

    @app.exception_handler(DripCutError)
    async def dripcut_error(request: Request, error: DripCutError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                message=error.message,
                hint=error.hint,
                code=error.code,
                retryable=error.retryable,
            ),
        )

    @app.exception_handler(QuotaExceeded)
    async def quota_error(request: Request, error: QuotaExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code=error.code,
                message=error.message,
                hint=error.hint,
                details={
                    "metric": error.metric,
                    "used": error.used,
                    "requested": error.requested,
                    "limit": error.limit,
                },
                retryable=False,
            ),
        )

    @app.exception_handler(UploadRejected)
    async def upload_error(request: Request, error: UploadRejected) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code=error.code,
                message=error.message,
                hint=error.hint,
                retryable=error.retryable,
            ),
        )

    @app.exception_handler(AuthProviderError)
    async def auth_error(request: Request, error: AuthProviderError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code=error.code,
                message=error.message,
                retryable=error.retryable,
            ),
        )

    @app.exception_handler(TenantAccessDenied)
    async def tenant_error(request: Request, _error: TenantAccessDenied) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code="RESOURCE_NOT_FOUND",
                message="That resource could not be found.",
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        safe_details = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ()) if part != "body"),
                "type": str(item.get("type") or "invalid"),
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code="VALIDATION_ERROR",
                message="The request contains invalid or missing information.",
                details=safe_details,
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        retryable = error.status_code == 429 or error.status_code >= 500
        message = (
            "The requested operation could not be completed. Please try again."
            if error.status_code >= 500
            else error.detail
            if isinstance(error.detail, str)
            else "The requested operation could not be completed."
        )
        return JSONResponse(
            status_code=error.status_code,
            headers=_request_headers(request, error.headers),
            content=_error_content(
                request=request,
                code=f"HTTP_{error.status_code}",
                message=message,
                details=None if isinstance(error.detail, str) or error.status_code >= 500 else error.detail,
                retryable=retryable,
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled API error request_id=%s method=%s path=%s",
            getattr(request.state, "request_id", "unknown"),
            request.method,
            request.url.path,
            exc_info=error,
        )
        return JSONResponse(
            status_code=500,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code="INTERNAL_SERVER_ERROR",
                message="Something went wrong while processing this request.",
                retryable=True,
            ),
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        runner = clip_service.container.resolve("ffmpeg")
        probe = clip_service.container.resolve("probe")
        return HealthResponse(status="ok", ffmpeg=runner.available(), ffprobe=probe.available())

    def current_principal(request: Request) -> Principal:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        token = token or request.cookies.get(ACCESS_COOKIE, "")
        if not token and development_session and development_session.tokens:
            token = development_session.tokens.access_token
        if not token:
            raise AuthProviderError(
                "Log in to continue.", status_code=401, code="AUTHENTICATION_REQUIRED"
            )
        user = auth.get_user(token)
        principal = tenants.principal_for(user, token)
        request.state.user_id = principal.user.id
        request.state.workspace_id = principal.workspace_id
        return principal

    principal_dependency = Depends(current_principal)

    def require_workspace_admin(
        principal: Principal = principal_dependency,
    ) -> Principal:
        if principal.role not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="Workspace admin access is required.")
        return principal

    admin_dependency = Depends(require_workspace_admin)

    def require_dripcut_admin(
        principal: Principal = principal_dependency,
    ) -> Principal:
        if not principal.is_dripcut_admin:
            raise HTTPException(status_code=403, detail="DripCut admin access is required.")
        return principal

    dripcut_admin_dependency = Depends(require_dripcut_admin)

    @app.get("/api/admin/overview", response_model=AdminOverviewResponse)
    def admin_overview(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        _principal: Principal = dripcut_admin_dependency,
    ) -> AdminOverviewResponse:
        return AdminOverviewResponse.model_validate(asdict(admin_repository.snapshot(limit=limit)))

    @app.get("/api/operations/metrics", response_model=OperationsMetricsResponse)
    def operations_metrics(
        principal: Principal = admin_dependency,
    ) -> OperationsMetricsResponse:
        queue = clip_service.container.resolve("queue")
        jobs = [
            job
            for job in queue.all_jobs(limit=200)
            if tenants.can_access(principal, "job", job.id)
        ]
        summary = summarize_pipeline_jobs(jobs)
        encoder = clip_service.container.resolve("ffmpeg").encoder_selection("h264")
        return OperationsMetricsResponse(
            **summary,
            encoder={
                "codec": encoder.codec,
                "encoder": encoder.encoder,
                "provider": encoder.provider,
                "hardware": encoder.hardware,
            },
        )

    def auth_response(result: AuthResult, response: Response) -> AuthSessionResponse:
        _set_session_cookies(response, result)
        principal = None
        if result.tokens:
            principal = tenants.principal_for(result.user, result.tokens.access_token)
        return AuthSessionResponse(
            authenticated=result.tokens is not None,
            provider=auth.name,
            user=(
                AuthUserResponse(
                    id=result.user.id,
                    email=result.user.email,
                    name=result.user.name,
                    workspace_id=principal.workspace_id if principal else None,
                    role=principal.role if principal else None,
                    is_dripcut_admin=principal.is_dripcut_admin if principal else False,
                )
                if result.tokens
                else None
            ),
            requires_email_confirmation=result.requires_email_confirmation,
            message=(
                "Check your email to confirm your account."
                if result.requires_email_confirmation
                else None
            ),
        )

    @app.post("/api/auth/signup", response_model=AuthSessionResponse, status_code=201)
    def signup(payload: AuthSignupRequest, response: Response) -> AuthSessionResponse:
        return auth_response(
            auth.signup(name=payload.name, email=payload.email, password=payload.password),
            response,
        )

    @app.post("/api/auth/login", response_model=AuthSessionResponse)
    def login(payload: AuthLoginRequest, response: Response) -> AuthSessionResponse:
        return auth_response(auth.login(email=payload.email, password=payload.password), response)

    @app.get("/api/auth/session", response_model=AuthSessionResponse)
    def session(request: Request) -> AuthSessionResponse:
        try:
            principal = current_principal(request)
        except AuthProviderError:
            return AuthSessionResponse(authenticated=False, provider=auth.name)
        return AuthSessionResponse(
            authenticated=True,
            provider=auth.name,
            user=AuthUserResponse(
                id=principal.user.id,
                email=principal.user.email,
                name=principal.user.name,
                workspace_id=principal.workspace_id,
                role=principal.role,
                is_dripcut_admin=principal.is_dripcut_admin,
            ),
        )

    @app.post("/api/auth/refresh", response_model=AuthSessionResponse)
    def refresh_session(request: Request, response: Response) -> AuthSessionResponse:
        token = request.cookies.get(REFRESH_COOKIE, "")
        if not token:
            raise AuthProviderError(
                "Your session has expired. Please log in again.",
                status_code=401,
                code="SESSION_EXPIRED",
            )
        return auth_response(auth.refresh(token), response)

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request) -> Response:
        token = request.cookies.get(ACCESS_COOKIE, "")
        if token:
            with suppress(AuthProviderError):
                auth.logout(token)
        response = Response(status_code=204)
        _clear_session_cookies(response)
        return response

    @app.post("/api/auth/forgot-password", response_model=PasswordRecoveryResponse)
    def forgot_password(payload: PasswordRecoveryRequest) -> PasswordRecoveryResponse:
        auth.request_password_reset(
            email=payload.email,
            redirect_to=_frontend_url("/reset-password"),
        )
        return PasswordRecoveryResponse(
            message="If an account exists for that email, a reset link has been sent."
        )

    @app.post("/api/auth/reset-password", response_model=AuthSessionResponse)
    def reset_password(
        payload: PasswordResetRequest, request: Request, response: Response
    ) -> AuthSessionResponse:
        token = payload.access_token or request.cookies.get(ACCESS_COOKIE, "")
        if not token:
            raise AuthProviderError(
                "Open the password reset link from your email.",
                status_code=401,
                code="RESET_TOKEN_REQUIRED",
            )
        user = auth.reset_password(access_token=token, password=payload.password)
        if payload.refresh_token:
            return auth_response(
                auth.accept_external_tokens(
                    access_token=token,
                    refresh_token=payload.refresh_token,
                ),
                response,
            )
        principal = tenants.principal_for(user, token)
        return AuthSessionResponse(
            authenticated=True,
            provider=auth.name,
            user=AuthUserResponse(
                id=user.id,
                email=user.email,
                name=user.name,
                workspace_id=principal.workspace_id,
                role=principal.role,
                is_dripcut_admin=principal.is_dripcut_admin,
            ),
        )

    @app.get("/api/auth/google", response_model=OAuthAuthorizeResponse)
    def google_oauth() -> OAuthAuthorizeResponse:
        url = auth.google_authorize_url(redirect_to=_frontend_url("/auth/callback"))
        if not url:
            raise AuthProviderError(
                "Google login is available when Supabase authentication is configured.",
                status_code=503,
                code="GOOGLE_AUTH_NOT_CONFIGURED",
            )
        return OAuthAuthorizeResponse(authorize_url=url)

    @app.post("/api/auth/oauth/exchange", response_model=AuthSessionResponse)
    def exchange_oauth(payload: OAuthTokenRequest, response: Response) -> AuthSessionResponse:
        return auth_response(
            auth.accept_external_tokens(
                access_token=payload.access_token,
                refresh_token=payload.refresh_token,
            ),
            response,
        )

    @app.get("/api/usage", response_model=UsageSummaryResponse)
    def usage_summary(
        principal: Principal = principal_dependency,
    ) -> UsageSummaryResponse:
        return UsageSummaryResponse.model_validate(usage.summary(principal))

    def register_project(principal: Principal, project: ProjectResponse) -> None:
        tenants.register(
            principal,
            "project",
            project.id,
            attributes={
                "title": project.title,
                "project_type": project.project_type,
                "status": project.status,
                "output_format": project.output_format,
            },
        )
        clip_service.claim_project(project.id, principal.user.id)

    def register_source(principal: Principal, source: SourceAssetResponse) -> None:
        if not source.project_id:
            raise HTTPException(status_code=500, detail="Imported source is missing its project.")
        project = clip_service.get_project(source.project_id)
        register_project(principal, project)
        source_record = clip_service.get_source(source.id)
        tenants.register(
            principal,
            "source",
            source.id,
            project_id=source.project_id,
            attributes={
                "kind": source.kind,
                "name": source.name,
                "duration": source.duration,
                "size_bytes": source.size_bytes,
                "mime_type": source.mime_type,
                "storage_key": source_record.storage_key,
                "poster_storage_key": source_record.poster_storage_key,
                "width": source.width,
                "height": source.height,
                "source_url": source.youtube_url,
            },
        )
        content.ensure_media_source(
            principal,
            project_id=source.project_id,
            source_asset_id=source.id,
            kind=source.kind,
            title=source.title,
            external_url=source.youtube_url,
        )

    def register_job(principal: Principal, job: JobResponse) -> None:
        if job.project_id:
            project = clip_service.get_project(job.project_id)
            register_project(principal, project)
        if job.source_id and not tenants.can_access(principal, "source", job.source_id):
            register_source(principal, clip_service.source_response(job.source_id))
        tenants.register(
            principal,
            "job",
            job.id,
            project_id=job.project_id or None,
            attributes={
                "source_id": job.source_id or None,
                "status": job.status,
                "progress": job.progress,
                "stage": job.stage,
                "error_code": job.error_code,
                "error_message": job.error,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "idempotency_key": job.idempotency_key,
            },
        )
        for artifact in job.artifacts:
            artifact_record = clip_service.get_artifact(artifact.id)
            tenants.register(
                principal,
                "artifact",
                artifact.id,
                project_id=job.project_id or None,
                attributes={
                    "job_id": artifact.job_id,
                    "kind": artifact.kind,
                    "name": artifact.name,
                    "size_bytes": artifact.size_bytes,
                    "mime_type": artifact.mime_type,
                    "storage_key": artifact_record.storage_key,
                },
            )
            if artifact.kind == "clip" and job.project_id:
                content.ensure_rendered_clip(
                    principal,
                    project_id=job.project_id,
                    source_id=job.source_id or None,
                    artifact_id=artifact.id,
                    title=Path(artifact.name).stem,
                    duration_seconds=artifact.duration,
                    output_format=artifact.output_format,
                    captions_enabled=artifact.captions_enabled,
                    job_id=job.id,
                    index=artifact.index,
                )

    def resolve_script_project(
        principal: Principal,
        project_id: str | None,
        title: str,
    ) -> tuple[str, bool]:
        if project_id:
            tenants.require_access(principal, "project", project_id)
            return project_id, False
        project = clip_service.create_content_project(title, project_type="script")
        register_project(principal, project)
        return project.id, True

    def clean_failed_script_project(principal: Principal, project_id: str, created: bool) -> None:
        if not created:
            return
        with suppress(Exception):
            content.delete_project(principal, project_id)
        with suppress(Exception):
            clip_service.delete_project(project_id)
        with suppress(Exception):
            tenants.delete_project(principal, project_id)

    def script_brief(payload: ScriptGenerateRequest | ScriptActionRequest) -> ScriptBrief:
        return ScriptBrief.model_validate(
            payload.model_dump(exclude={"project_id", "action"})
        )

    def script_response(workspace: ScriptWorkspace) -> ScriptWorkspaceResponse:
        return ScriptWorkspaceResponse(
            source=ContentSourceResponse.model_validate(workspace.source),
            item=ContentItemResponse.model_validate(workspace.item),
            alternate_hooks=list(workspace.alternate_hooks),
        )

    @app.post(
        "/api/scripts/manual",
        response_model=ScriptWorkspaceResponse,
        status_code=201,
    )
    def create_manual_script(
        payload: ManualScriptCreateRequest,
        principal: Principal = principal_dependency,
    ) -> ScriptWorkspaceResponse:
        project_id, created = resolve_script_project(
            principal,
            payload.project_id,
            payload.title,
        )
        try:
            return script_response(
                script_studio.create_manual(
                    principal,
                    project_id,
                    title=payload.title,
                    script=payload.script,
                    platform=payload.platform,
                    language=payload.language,
                    target_duration_seconds=payload.target_duration_seconds,
                )
            )
        except Exception:
            clean_failed_script_project(principal, project_id, created)
            raise

    @app.post(
        "/api/scripts/generate",
        response_model=ScriptWorkspaceResponse,
        status_code=201,
    )
    def generate_script(
        payload: ScriptGenerateRequest,
        principal: Principal = principal_dependency,
    ) -> ScriptWorkspaceResponse:
        project_id, created = resolve_script_project(
            principal,
            payload.project_id,
            payload.topic,
        )
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("ai_editor_actions", 1)],
            project_id=project_id,
        )
        try:
            workspace = script_studio.generate(principal, project_id, script_brief(payload))
            reservation.commit()
            return script_response(workspace)
        except Exception:
            reservation.release()
            clean_failed_script_project(principal, project_id, created)
            raise

    @app.post(
        "/api/scripts/{content_id}/actions",
        response_model=ScriptWorkspaceResponse,
    )
    def run_script_action(
        content_id: str,
        payload: ScriptActionRequest,
        principal: Principal = principal_dependency,
    ) -> ScriptWorkspaceResponse:
        item = content.item(principal, content_id)
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("ai_editor_actions", 1)],
            project_id=item.project_id,
        )
        try:
            brief = script_brief(payload)
            if payload.action == "generate_hooks":
                workspace = script_studio.hooks(principal, content_id, brief=brief)
            elif payload.action in {"adapt_youtube", "adapt_instagram"}:
                workspace = script_studio.adapt(
                    principal,
                    content_id,
                    platform=payload.action.removeprefix("adapt_"),
                    brief=brief,
                )
            else:
                workspace = script_studio.rewrite(
                    principal,
                    content_id,
                    action=cast(ScriptRewriteAction, payload.action),
                    brief=brief,
                )
            reservation.commit()
            return script_response(workspace)
        except Exception:
            reservation.release()
            raise

    @app.post("/api/sources/upload", response_model=SourceAssetResponse, status_code=201)
    def upload_source(
        video: Annotated[UploadFile, File()],
        principal: Principal = principal_dependency,
    ) -> SourceAssetResponse:
        max_bytes = int(clip_service.container.settings.server.max_upload_mb) * 1024 * 1024
        if video.size is not None and video.size > max_bytes:
            raise UploadRejected(
                "This video is larger than the upload limit.",
                code="UPLOAD_TOO_LARGE",
                status_code=413,
                hint=f"Choose a video smaller than {max_bytes // 1024 // 1024} MB.",
            )
        content_type = (video.content_type or "").lower()
        if content_type and not (
            content_type.startswith("video/") or content_type == "application/octet-stream"
        ):
            raise UploadRejected(
                "This upload is not a supported video.",
                code="INVALID_VIDEO_TYPE",
                hint="Upload an MP4, MOV, WebM, or Matroska video.",
            )
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("storage_bytes", float(video.size or 0))],
        )
        try:
            source = clip_service.import_upload(video.filename or "source.mp4", video.file)
            register_source(principal, source)
            reservation.commit()
            return source
        except Exception:
            reservation.release()
            raise

    @app.post("/api/sources/youtube", response_model=SourceAssetResponse, status_code=201)
    def import_youtube(
        payload: YouTubeImportRequest,
        principal: Principal = principal_dependency,
    ) -> SourceAssetResponse:
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("youtube_imports", 1)],
        )
        try:
            source = clip_service.import_youtube(
                payload.url, rights_confirmed=payload.rights_confirmed
            )
            register_source(principal, source)
            reservation.commit()
            return source
        except Exception:
            reservation.release()
            raise

    @app.post("/api/jobs/youtube", response_model=JobResponse, status_code=202)
    def queue_youtube_import(
        payload: YouTubeImportRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=200)
        ] = None,
        principal: Principal = principal_dependency,
    ) -> JobResponse:
        scoped_key = (
            f"{principal.workspace_id}:youtube:{idempotency_key}"
            if idempotency_key
            else None
        )
        if scoped_key and (existing := clip_service.idempotent_job(scoped_key)):
            register_job(principal, existing)
            return existing
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("youtube_imports", 1)],
        )
        try:
            job = clip_service.create_youtube_import(
                payload.url,
                rights_confirmed=payload.rights_confirmed,
                on_success=reservation.commit,
                on_failure=reservation.release,
                idempotency_key=scoped_key,
            )
            register_job(principal, job)
            return job
        except Exception:
            reservation.release()
            raise

    @app.get("/api/projects", response_model=list[ProjectResponse])
    def list_projects(
        limit: Annotated[int | None, Query(ge=1, le=200)] = None,
        principal: Principal = principal_dependency,
    ) -> list[ProjectResponse]:
        allowed = tenants.project_ids(principal)
        projects = clip_service.list_projects(limit=200, project_ids=allowed)
        return projects[:limit] if limit else projects

    @app.get("/api/projects/{project_id}", response_model=ProjectDetailResponse)
    def get_project(
        project_id: str,
        principal: Principal = principal_dependency,
    ) -> ProjectDetailResponse:
        tenants.require_access(principal, "project", project_id)
        return clip_service.get_project(project_id)

    @app.patch("/api/projects/{project_id}", response_model=ProjectResponse)
    def update_project(
        project_id: str,
        payload: ProjectUpdateRequest,
        principal: Principal = principal_dependency,
    ) -> ProjectResponse:
        tenants.require_access(principal, "project", project_id)
        project = clip_service.rename_project(project_id, payload.title)
        register_project(principal, project)
        return project

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(
        project_id: str,
        principal: Principal = principal_dependency,
    ) -> Response:
        tenants.require_access(principal, "project", project_id)
        content.delete_project(principal, project_id)
        clip_service.delete_project(project_id)
        tenants.delete_project(principal, project_id)
        return Response(status_code=204)

    @app.get(
        "/api/projects/{project_id}/sources/content",
        response_model=list[ContentSourceResponse],
    )
    def list_content_sources(
        project_id: str,
        principal: Principal = principal_dependency,
    ) -> list[ContentSourceResponse]:
        tenants.require_access(principal, "project", project_id)
        return [
            ContentSourceResponse.model_validate(source)
            for source in content_repository.list_sources(
                principal.workspace_id,
                project_id,
                access_token=principal.access_token,
            )
        ]

    @app.post(
        "/api/projects/{project_id}/sources/content",
        response_model=ContentSourceResponse,
        status_code=201,
    )
    def create_content_source(
        project_id: str,
        payload: ContentSourceCreateRequest,
        principal: Principal = principal_dependency,
    ) -> ContentSourceResponse:
        source = content.create_source(
            principal,
            project_id,
            source_type=ContentSourceType(payload.source_type),
            title=payload.title,
            text_content=payload.text_content,
            source_asset_id=payload.source_asset_id,
            external_url=payload.external_url,
            metadata=payload.metadata,
            status=ContentSourceStatus(payload.status),
            rights_confirmed=payload.rights_confirmed,
        )
        return ContentSourceResponse.model_validate(source)

    @app.get(
        "/api/projects/{project_id}/content",
        response_model=list[ContentItemResponse],
    )
    def list_project_content(
        project_id: str,
        principal: Principal = principal_dependency,
    ) -> list[ContentItemResponse]:
        return [
            ContentItemResponse.model_validate(item)
            for item in content.list_project_content(principal, project_id)
        ]

    @app.post(
        "/api/projects/{project_id}/content",
        response_model=ContentItemResponse,
        status_code=201,
    )
    def create_content_item(
        project_id: str,
        payload: ContentItemCreateRequest,
        principal: Principal = principal_dependency,
    ) -> ContentItemResponse:
        values = payload.model_dump()
        values["content_type"] = ContentType(payload.content_type)
        values["status"] = ContentItemStatus(payload.status)
        item = content.create_item(principal, project_id, **values)
        return ContentItemResponse.model_validate(item)

    @app.get("/api/content/{content_id}", response_model=ContentItemResponse)
    def get_content_item(
        content_id: str,
        principal: Principal = principal_dependency,
    ) -> ContentItemResponse:
        return ContentItemResponse.model_validate(content.item(principal, content_id))

    @app.patch("/api/content/{content_id}", response_model=ContentItemResponse)
    def update_content_item(
        content_id: str,
        payload: ContentItemUpdateRequest,
        principal: Principal = principal_dependency,
    ) -> ContentItemResponse:
        values = payload.model_dump(exclude_unset=True)
        if values.get("status") is not None:
            values["status"] = ContentItemStatus(values["status"])
        item = content.update_item(principal, content_id, **values)
        return ContentItemResponse.model_validate(item)

    @app.delete("/api/content/{content_id}", status_code=204)
    def delete_content_item(
        content_id: str,
        principal: Principal = principal_dependency,
    ) -> Response:
        content.delete_item(principal, content_id)
        return Response(status_code=204)

    @app.get(
        "/api/content/{content_id}/targets",
        response_model=list[PlatformTargetResponse],
    )
    def list_platform_targets(
        content_id: str,
        principal: Principal = principal_dependency,
    ) -> list[PlatformTargetResponse]:
        return [
            PlatformTargetResponse.model_validate(target)
            for target in content.list_targets(principal, content_id)
        ]

    @app.post(
        "/api/content/{content_id}/targets",
        response_model=PlatformTargetResponse,
        status_code=201,
    )
    def create_platform_target(
        content_id: str,
        payload: PlatformTargetCreateRequest,
        principal: Principal = principal_dependency,
    ) -> PlatformTargetResponse:
        values = payload.model_dump()
        values["platform"] = TargetPlatform(payload.platform)
        target = content.create_target(principal, content_id, **values)
        return PlatformTargetResponse.model_validate(target)

    @app.patch(
        "/api/content/{content_id}/targets/{target_id}",
        response_model=PlatformTargetResponse,
    )
    def update_platform_target(
        content_id: str,
        target_id: str,
        payload: PlatformTargetUpdateRequest,
        principal: Principal = principal_dependency,
    ) -> PlatformTargetResponse:
        values = payload.model_dump(exclude_unset=True)
        if values.get("publish_status") is not None:
            values["publish_status"] = PlatformTargetStatus(values["publish_status"])
        target = content.update_target(principal, content_id, target_id, **values)
        return PlatformTargetResponse.model_validate(target)

    @app.delete("/api/content/{content_id}/targets/{target_id}", status_code=204)
    def delete_platform_target(
        content_id: str,
        target_id: str,
        principal: Principal = principal_dependency,
    ) -> Response:
        content.delete_target(principal, content_id, target_id)
        return Response(status_code=204)

    @app.post(
        "/api/projects/{project_id}/thumbnails",
        response_model=ThumbnailGenerationResponse,
        status_code=201,
    )
    def create_thumbnails(
        project_id: str,
        payload: ThumbnailRequest,
        principal: Principal = principal_dependency,
    ) -> ThumbnailGenerationResponse:
        tenants.require_access(principal, "project", project_id)
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("thumbnail_generations", 1)],
            project_id=project_id,
        )
        try:
            artifacts = clip_service.create_thumbnail_candidates(project_id, payload)
            if artifacts.candidates:
                job_id = artifacts.candidates[0].job_id
                tenants.register(
                    principal,
                    "job",
                    job_id,
                    project_id=project_id,
                    attributes={"status": "succeeded", "progress": 1, "stage": "Thumbnails ready"},
                )
                for artifact in artifacts.candidates:
                    artifact_record = clip_service.get_artifact(artifact.id)
                    tenants.register(
                        principal,
                        "artifact",
                        artifact.id,
                        project_id=project_id,
                        attributes={
                            "job_id": job_id,
                            "kind": artifact.kind,
                            "name": artifact.name,
                            "size_bytes": artifact.size_bytes,
                            "mime_type": artifact.mime_type,
                            "storage_key": artifact_record.storage_key,
                        },
                    )
            reservation.commit()
            return artifacts
        except Exception:
            reservation.release()
            raise

    @app.post("/api/ai/edit-plan", response_model=AIEditPlanResponse)
    def create_ai_edit_plan(
        payload: AIEditPlanRequest,
        principal: Principal = principal_dependency,
    ) -> AIEditPlanResponse:
        tenants.require_access(principal, "source", payload.source_id)
        source = clip_service.source_response(payload.source_id)
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("ai_editor_actions", 1)],
            project_id=source.project_id,
        )
        try:
            result = clip_service.plan_ai_edit(payload)
            reservation.commit()
            return result
        except Exception:
            reservation.release()
            raise

    @app.post(
        "/api/sources/{source_id}/viral-moments",
        response_model=ViralMomentAnalysisResponse,
    )
    def find_viral_moments(
        source_id: str,
        payload: ViralMomentRequest,
        principal: Principal = principal_dependency,
    ) -> ViralMomentAnalysisResponse:
        tenants.require_access(principal, "source", source_id)
        source = clip_service.source_response(source_id)
        reservation = usage.reserve_many(
            principal,
            [
                UsageRequest("ai_viral_analyses", 1),
                UsageRequest("transcription_minutes", source.duration / 60),
            ],
            project_id=source.project_id,
        )
        try:
            result = clip_service.find_viral_moments(source_id, payload)
            reservation.commit()
            return result
        except Exception:
            reservation.release()
            raise

    @app.get("/api/social/connections", response_model=list[SocialConnectionResponse])
    def social_connections(
        principal: Principal = principal_dependency,
    ) -> list[SocialConnectionResponse]:
        return clip_service.social_connections(principal)

    @app.get(
        "/api/social/capabilities",
        response_model=list[ProviderCapabilitiesResponse],
    )
    def social_capabilities(
        principal: Principal = principal_dependency,
    ) -> list[ProviderCapabilitiesResponse]:
        del principal
        return [
            ProviderCapabilitiesResponse.model_validate(asdict(capabilities))
            for capabilities in social.capabilities()
        ]

    @app.get(
        "/api/social/{platform}/authorize",
        response_model=SocialOAuthStartResponse,
    )
    def begin_social_oauth(
        platform: Literal["youtube", "instagram"],
        principal: Principal = principal_dependency,
    ) -> SocialOAuthStartResponse:
        authorization_url = social.begin_oauth(
            platform,
            principal,
            redirect_uri=_social_callback_url(platform),
        )
        return SocialOAuthStartResponse(
            platform=platform,
            authorization_url=authorization_url,
        )

    @app.get("/api/social/{platform}/callback", response_model=None)
    def finish_social_oauth(
        platform: Literal["youtube", "instagram"],
        code: str = Query(default="", max_length=4096),
        state: str = Query(default="", max_length=4096),
        error: str = Query(default="", max_length=200),
        principal: Principal = principal_dependency,
    ) -> RedirectResponse:
        if error:
            return RedirectResponse(
                _frontend_url(f"/schedule?social={platform}-denied"),
                status_code=303,
            )
        social.complete_oauth(
            platform,
            principal,
            code=code,
            state=state,
            redirect_uri=_social_callback_url(platform),
        )
        return RedirectResponse(
            _frontend_url(f"/schedule?social={platform}-connected"),
            status_code=303,
        )

    @app.delete(
        "/api/social/{platform}",
        response_model=SocialDisconnectResponse,
    )
    def disconnect_social(
        platform: Literal["youtube", "instagram"],
        principal: Principal = principal_dependency,
    ) -> SocialDisconnectResponse:
        social.disconnect(platform, principal)
        return SocialDisconnectResponse(platform=platform)

    @app.post(
        "/api/projects/{project_id}/social-metadata",
        response_model=SocialMetadataResponse,
    )
    def generate_social_metadata(
        project_id: str,
        payload: SocialMetadataRequest,
        principal: Principal = principal_dependency,
    ) -> SocialMetadataResponse:
        tenants.require_access(principal, "project", project_id)
        if payload.artifact_id:
            tenants.require_access(principal, "artifact", payload.artifact_id)
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("ai_editor_actions", 1)],
            project_id=project_id,
        )
        try:
            result = clip_service.generate_social_metadata(project_id, payload)
            reservation.commit()
            return result
        except Exception:
            reservation.release()
            raise

    @app.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
    def create_schedule(
        payload: ScheduleCreateRequest,
        principal: Principal = principal_dependency,
    ) -> ScheduleResponse:
        tenants.require_access(principal, "project", payload.project_id)
        project = clip_service.get_project(payload.project_id)
        post_count = max(1, project.clip_count) * len(payload.platforms)
        reservation = usage.reserve_many(
            principal,
            [UsageRequest("scheduled_posts", float(post_count))],
            project_id=payload.project_id,
        )
        try:
            result = clip_service.create_schedule(payload, principal)
            reservation.commit()
            return result
        except Exception:
            reservation.release()
            raise

    @app.get("/api/schedules/latest", response_model=ScheduleResponse | None)
    def latest_schedule(
        principal: Principal = principal_dependency,
    ) -> ScheduleResponse | None:
        return clip_service.latest_schedule(principal)

    @app.get("/api/schedules/{schedule_id}", response_model=ScheduleResponse)
    def get_schedule(
        schedule_id: str,
        principal: Principal = principal_dependency,
    ) -> ScheduleResponse:
        return clip_service.get_schedule(schedule_id, principal)

    @app.patch(
        "/api/schedules/{schedule_id}/posts/{post_id}",
        response_model=ScheduleResponse,
    )
    def update_scheduled_post(
        schedule_id: str,
        post_id: str,
        payload: SchedulePostUpdateRequest,
        principal: Principal = principal_dependency,
    ) -> ScheduleResponse:
        return clip_service.update_scheduled_post(
            schedule_id,
            post_id,
            payload,
            principal,
        )

    @app.get("/api/youtube/diagnostics", response_model=YouTubeDiagnosticsResponse)
    def youtube_diagnostics(
        _principal: Principal = principal_dependency,
    ) -> YouTubeDiagnosticsResponse:
        return YouTubeDiagnosticsResponse(**clip_service.container.youtube.diagnostics().to_dict())

    @app.get("/api/sources/{source_id}", response_model=SourceAssetResponse)
    def get_source(
        source_id: str,
        principal: Principal = principal_dependency,
    ) -> SourceAssetResponse:
        tenants.require_access(principal, "source", source_id)
        return clip_service.source_response(source_id)

    @app.post("/api/sources/{source_id}/standard-plan", response_model=StandardPlanResponse)
    def standard_plan(
        source_id: str,
        payload: StandardPlanRequest,
        principal: Principal = principal_dependency,
    ) -> StandardPlanResponse:
        tenants.require_access(principal, "source", source_id)
        return clip_service.standard_plan(source_id, payload)

    @app.get("/api/sources/{source_id}/media")
    def source_media(
        source_id: str,
        principal: Principal = principal_dependency,
    ) -> FileResponse:
        tenants.require_access(principal, "source", source_id)
        source = clip_service.get_source(source_id)
        return FileResponse(source.path, media_type=source.mime_type, filename=None)

    @app.get("/api/sources/{source_id}/poster")
    def source_poster(
        source_id: str,
        principal: Principal = principal_dependency,
    ) -> FileResponse:
        tenants.require_access(principal, "source", source_id)
        source = clip_service.get_source(source_id)
        if not source.poster_path or not Path(source.poster_path).is_file():
            from dripcut.core.errors import ValidationError

            raise ValidationError("This source has no preview image.")
        return FileResponse(source.poster_path, media_type="image/jpeg")

    @app.post("/api/jobs/clips", response_model=JobResponse, status_code=202)
    def create_clips(
        payload: RenderRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=200)
        ] = None,
        principal: Principal = principal_dependency,
    ) -> JobResponse:
        tenants.require_access(principal, "source", payload.source_id)
        scoped_key = (
            f"{principal.workspace_id}:clips:{idempotency_key}"
            if idempotency_key
            else None
        )
        if scoped_key and (existing := clip_service.idempotent_job(scoped_key)):
            register_job(principal, existing)
            return existing
        source = clip_service.source_response(payload.source_id)
        requests = [
            UsageRequest(
                "video_processing_minutes",
                sum(max(0, segment.end - segment.start) for segment in payload.segments) / 60,
            )
        ]
        if payload.auto_captions:
            requests.append(UsageRequest("transcription_minutes", source.duration / 60))
        reservation = usage.reserve_many(
            principal,
            requests,
            project_id=source.project_id,
        )
        try:
            job = clip_service.create_render(
                payload,
                on_success=reservation.commit,
                on_failure=reservation.release,
                idempotency_key=scoped_key,
            )
            register_job(principal, job)
            return job
        except Exception:
            reservation.release()
            raise

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def get_job(
        job_id: str,
        principal: Principal = principal_dependency,
    ) -> JobResponse:
        tenants.require_access(principal, "job", job_id)
        job = clip_service.job_response(job_id)
        register_job(principal, job)
        return job

    @app.get("/api/artifacts/{artifact_id}/media")
    def stream_artifact(
        artifact_id: str,
        principal: Principal = principal_dependency,
    ) -> FileResponse:
        tenants.require_access(principal, "artifact", artifact_id)
        artifact = clip_service.get_artifact(artifact_id)
        return FileResponse(artifact.path, media_type=artifact.mime_type, filename=None)

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(
        artifact_id: str,
        principal: Principal = principal_dependency,
    ) -> FileResponse:
        tenants.require_access(principal, "artifact", artifact_id)
        artifact = clip_service.get_artifact(artifact_id)
        return FileResponse(artifact.path, media_type=artifact.mime_type, filename=artifact.name)

    return app
