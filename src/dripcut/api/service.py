"""Application service that connects HTTP requests to DripCut's media pipeline."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, BinaryIO, cast
from uuid import uuid4

from dripcut.api.contracts import (
    AIEditActionResponse,
    AIEditPlanRequest,
    AIEditPlanResponse,
    ArtifactResponse,
    ClipSegmentRequest,
    JobResponse,
    ProjectDetailResponse,
    ProjectResponse,
    RenderRequest,
    ScheduleCreateRequest,
    ScheduledPostResponse,
    SchedulePostUpdateRequest,
    ScheduleResponse,
    SocialConnectionResponse,
    SocialMetadataRequest,
    SocialMetadataResponse,
    SourceAssetResponse,
    StandardPlanRequest,
    StandardPlanResponse,
    ThumbnailBriefResponse,
    ThumbnailGenerationResponse,
    ThumbnailRankResponse,
    ThumbnailRequest,
    ViralMomentAnalysisResponse,
    ViralMomentRequest,
    ViralMomentResponse,
)
from dripcut.api.stores import (
    ArtifactRecord,
    ArtifactStore,
    JobStore,
    SourceAssetRecord,
    SourceAssetStore,
)
from dripcut.core.container import ServiceContainer
from dripcut.core.errors import ValidationError
from dripcut.engines.ai.thumbnail import inspect_frame, usable_frames
from dripcut.engines.subtitle.styles import get_preset
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.models.job import Job, JobKind, JobResult
from dripcut.models.project import Project, ProjectSummary
from dripcut.tenancy.models import Principal


class WebClipService:
    """Orchestrate imports, validated segment plans and background renders."""

    def __init__(
        self,
        container: ServiceContainer,
        sources: SourceAssetStore,
        artifacts: ArtifactStore,
        jobs: JobStore,
    ) -> None:
        self.container = container
        self.sources = sources
        self.artifacts = artifacts
        self.jobs = jobs

    def import_upload(self, file_name: str, stream: BinaryIO) -> SourceAssetResponse:
        record = self.sources.save_upload(file_name, stream)
        return self._finish_source(record, project_type="auto_clip")

    def import_youtube(
        self, url: str, *, rights_confirmed: bool = False
    ) -> SourceAssetResponse:
        value = self._require_youtube_permission(url, rights_confirmed)
        project = self._start_youtube_project(value)
        try:
            result = self.container.youtube.import_video(value)
            return self._register_youtube_result(result, value, project=project)
        except Exception:
            project.status = "failed"
            self.container.projects.save(project)
            raise

    def create_youtube_import(
        self,
        url: str,
        *,
        rights_confirmed: bool = False,
        on_success: Callable[[], None] | None = None,
        on_failure: Callable[[], None] | None = None,
        idempotency_key: str | None = None,
    ) -> JobResponse:
        value = self._require_youtube_permission(url, rights_confirmed)
        project = self._start_youtube_project(value)
        job = Job(
            kind=cast(JobKind, JobKind.DOWNLOAD),
            title="Import YouTube video",
            metadata={
                "youtube_video_id": self.container.youtube.video_id(value),
                "project_id": project.id,
                "rights_confirmed": True,
                "rights_confirmed_at": project.content_rights_confirmed_at,
                "import_state": "VALIDATING_URL",
            },
            idempotency_key=idempotency_key,
        )
        project.latest_job_id = job.id
        self.container.projects.save(project)

        def work(active: Job) -> JobResult:
            try:
                def import_progress(progress: float, stage: str) -> None:
                    active.metadata["import_state"] = self._youtube_import_state(stage)
                    active.set_progress(progress * 0.92, stage)

                active.metadata["import_state"] = "FETCHING_METADATA"
                result = self.container.youtube.import_video(
                    value,
                    on_progress=import_progress,
                )
                active.metadata["import_state"] = "VERIFYING"
                active.set_progress(0.94, "Checking downloaded video")
                active.metadata["import_state"] = "REGISTERING"
                response = self._register_youtube_result(result, value, project=project)
                active.metadata.update(
                    {
                        "source_id": response.id,
                        "youtube_strategy": result.strategy,
                        "youtube_format": result.format_id,
                        "youtube_attempts": result.attempts,
                        "youtube_metadata_seconds": result.metadata_seconds,
                        "youtube_download_seconds": result.download_seconds,
                        "youtube_prepare_seconds": result.prepare_seconds,
                    }
                )
                active.metadata["import_state"] = "READY"
                active.set_progress(0.99, "Ready")
                source = self.sources.get(response.id)
                if on_success:
                    on_success()
                return JobResult(
                    outputs=[Path(source.path)],
                    message="YouTube video imported and verified.",
                    data={"source_id": response.id, "project_id": project.id},
                )
            except Exception:
                active.metadata["import_state"] = "FAILED"
                if on_failure:
                    on_failure()
                project.status = "failed"
                self.container.projects.save(project)
                raise

        job.run = work
        submitted = self.jobs.submit(job)
        if submitted is not job:
            self.container.projects.delete(project.id)
            if on_failure:
                on_failure()
            return self.job_response(submitted.id, idempotent_replay=True)
        return self.job_response(job.id)

    @staticmethod
    def _youtube_import_state(stage: str) -> str:
        """Map customer progress labels onto stable acquisition state names."""
        if stage == "Fetching video information":
            return "FETCHING_METADATA"
        if stage == "Checking downloaded video":
            return "VERIFYING"
        if stage == "Ready":
            return "READY"
        return "ACQUIRING"

    def _register_youtube_result(
        self,
        result: Any,
        url: str,
        *,
        project: Project,
    ) -> SourceAssetResponse:
        downloaded = result.path
        metadata = result.metadata
        record = self.sources.save_path(
            downloaded,
            kind="youtube",
            title=metadata.title or downloaded.stem,
        )
        record.channel = metadata.channel
        record.youtube_url = url
        return self._finish_source(record, project=project, project_type="youtube_short")

    def list_projects(
        self,
        *,
        limit: int | None = None,
        project_ids: set[str] | None = None,
    ) -> list[ProjectResponse]:
        summaries = self.container.projects.list_projects(
            limit=limit,
            project_ids=project_ids,
        )
        return [self._project_response(summary) for summary in summaries]

    def create_content_project(
        self,
        title: str,
        *,
        project_type: str,
    ) -> ProjectResponse:
        project = self.container.projects.create(title)
        project.project_type = project_type
        project.status = "draft"
        self.container.projects.save(project)
        return self._project_response(project.summary())

    def get_project(self, project_id: str) -> ProjectDetailResponse:
        project = self.container.projects.load(project_id)
        payload = self._project_response(project.summary()).model_dump()
        source = None
        if project.source_asset_id:
            try:
                source = self.source_response(project.source_asset_id)
            except ValidationError:
                source = None
        return ProjectDetailResponse(**payload, source=source)

    def claim_project(self, project_id: str, user_id: str) -> ProjectResponse:
        """Stamp the informational owner field after tenant registration."""
        project = self.container.projects.load(project_id)
        if project.user_id != user_id:
            project.user_id = user_id
            self.container.projects.save(project)
        return self._project_response(project.summary())

    def rename_project(self, project_id: str, title: str) -> ProjectResponse:
        project = self.container.projects.rename(project_id, title)
        return self._project_response(project.summary())

    def delete_project(self, project_id: str) -> None:
        self.container.projects.delete(project_id, keep_outputs=False)

    def create_thumbnail_candidates(
        self, project_id: str, request: ThumbnailRequest
    ) -> ThumbnailGenerationResponse:
        project = self.container.projects.load(project_id)
        if not project.source_asset_id:
            raise ValidationError("Add a source video before creating thumbnails.")
        source = self.sources.get(project.source_asset_id)
        media = self.container.media.import_file(source.path)
        job_id = str(uuid4())
        output_dir = self.artifacts.output_dir(job_id).parent / "thumbnails"
        output_dir.mkdir(parents=True, exist_ok=True)
        provider = self.container.ai.content_provider
        if provider is None:
            from dripcut.core.errors import AIProviderError

            raise AIProviderError("Editorial AI is not configured.")
        positions = [index / 17 for index in range(1, 17)]
        inspected = []
        for fraction in positions:
            timestamp = max(0.0, media.duration * fraction)
            cached = self.container.media.thumbnail_for(
                media,
                at=timestamp,
                width=1280,
            )
            if cached is None:
                continue
            quality = inspect_frame(cached, timestamp)
            if quality is not None:
                inspected.append(quality)
        finalists = usable_frames(inspected, limit=8)
        if not finalists:
            raise ValidationError("Thumbnail candidates could not be created.")

        transcript = self.container.ai.cached_transcript(Path(source.path))
        prompt_candidates = []
        by_id = {}
        for index, frame in enumerate(finalists, start=1):
            frame_id = f"frame-{index}"
            by_id[frame_id] = frame
            nearby = (
                transcript.text_between(
                    max(0, frame.timestamp - 4), min(transcript.duration, frame.timestamp + 4)
                )
                if transcript
                else ""
            )
            prompt_candidates.append(
                frame.prompt_payload(frame_id=frame_id, nearby_text=nearby)
            )
        ranked = provider.rank_clips(prompt_candidates, platform=request.target)
        order = [item.id for item in ranked.clips if item.id in by_id]
        order.extend(frame_id for frame_id in by_id if frame_id not in order)
        selected_ids = order[:4]
        rank_lookup = {item.id: item for item in ranked.clips}

        records: list[ArtifactRecord] = []
        ranking: list[ThumbnailRankResponse] = []
        for index, frame_id in enumerate(selected_ids, start=1):
            frame = by_id[frame_id]
            target = output_dir / f"{project.slug}-candidate-{index}.jpg"
            shutil.copy2(frame.path, target)
            record = self.artifacts.register_thumbnail(job_id, target, index=index)
            records.append(record)
            model_rank = rank_lookup.get(frame_id)
            ranking.append(
                ThumbnailRankResponse(
                    artifact_id=record.id,
                    score=(model_rank.score if model_rank else round(frame.quality_score)),
                    reason=(
                        model_rank.reason
                        if model_rank
                        else "Selected from image sharpness, exposure, faces, and composition."
                    ),
                )
            )
        brief = provider.generate_thumbnail_brief(
            transcript.text if transcript else source.title,
            prompt=request.prompt,
        )
        project.artifact_ids.extend(
            record.id for record in records if record.id not in project.artifact_ids
        )
        project.notes = brief.model_dump_json()
        self.container.projects.save(project)
        return ThumbnailGenerationResponse(
            candidates=[self._artifact_response(record) for record in records],
            brief=ThumbnailBriefResponse(**brief.model_dump()),
            ranking=ranking,
        )

    def plan_ai_edit(self, request: AIEditPlanRequest) -> AIEditPlanResponse:
        source = self.sources.get(request.source_id)
        provider = self.container.ai.content_provider
        if provider is None:
            from dripcut.core.errors import AIProviderError

            raise AIProviderError("Editorial AI is not configured.")
        planned = provider.plan_edit(request.prompt.strip(), duration=source.duration)
        output_format = {
            "source": "source",
            "16:9": "landscape",
            "9:16": "portrait",
            "1:1": "square",
        }[planned.aspect_ratio]
        clip_duration = min(source.duration, planned.duration)
        if planned.selection == "viral":
            transcript = self.container.ai.transcribe(
                source.path,
                source_asset_id=source.id,
            )
            viral = self.container.ai.find_viral_moments(
                transcript,
                platform=planned.platform,
                target_length=clip_duration,
                max_clips=planned.count,
                metadata={"title": source.title, "kind": source.kind},
            )
            segments = [
                ClipSegmentRequest(
                    id=f"ai-edit-viral-{index}",
                    index=index,
                    start=moment.start,
                    end=moment.end,
                    strategy="ai",
                    score=moment.score / 100,
                    reason=moment.reason,
                )
                for index, moment in enumerate(viral.segments, start=1)
            ]
        else:
            maximum = max(1, int(source.duration // max(clip_duration, 0.001)))
            count = min(planned.count, maximum)
            segments = [
                ClipSegmentRequest(
                    id=f"ai-edit-standard-{index}",
                    index=index,
                    start=(index - 1) * clip_duration,
                    end=min(source.duration, index * clip_duration),
                    strategy="standard",
                )
                for index in range(1, count + 1)
            ]
        if not segments:
            raise ValidationError(
                "AI did not find a usable clip range.",
                hint="Try standard selection or request fewer clips.",
            )
        actions = [
            AIEditActionResponse(kind="platform", label="Destination", value=planned.platform),
            AIEditActionResponse(kind="selection", label="Selection", value=planned.selection),
            AIEditActionResponse(kind="trim", label="Clip duration", value=clip_duration),
            AIEditActionResponse(kind="format", label="Output format", value=output_format),
            AIEditActionResponse(kind="captions", label="Auto captions", value=planned.captions),
            AIEditActionResponse(kind="style", label="Caption style", value=planned.caption_style),
            AIEditActionResponse(kind="reframe", label="Reframe", value=planned.reframe),
        ]
        project = self._project_for_source(source)
        project.project_type = "ai_edit"
        project.output_format = output_format
        project.captions_enabled = planned.captions
        project.platform = planned.platform
        project.notes = request.prompt.strip()
        self.container.projects.save(project)
        return AIEditPlanResponse(
            source_id=source.id,
            summary=(
                f"Create {len(segments)} {clip_duration:.0f}-second {planned.platform} "
                f"clip{'s' if len(segments) != 1 else ''} using {planned.selection} selection."
            ),
            actions=actions,
            segments=segments,
            output_format=output_format,
            auto_captions=planned.captions,
            platform=planned.platform,
            selection=planned.selection,
            count=len(segments),
            duration=clip_duration,
            caption_style=planned.caption_style,
            reframe=planned.reframe,
        )

    def generate_social_metadata(
        self, project_id: str, request: SocialMetadataRequest
    ) -> SocialMetadataResponse:
        project = self.container.projects.load(project_id)
        if not project.source_asset_id:
            raise ValidationError("This project does not have a source video.")
        source = self.sources.get(project.source_asset_id)
        transcript = self.container.ai.transcribe(
            source.path,
            source_asset_id=source.id,
        )
        if request.artifact_id:
            if request.artifact_id not in project.artifact_ids:
                raise ValidationError("That clip is not part of this project.")
            artifact = self.artifacts.get(request.artifact_id)
            if artifact.index and project.plan:
                segment = next(
                    (item for item in project.plan.segments if item.index == artifact.index),
                    None,
                )
                if segment:
                    transcript = transcript.window(segment.start, segment.end)
        provider = self.container.ai.content_provider
        if provider is None:
            from dripcut.core.errors import AIProviderError

            raise AIProviderError("Editorial AI is not configured.")
        package = provider.generate_social_metadata(transcript.text)
        return SocialMetadataResponse(
            project_id=project.id,
            artifact_id=request.artifact_id,
            **package.model_dump(),
        )

    def find_viral_moments(
        self, source_id: str, request: ViralMomentRequest
    ) -> ViralMomentAnalysisResponse:
        source = self.sources.get(source_id)
        transcript = self.container.ai.transcribe(
            source.path,
            source_asset_id=source.id,
        )
        provider = self.container.ai.content_provider
        if provider is None:
            from dripcut.core.errors import AIProviderError

            raise AIProviderError("Editorial AI is not configured.")
        analysis = self.container.ai.find_viral_moments(
            transcript,
            platform=request.platform,
            target_length=request.target_length,
            max_clips=request.max_clips,
            metadata={"title": source.title, "kind": source.kind},
        )
        return ViralMomentAnalysisResponse(
            source_id=source.id,
            platform=request.platform,
            model=provider.model,
            analysis_version=str(getattr(provider, "analysis_version", "viral-v1")),
            segments=[
                ViralMomentResponse(
                    id=f"viral-{index}",
                    start=moment.start,
                    end=moment.end,
                    duration=moment.duration,
                    score=moment.score,
                    hook_score=moment.hook_score,
                    retention_score=moment.retention_score,
                    shareability_score=moment.shareability_score,
                    platform=moment.platform,
                    reason=moment.reason,
                    hook=moment.hook,
                )
                for index, moment in enumerate(analysis.segments, start=1)
            ],
        )

    def social_connections(
        self, principal: Principal | None = None
    ) -> list[SocialConnectionResponse]:
        return [
            SocialConnectionResponse(**asdict(connection))
            for connection in self.container.social.connections(principal)
        ]

    def create_schedule(
        self, request: ScheduleCreateRequest, principal: Principal | None = None
    ) -> ScheduleResponse:
        project = self.container.projects.load(request.project_id)
        archive = self._project_archive(project)
        schedule = self.container.social.create_schedule_for_archive(
            archive=Path(archive.path),
            project_id=project.id,
            platforms=list(request.platforms),
            interval_minutes=request.interval_minutes,
            start_at=request.start_at,
            caption=request.caption,
            principal=principal,
        )
        project.scheduling_status = "draft"
        self.container.projects.save(project)
        ready = all(
            connection.connected
            for platform, connection in self.container.social.connection_map(principal).items()
            if platform in request.platforms
        )
        return self._schedule_response(schedule, publish_ready=ready)

    def get_schedule(
        self, schedule_id: str, principal: Principal | None = None
    ) -> ScheduleResponse:
        schedule = self.container.social.get_schedule(schedule_id, principal)
        ready = all(post.status != "draft" for post in schedule.posts)
        return self._schedule_response(schedule, publish_ready=ready)

    def latest_schedule(
        self, principal: Principal | None = None
    ) -> ScheduleResponse | None:
        schedule = self.container.social.latest_schedule(principal)
        if schedule is None:
            return None
        ready = all(post.status != "draft" for post in schedule.posts)
        return self._schedule_response(schedule, publish_ready=ready)

    def update_scheduled_post(
        self,
        schedule_id: str,
        post_id: str,
        request: SchedulePostUpdateRequest,
        principal: Principal | None = None,
    ) -> ScheduleResponse:
        schedule = self.container.social.update_scheduled_post(
            schedule_id,
            post_id,
            publish_at=request.publish_at,
            caption=request.caption,
            principal=principal,
        )
        ready = all(post.status != "draft" for post in schedule.posts)
        return self._schedule_response(schedule, publish_ready=ready)

    def get_source(self, source_id: str) -> SourceAssetRecord:
        return self.sources.get(source_id)

    def source_response(self, source_id: str) -> SourceAssetResponse:
        return self._source_response(self.sources.get(source_id))

    def standard_plan(self, source_id: str, request: StandardPlanRequest) -> StandardPlanResponse:
        source = self.sources.get(source_id)
        maximum = max(0, int(source.duration // request.duration))
        count = maximum if request.count == "max" else min(maximum, max(0, request.count))
        segments = [
            ClipSegmentRequest(
                id=f"standard-segment-{index + 1}",
                index=index + 1,
                start=round(index * request.duration, 3),
                end=round((index + 1) * request.duration, 3),
            )
            for index in range(count)
        ]
        return StandardPlanResponse(
            duration=request.duration,
            requested_count=count,
            max_count=maximum,
            segments=segments,
        )

    def create_render(
        self,
        request: RenderRequest,
        *,
        on_success: Callable[[], None] | None = None,
        on_failure: Callable[[], None] | None = None,
        idempotency_key: str | None = None,
    ) -> JobResponse:
        source = self.sources.get(request.source_id)
        segments = self._validated_segments(request.segments, source.duration)
        plan = SplitPlan(
            source=Path(source.path),
            mode=cast(
                SplitMode,
                SplitMode.FIXED
                if all(item.strategy == "standard" for item in request.segments)
                else SplitMode.AI_HIGHLIGHT,
            ),
            segments=tuple(segments),
            parameters={"selection_strategy": request.segments[0].strategy},
        )
        accurate = not self._can_stream_copy_plan(source, segments, request)
        project = self._project_for_source(source)
        project.plan = plan
        project.status = "processing"
        project.platform = self._platform_label(request.platforms)
        project.output_format = request.output_format
        project.captions_enabled = request.auto_captions
        caption_presets = {
            "clean": "Clean",
            "dynamic": "Signal",
            "minimal": "Documentary",
            "bold": "Punch",
        }
        project.caption_style = get_preset(caption_presets[request.caption_style])

        job = Job(
            kind=cast(JobKind, JobKind.SPLIT),
            title=f"Create {len(segments)} clips from {source.title}",
            source=Path(source.path),
            metadata={
                "source_id": source.id,
                "project_id": project.id,
                "segment_count": len(segments),
                "output_format": request.output_format,
                "captions_enabled": request.auto_captions,
                "caption_style": request.caption_style,
            },
            idempotency_key=idempotency_key,
        )
        project.latest_job_id = job.id
        self.container.projects.save(project)

        def work(active: Job) -> JobResult:
            try:
                transcript = None
                output_dir = self.artifacts.output_dir(active.id)
                timings: dict[str, float | bool] = {}
                subtitle_paths: list[Path | None] | None = None
                caption_overlays: list[list[tuple[Path, float, float]]] | None = None
                caption_asset_dirs: list[Path] = []

                def transcribe(progress_callback) -> Any:
                    started = time.monotonic()
                    result = self.container.ai.transcribe(
                        source.path,
                        source_asset_id=source.id,
                        on_progress=progress_callback,
                        cancel_token=active.cancel_token,
                    )
                    timings["transcription_seconds"] = round(
                        time.monotonic() - started, 3
                    )
                    timings["transcript_cache_hit"] = bool(
                        result.metadata.get("cache_hit", False)
                    )
                    timings["provider_api_called"] = bool(
                        result.metadata.get("provider_api_seconds") is not None
                        and not result.metadata.get("cache_hit", False)
                    )
                    if not timings["transcript_cache_hit"]:
                        for key in (
                            "audio_extraction_seconds",
                            "provider_api_seconds",
                            "transcript_normalization_seconds",
                        ):
                            value = result.metadata.get(key)
                            if isinstance(value, int | float):
                                timings[key] = round(float(value), 3)
                    return result

                def render(progress_callback) -> list[Path]:
                    started = time.monotonic()
                    try:
                        rendered = self.container.split.render(
                            plan,
                            output_dir,
                            name_pattern="clip-{index:02d}",
                            container=request.container,
                            accurate=accurate,
                            output_format=request.output_format,
                            portrait_mode=request.portrait_mode,
                            on_progress=progress_callback,
                            cancel_token=active.cancel_token,
                            stem=source.title,
                            subtitle_paths=subtitle_paths,
                            caption_overlays=caption_overlays,
                        )
                    finally:
                        for subtitle_path in subtitle_paths or []:
                            if subtitle_path is not None:
                                subtitle_path.unlink(missing_ok=True)
                        for asset_dir in caption_asset_dirs:
                            shutil.rmtree(asset_dir, ignore_errors=True)
                    timings["clip_render_seconds"] = round(
                        time.monotonic() - started, 3
                    )
                    return rendered

                provider = self.container.ai.active_transcription_provider
                native_subtitles = self.container.resolve("ffmpeg").has_filter(
                    "subtitles"
                )
                single_pass_captions = bool(
                    request.auto_captions
                    and (native_subtitles or self.container.subtitles.can_overlay())
                )
                if single_pass_captions:
                    transcript = transcribe(
                        lambda value, stage: active.set_progress(
                            value * 0.28, f"Transcribing · {stage}"
                        )
                    )
                    active.set_progress(0.29, "Adding captions")
                    preparation_started = time.monotonic()
                    video_size = {
                        "portrait": (1080, 1920),
                        "square": (1080, 1080),
                        "landscape": (1920, 1080),
                    }.get(request.output_format, (source.width, source.height))
                    if native_subtitles:
                        subtitle_paths = []
                    else:
                        caption_overlays = []
                    used_segments = 0
                    for segment in segments:
                        clip_transcript = transcript.window(segment.start, segment.end)
                        if clip_transcript.is_empty:
                            if subtitle_paths is not None:
                                subtitle_paths.append(None)
                            if caption_overlays is not None:
                                caption_overlays.append([])
                            continue
                        if subtitle_paths is not None:
                            subtitle_path = output_dir / f".clip-{segment.index:02d}.ass"
                            self.container.subtitles.write(
                                clip_transcript,
                                subtitle_path,
                                style=project.caption_style,
                                subtitle_format="ass",
                                video_size=video_size,
                            )
                            subtitle_paths.append(subtitle_path)
                        elif caption_overlays is not None:
                            asset_dir = output_dir / f".captions-{segment.index:02d}"
                            caption_asset_dirs.append(asset_dir)
                            caption_overlays.append(
                                self.container.subtitles.prepare_overlays(
                                    clip_transcript,
                                    asset_dir,
                                    style=project.caption_style,
                                    video_size=video_size,
                                )
                            )
                        used_segments += len(clip_transcript.segments)
                    timings["subtitle_preparation_seconds"] = round(
                        time.monotonic() - preparation_started, 3
                    )
                    timings["clip_transcript_segments"] = float(used_segments)
                    timings["single_pass_caption_render"] = True
                    timings["caption_overlay_fallback"] = not native_subtitles
                    outputs = render(
                        lambda value, stage: active.set_progress(
                            0.30 + value * 0.63, f"Creating clips · {stage}"
                        )
                    )
                    timings["final_render_seconds"] = timings["clip_render_seconds"]
                    timings["caption_encoding_in_final_pass"] = True
                elif request.auto_captions and provider.remote:
                    progress_state = {"transcription": 0.0, "render": 0.0}
                    progress_lock = threading.Lock()

                    def concurrent_progress(kind: str, value: float, stage: str) -> None:
                        with progress_lock:
                            progress_state[kind] = max(progress_state[kind], value)
                            combined = (
                                progress_state["transcription"] * 0.24
                                + progress_state["render"] * 0.52
                            )
                            phase = (
                                "Transcribing"
                                if kind == "transcription"
                                else "Creating clips"
                            )
                            active.set_progress(
                                min(0.76, combined), f"{phase} · {stage}"
                            )

                    with ThreadPoolExecutor(
                        max_workers=2, thread_name_prefix="dripcut-pipeline"
                    ) as executor:
                        transcript_future = executor.submit(
                            transcribe,
                            lambda value, stage: concurrent_progress(
                                "transcription", value, stage
                            ),
                        )
                        outputs = render(
                            lambda value, stage: concurrent_progress(
                                "render", value, stage
                            )
                        )
                        transcript = transcript_future.result()
                else:
                    if request.auto_captions:
                        transcript = transcribe(
                            lambda value, stage: active.set_progress(
                                value * 0.28, f"Transcribing · {stage}"
                            )
                        )
                    render_start = 0.28 if transcript is not None else 0.0
                    render_share = 0.48 if transcript is not None else 0.82
                    outputs = render(
                        lambda value, stage: active.set_progress(
                            render_start + value * render_share,
                            f"Creating clips · {stage}",
                        )
                    )

                if transcript is not None:
                    cache_path = transcript.metadata.get("cache_path")
                    if cache_path:
                        project.transcript_file = Path(str(cache_path))
                if transcript is not None and not single_pass_captions:
                    caption_started = time.monotonic()
                    outputs = self._burn_captions(
                        active,
                        outputs,
                        segments,
                        transcript,
                        project,
                        timings,
                    )
                    timings["caption_render_seconds"] = round(
                        time.monotonic() - caption_started, 3
                    )

                active.set_progress(0.94, "Finalizing downloads")
                clips = [
                    self.artifacts.register_clip(
                        active.id,
                        path,
                        index=segment.index,
                        duration=segment.duration,
                        output_format=request.output_format,
                        captions_enabled=request.auto_captions,
                    )
                    for path, segment in zip(outputs, segments, strict=True)
                ]
                active.set_progress(0.98, "Finalizing ZIP")
                archive_started = time.monotonic()
                archive = self.artifacts.create_zip(
                    active.id, clips, source_title=source.title
                )
                timings["zip_seconds"] = round(time.monotonic() - archive_started, 3)
                active.metadata["pipeline_timings"] = timings
                project.outputs = [*outputs, Path(archive.path)]
                project.artifact_ids = [item.id for item in [*clips, archive]]
                project.status = "completed"
                self.container.projects.save(project)
                if on_success:
                    on_success()
                return JobResult(
                    outputs=[*outputs, Path(archive.path)],
                    message=f"Created {len(outputs)} clips and one ZIP archive.",
                    data={
                        "source_id": source.id,
                        "project_id": project.id,
                        "pipeline_timings": timings,
                    },
                )
            except Exception:
                if on_failure:
                    on_failure()
                project.status = "failed"
                self.container.projects.save(project)
                raise

        job.run = work
        submitted = self.jobs.submit(job)
        if submitted is not job:
            project.latest_job_id = submitted.id
            project.status = "processing" if submitted.is_active else submitted.status.value
            self.container.projects.save(project)
            if on_failure:
                on_failure()
            return self.job_response(submitted.id, idempotent_replay=True)
        return self.job_response(job.id)

    def _can_stream_copy_plan(
        self,
        source: SourceAssetRecord,
        segments: list[Segment],
        request: RenderRequest,
    ) -> bool:
        """Use stream copy only when every boundary lands on a real keyframe."""
        if (
            not request.fast_mode
            or request.auto_captions
            or request.output_format != "source"
        ):
            return False
        info = self.container.media.import_file(source.path)
        video = self.container.resolve("video_engine")
        if not video.can_stream_copy(info, request.container):
            return False
        keyframes = self.container.resolve("probe").keyframe_times(source.path)
        if not keyframes:
            return False
        return all(
            segment.start <= 0.05 or any(abs(keyframe - segment.start) <= 0.08 for keyframe in keyframes)
            for segment in segments
        )

    def job_response(self, job_id: str, *, idempotent_replay: bool = False) -> JobResponse:
        job = self.jobs.get(job_id)
        if job is None:
            raise ValidationError("That render job could not be found.", hint="Start the render again.")
        if job.status.value in {"failed", "cancelled"}:
            self.artifacts.discover_clips(job.id)
        records = self.artifacts.list_for_job(job.id)
        artifacts = [self._artifact_response(item) for item in records]
        zip_artifact = next((item for item in artifacts if item.kind == "zip"), None)
        return JobResponse(
            id=job.id,
            source_id=str(job.metadata.get("source_id", "")),
            project_id=str(job.metadata.get("project_id", "")),
            status=job.status.value,
            progress=round(job.progress, 4),
            percent=job.percent,
            stage=job.stage or "Queued",
            elapsed=round(job.elapsed, 3),
            error=job.error,
            error_code=str(job.metadata.get("error_code") or "") or None,
            hint=job.hint,
            retryable=bool(job.metadata.get("retryable", False)),
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            idempotent_replay=idempotent_replay,
            idempotency_key=job.idempotency_key,
            artifacts=artifacts,
            zip_artifact=zip_artifact,
        )

    def idempotent_job(self, key: str) -> JobResponse | None:
        """Return a prior request result before repeating quota or project work."""
        job = self.jobs.get_by_idempotency_key(key)
        return self.job_response(job.id, idempotent_replay=True) if job else None

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        return self.artifacts.get(artifact_id)

    def _project_archive(self, project: Project) -> ArtifactRecord:
        for artifact_id in reversed(project.artifact_ids):
            try:
                artifact = self.artifacts.get(artifact_id)
            except ValidationError:
                continue
            if artifact.kind == "zip":
                return artifact
        raise ValidationError("Render a project ZIP before creating a schedule.")

    @staticmethod
    def _schedule_response(schedule: Any, *, publish_ready: bool) -> ScheduleResponse:
        return ScheduleResponse(
            id=schedule.id,
            project_id=schedule.project_id,
            archive_name=schedule.archive_name,
            created_at=schedule.created_at,
            posts=[ScheduledPostResponse(**asdict(post)) for post in schedule.posts],
            publish_ready=publish_ready,
        )

    def _finish_source(
        self,
        record: SourceAssetRecord,
        *,
        project: Project | None = None,
        project_type: str,
    ) -> SourceAssetResponse:
        try:
            info = self.container.media.import_file(record.path)
        except Exception:
            shutil.rmtree(Path(record.path).parent, ignore_errors=True)
            raise
        if not info.has_video:
            shutil.rmtree(Path(record.path).parent, ignore_errors=True)
            raise ValidationError("This file has no video track.", hint="Choose a video file.")
        container_names = {value.strip().lower() for value in info.container.split(",")}
        supported_containers = {
            "mov",
            "mp4",
            "m4a",
            "3gp",
            "3g2",
            "mj2",
            "matroska",
            "webm",
        }
        if not container_names.intersection(supported_containers):
            shutil.rmtree(Path(record.path).parent, ignore_errors=True)
            raise ValidationError(
                "This video container is not supported.",
                hint="Upload an MP4, MOV, WebM, or Matroska video.",
            )
        max_bytes = int(self.container.settings.server.max_upload_mb) * 1024 * 1024
        if info.size_bytes > max_bytes:
            shutil.rmtree(Path(record.path).parent, ignore_errors=True)
            raise ValidationError(
                "This video is larger than the upload limit.",
                hint=f"Choose a video smaller than {max_bytes // 1024 // 1024} MB.",
            )
        max_duration = float(os.environ.get("DRIPCUT_MAX_VIDEO_DURATION_SECONDS", "14400"))
        if info.duration <= 0 or info.duration > max_duration:
            shutil.rmtree(Path(record.path).parent, ignore_errors=True)
            raise ValidationError(
                "This video's duration is outside the supported range.",
                hint=f"Choose a video shorter than {max_duration / 3600:g} hours.",
            )
        width, height = info.video.display_resolution
        record.name = info.name
        record.duration = info.duration
        record.width = width
        record.height = height
        record.size_bytes = info.size_bytes
        if "webm" in container_names:
            record.mime_type = "video/webm"
        elif "matroska" in container_names:
            record.mime_type = "video/x-matroska"
        elif "mov" in container_names and "mp4" not in container_names:
            record.mime_type = "video/quicktime"
        else:
            record.mime_type = "video/mp4"
        thumbnail = self.container.media.thumbnail_for(info)
        if thumbnail:
            poster = Path(record.path).parent / "poster.jpg"
            shutil.copy2(thumbnail, poster)
            record.poster_path = str(poster)
        resolved_project = project or self.container.projects.create(record.title, info)
        resolved_project.name = record.title
        resolved_project.source_path = Path(record.path)
        resolved_project.duration = info.duration
        resolved_project.thumbnail = Path(record.poster_path) if record.poster_path else None
        resolved_project.project_type = project_type
        resolved_project.source_asset_id = record.id
        resolved_project.status = "ready"
        record.project_id = resolved_project.id
        self.container.projects.save(resolved_project)
        self.sources.update(record)
        return self._source_response(record)

    def _require_youtube_permission(self, url: str, confirmed: bool) -> str:
        value = self.container.youtube.validate_url(url)
        if not confirmed:
            raise ValidationError(
                "Confirm that you have permission to use this video.",
                hint=(
                    "Only import videos you own, license, or have permission to edit."
                ),
            )
        return value

    def _start_youtube_project(self, url: str) -> Project:
        video_id = self.container.youtube.video_id(url)
        project = self.container.projects.create(f"YouTube {video_id}")
        project.project_type = "youtube_short"
        project.status = "importing"
        project.content_rights_confirmed = True
        project.content_rights_confirmed_at = time.time()
        project.content_rights_source = url
        self.container.projects.save(project)
        return project

    def _project_for_source(self, source: SourceAssetRecord) -> Project:
        if source.project_id:
            return self.container.projects.load(source.project_id)
        info = self.container.media.import_file(source.path)
        project = self.container.projects.create(source.title, info)
        project.source_asset_id = source.id
        project.status = "ready"
        source.project_id = project.id
        self.sources.update(source)
        self.container.projects.save(project)
        return project

    def _burn_captions(
        self,
        active: Job,
        outputs: list[Path],
        segments: list[Segment],
        transcript: Any,
        project: Project,
        pipeline_timings: dict[str, float | bool],
    ) -> list[Path]:
        captioned: list[Path] = []
        subtitle_preparation = 0.0
        caption_encoding = 0.0
        total = max(1, len(outputs))
        for position, (path, segment) in enumerate(
            zip(outputs, segments, strict=True), start=1
        ):
            media = self.container.media.import_file(path)
            temporary = path.with_name(f"{path.stem}-captioned{path.suffix}")

            def progress(value: float, stage: str, index: int = position) -> None:
                base = 0.76 + ((index - 1) / total) * 0.17
                active.set_progress(
                    min(0.93, base + (value / total) * 0.17),
                    f"Captions {index} of {total} · {stage}",
                )

            clip_timings: dict[str, float] = {}
            self.container.subtitles.burn(
                media,
                transcript,
                temporary,
                style=project.caption_style,
                offset=segment.start,
                on_progress=progress,
                cancel_token=active.cancel_token,
                timings=clip_timings,
            )
            subtitle_preparation += clip_timings.get("subtitle_preparation_seconds", 0.0)
            caption_encoding += clip_timings.get("caption_encoding_seconds", 0.0)
            path.unlink(missing_ok=True)
            temporary.replace(path)
            captioned.append(path)
        pipeline_timings["subtitle_preparation_seconds"] = round(
            subtitle_preparation, 3
        )
        pipeline_timings["caption_encoding_seconds"] = round(caption_encoding, 3)
        return captioned

    @staticmethod
    def _platform_label(platforms: Sequence[str]) -> str:
        unique = set(platforms)
        if unique == {"youtube", "instagram"}:
            return "both"
        return next(iter(unique), "both")

    def _project_response(self, summary: ProjectSummary) -> ProjectResponse:
        workflow = {
            "ai_edit": "ai-editor",
            "script": "script",
        }.get(summary.project_type, "auto-clip")
        thumbnail_url = (
            f"/api/sources/{summary.source_asset_id}/poster"
            if summary.thumbnail and summary.source_asset_id
            else None
        )
        download_artifact_id = None
        for artifact_id in reversed(summary.artifact_ids):
            try:
                if self.artifacts.get(artifact_id).kind == "zip":
                    download_artifact_id = artifact_id
                    break
            except ValidationError:
                continue
        return ProjectResponse(
            id=summary.id,
            title=summary.name,
            project_type=summary.project_type,
            source_asset_id=summary.source_asset_id,
            thumbnail_url=thumbnail_url,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            status=summary.status,
            platform=summary.platform,
            output_format=summary.output_format,
            clip_count=summary.clip_count,
            artifact_ids=list(summary.artifact_ids),
            download_artifact_id=download_artifact_id,
            scheduling_status=summary.scheduling_status,
            latest_job_id=summary.latest_job_id,
            captions_enabled=summary.captions_enabled,
            workflow_route=workflow,
        )

    @staticmethod
    def _youtube_metadata(downloaded: Path) -> dict[str, Any]:
        sidecars = [downloaded.with_suffix(".info.json"), *downloaded.parent.glob("*.info.json")]
        for sidecar in sidecars:
            if sidecar.is_file():
                try:
                    return json.loads(sidecar.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
        return {}

    @staticmethod
    def _validated_segments(requests: list[ClipSegmentRequest], source_duration: float) -> list[Segment]:
        ordered = sorted(requests, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(1, len(ordered) + 1)):
            raise ValidationError("Clip numbers must start at 1 and stay consecutive.")
        previous_end = 0.0
        segments: list[Segment] = []
        for item in ordered:
            if item.end <= item.start:
                raise ValidationError(f"Clip {item.index} has an invalid time range.")
            if item.end > source_duration + 0.05:
                raise ValidationError(f"Clip {item.index} extends beyond the source video.")
            if item.start < previous_end - 0.01:
                raise ValidationError("Clip ranges cannot overlap.")
            previous_end = item.end
            segments.append(
                Segment(
                    id=item.id,
                    index=item.index,
                    start=item.start,
                    end=item.end,
                    source=cast(
                        SegmentSource,
                        SegmentSource.FIXED if item.strategy == "standard" else SegmentSource.AI,
                    ),
                )
            )
        return segments

    def _source_response(self, record: SourceAssetRecord) -> SourceAssetResponse:
        media_url = self.sources.signed_url(record) or f"/api/sources/{record.id}/media"
        poster_url = None
        if record.poster_path or record.poster_storage_key:
            poster_url = self.sources.signed_url(record, poster=True) or f"/api/sources/{record.id}/poster"
        return SourceAssetResponse(
            id=record.id,
            kind=record.kind,
            name=record.name,
            title=record.title,
            duration=record.duration,
            width=record.width,
            height=record.height,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            channel=record.channel,
            youtube_url=record.youtube_url,
            project_id=record.project_id,
            media_url=media_url,
            poster_url=poster_url,
        )

    def _artifact_response(self, record: ArtifactRecord) -> ArtifactResponse:
        stream_url = None
        if record.kind in {"clip", "thumbnail"}:
            stream_url = self.artifacts.signed_url(record) or f"/api/artifacts/{record.id}/media"
        download_url = self.artifacts.signed_url(record, download=True) or f"/api/artifacts/{record.id}/download"
        return ArtifactResponse(
            id=record.id,
            job_id=record.job_id,
            kind=record.kind,
            name=record.name,
            size_bytes=record.size_bytes,
            mime_type=record.mime_type,
            index=record.index,
            duration=record.duration,
            output_format=record.output_format,
            captions_enabled=record.captions_enabled,
            stream_url=stream_url,
            download_url=download_url,
        )
