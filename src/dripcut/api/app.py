"""FastAPI routes for source import, background rendering and downloads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from dripcut.api.contracts import (
    AIEditPlanRequest,
    AIEditPlanResponse,
    ArtifactResponse,
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DripCutError)
    async def dripcut_error(_: Request, error: DripCutError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                message=error.message,
                hint=error.hint,
                code=getattr(error, "code", None),
            ).model_dump(exclude_none=True),
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
