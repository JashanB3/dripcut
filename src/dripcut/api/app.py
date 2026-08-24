"""FastAPI routes for source import, background rendering and downloads."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from dripcut.api.contracts import (
    AIEditPlanRequest,
    AIEditPlanResponse,
    ArtifactResponse,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    JobResponse,
    ProjectDetailResponse,
    ProjectResponse,
    RenderRequest,
    ScheduleCreateRequest,
    ScheduleResponse,
    SocialConnectionResponse,
    SourceAssetResponse,
    StandardPlanRequest,
    StandardPlanResponse,
    ThumbnailRequest,
    YouTubeDiagnosticsResponse,
    YouTubeImportRequest,
)
from dripcut.api.service import WebClipService
from dripcut.api.stores import LocalArtifactStore, LocalSourceAssetStore, QueueJobStore
from dripcut.core.bootstrap import build_container
from dripcut.core.container import ServiceContainer
from dripcut.core.errors import DripCutError

logger = logging.getLogger(__name__)


def _request_headers(
    request: Request, headers: Mapping[str, str] | None = None
) -> dict[str, str]:
    result = dict(headers or {})
    result["x-request-id"] = getattr(request.state, "request_id", "unknown")
    return result


def _error_content(
    *,
    code: str,
    message: str,
    request: Request,
    hint: str | None = None,
    details: object | list[object] | None = None,
) -> dict[str, object]:
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            hint=hint,
            details=details,
            request_id=getattr(request.state, "request_id", None),
        )
    ).model_dump(exclude_none=True)


def build_service(container: ServiceContainer | None = None) -> WebClipService:
    resolved = container or build_container(load_plugins=False)
    root = resolved.paths.projects / "web"
    return WebClipService(
        resolved,
        LocalSourceAssetStore(root),
        LocalArtifactStore(root),
        QueueJobStore(resolved.resolve("queue")),
    )


def create_app(service: WebClipService | None = None) -> FastAPI:
    clip_service = service or build_service()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        queue = clip_service.container.try_resolve("queue")
        if queue is not None:
            queue.shutdown(cancel_pending=False)

    app = FastAPI(title="DripCut API", version="1.0.0", lifespan=lifespan)
    app.state.clip_service = clip_service
    allowed_origins = [
        value.strip()
        for value in os.environ.get(
            "DRIPCUT_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if value.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = request.headers.get("x-request-id") or uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(DripCutError)
    async def dripcut_error(request: Request, error: DripCutError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                message=error.message,
                hint=error.hint,
                code=getattr(error, "code", error.__class__.__name__.upper()),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            headers=_request_headers(request),
            content=_error_content(
                request=request,
                code="VALIDATION_ERROR",
                message="The request contains invalid or missing information.",
                details=error.errors(),
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        message = error.detail if isinstance(error.detail, str) else "The requested operation could not be completed."
        return JSONResponse(
            status_code=error.status_code,
            headers=_request_headers(request, error.headers),
            content=_error_content(
                request=request,
                code=f"HTTP_{error.status_code}",
                message=message,
                details=None if isinstance(error.detail, str) else error.detail,
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
            ),
        )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        runner = clip_service.container.resolve("ffmpeg")
        probe = clip_service.container.resolve("probe")
        return HealthResponse(status="ok", ffmpeg=runner.available(), ffprobe=probe.available())

    @app.post("/api/sources/upload", response_model=SourceAssetResponse, status_code=201)
    def upload_source(video: Annotated[UploadFile, File()]) -> SourceAssetResponse:
        return clip_service.import_upload(video.filename or "source.mp4", video.file)

    @app.post("/api/sources/youtube", response_model=SourceAssetResponse, status_code=201)
    def import_youtube(payload: YouTubeImportRequest) -> SourceAssetResponse:
        return clip_service.import_youtube(
            payload.url, rights_confirmed=payload.rights_confirmed
        )

    @app.post("/api/jobs/youtube", response_model=JobResponse, status_code=202)
    def queue_youtube_import(payload: YouTubeImportRequest) -> JobResponse:
        return clip_service.create_youtube_import(
            payload.url, rights_confirmed=payload.rights_confirmed
        )

    @app.get("/api/projects", response_model=list[ProjectResponse])
    def list_projects(
        limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    ) -> list[ProjectResponse]:
        return clip_service.list_projects(limit=limit)

    @app.get("/api/projects/{project_id}", response_model=ProjectDetailResponse)
    def get_project(project_id: str) -> ProjectDetailResponse:
        return clip_service.get_project(project_id)

    @app.post(
        "/api/projects/{project_id}/thumbnails",
        response_model=list[ArtifactResponse],
        status_code=201,
    )
    def create_thumbnails(
        project_id: str, payload: ThumbnailRequest
    ) -> list[ArtifactResponse]:
        return clip_service.create_thumbnail_candidates(project_id, payload)

    @app.post("/api/ai/edit-plan", response_model=AIEditPlanResponse)
    def create_ai_edit_plan(payload: AIEditPlanRequest) -> AIEditPlanResponse:
        return clip_service.plan_ai_edit(payload)

    @app.get("/api/social/connections", response_model=list[SocialConnectionResponse])
    def social_connections() -> list[SocialConnectionResponse]:
        return clip_service.social_connections()

    @app.post("/api/schedules", response_model=ScheduleResponse, status_code=201)
    def create_schedule(payload: ScheduleCreateRequest) -> ScheduleResponse:
        return clip_service.create_schedule(payload)

    @app.get("/api/youtube/diagnostics", response_model=YouTubeDiagnosticsResponse)
    def youtube_diagnostics() -> YouTubeDiagnosticsResponse:
        return YouTubeDiagnosticsResponse(**clip_service.container.youtube.diagnostics().to_dict())

    @app.get("/api/sources/{source_id}", response_model=SourceAssetResponse)
    def get_source(source_id: str) -> SourceAssetResponse:
        return clip_service.source_response(source_id)

    @app.post("/api/sources/{source_id}/standard-plan", response_model=StandardPlanResponse)
    def standard_plan(source_id: str, payload: StandardPlanRequest) -> StandardPlanResponse:
        return clip_service.standard_plan(source_id, payload)

    @app.get("/api/sources/{source_id}/media")
    def source_media(source_id: str) -> FileResponse:
        source = clip_service.get_source(source_id)
        return FileResponse(source.path, media_type=source.mime_type, filename=None)

    @app.get("/api/sources/{source_id}/poster")
    def source_poster(source_id: str) -> FileResponse:
        source = clip_service.get_source(source_id)
        if not source.poster_path or not Path(source.poster_path).is_file():
            from dripcut.core.errors import ValidationError

            raise ValidationError("This source has no preview image.")
        return FileResponse(source.poster_path, media_type="image/jpeg")

    @app.post("/api/jobs/clips", response_model=JobResponse, status_code=202)
    def create_clips(payload: RenderRequest) -> JobResponse:
        return clip_service.create_render(payload)

    @app.get("/api/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str) -> JobResponse:
        return clip_service.job_response(job_id)

    @app.get("/api/artifacts/{artifact_id}/media")
    def stream_artifact(artifact_id: str) -> FileResponse:
        artifact = clip_service.get_artifact(artifact_id)
        return FileResponse(artifact.path, media_type=artifact.mime_type, filename=None)

    @app.get("/api/artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str) -> FileResponse:
        artifact = clip_service.get_artifact(artifact_id)
        return FileResponse(artifact.path, media_type=artifact.mime_type, filename=artifact.name)

    return app
