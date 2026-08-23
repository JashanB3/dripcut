"""Application composition root.

Everything is constructed exactly once, here, and handed to the container. This is
the only module that knows the full object graph; adding a service means editing one
function rather than hunting for import sites.
"""

from __future__ import annotations

from dripcut.core.config import Settings, load_settings
from dripcut.core.container import ServiceContainer
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger, setup_logging
from dripcut.core.paths import AppPaths, app_paths
from dripcut.engines.ai.analysis import AnalysisEngine
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.transcription import TranscriptionEngine
from dripcut.engines.export.queue import JobQueue
from dripcut.engines.ffmpeg.probe import MediaProbe
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.engines.split.registry import build_default_registry
from dripcut.engines.subtitle.generator import SubtitleEngine
from dripcut.engines.video.engine import VideoEngine
from dripcut.plugins.api import PluginContext
from dripcut.plugins.loader import PluginRegistry
from dripcut.services.ai_service import AIService
from dripcut.services.export_service import ExportService
from dripcut.services.media_service import MediaService
from dripcut.services.notification_service import NotificationService
from dripcut.services.project_service import ProjectService
from dripcut.services.social_service import SocialScheduleService
from dripcut.services.split_service import SplitService
from dripcut.services.subtitle_service import SubtitleService
from dripcut.services.youtube_service import YouTubeService

__all__ = ["build_container", "AppContext"]

_log = get_logger("core.bootstrap")

AppContext = ServiceContainer  # readable alias used by the UI layer


def build_container(
    settings: Settings | None = None,
    *,
    paths: AppPaths | None = None,
    load_plugins: bool = True,
) -> ServiceContainer:
    """Construct and wire every DripCut service.

    Args:
        settings: Pre-loaded settings; loaded from disk when omitted.
        paths: Application paths; resolved from the platform when omitted.
        load_plugins: Discover and activate plugins (off in most tests).

    Returns:
        A fully wired :class:`ServiceContainer`.
    """
    resolved_paths = paths or app_paths()
    resolved_settings = settings or load_settings(resolved_paths.config_file)
    setup_logging(resolved_settings.log_level)

    container = ServiceContainer()
    events = EventBus()

    container.register_instance(container.KEY_SETTINGS, resolved_settings)
    container.register_instance(container.KEY_EVENTS, events)
    container.register_instance(container.KEY_PATHS, resolved_paths)

    # --- FFmpeg layer -------------------------------------------------------
    runner = FFmpegRunner(
        resolved_settings.ffmpeg_path, hardware_accel=resolved_settings.video.hardware_accel
    )
    probe = MediaProbe(resolved_settings.ffprobe_path)
    container.register_instance(container.KEY_FFMPEG, runner)
    container.register_instance(container.KEY_PROBE, probe)

    # --- engines ------------------------------------------------------------
    video_engine = VideoEngine(runner, probe)
    subtitle_engine = SubtitleEngine()
    split_registry = build_default_registry()
    container.register_instance("video_engine", video_engine)
    container.register_instance("subtitle_engine", subtitle_engine)
    container.register_instance("split_registry", split_registry)

    llm = OllamaClient(
        resolved_settings.ai.ollama_host,
        model=resolved_settings.ai.ollama_model,
        timeout=resolved_settings.ai.ollama_timeout_s,
        num_ctx=resolved_settings.ai.ollama_num_ctx,
        temperature=resolved_settings.ai.ollama_temperature,
    )
    transcription = TranscriptionEngine(
        runner,
        model_name=resolved_settings.ai.whisper_model,
        compute_type=resolved_settings.ai.whisper_compute_type,
        device=resolved_settings.ai.whisper_device,
        beam_size=resolved_settings.ai.whisper_beam_size,
        vad_filter=resolved_settings.ai.whisper_vad_filter,
        language=resolved_settings.ai.whisper_language,
        download_root=resolved_paths.models,
    )
    analysis = AnalysisEngine(llm, enabled=resolved_settings.ai.enable_ai)
    container.register_instance("llm", llm)
    container.register_instance("transcription_engine", transcription)
    container.register_instance("analysis_engine", analysis)

    queue = JobQueue(
        events,
        max_workers=resolved_settings.video.max_workers,
        history_file=resolved_paths.history_file,
    )
    container.register_instance("queue", queue)

    # --- services -----------------------------------------------------------
    notifications = NotificationService(events)
    ai_service = AIService(transcription, analysis, llm, events, resolved_settings, resolved_paths)
    media_service = MediaService(probe, video_engine, events, resolved_settings, resolved_paths)
    youtube_service = YouTubeService(resolved_paths)
    social_service = SocialScheduleService(resolved_paths)
    project_service = ProjectService(resolved_paths, events)
    split_service = SplitService(
        split_registry, video_engine, runner, events, resolved_settings, ai_service
    )
    subtitle_service = SubtitleService(subtitle_engine, video_engine, resolved_settings)
    export_service = ExportService(queue, video_engine, split_service, resolved_settings)

    container.register_instance(container.KEY_NOTIFICATIONS, notifications)
    container.register_instance(container.KEY_AI, ai_service)
    container.register_instance(container.KEY_MEDIA, media_service)
    container.register_instance(container.KEY_YOUTUBE, youtube_service)
    container.register_instance(container.KEY_SOCIAL, social_service)
    container.register_instance(container.KEY_PROJECTS, project_service)
    container.register_instance(container.KEY_SPLIT, split_service)
    container.register_instance(container.KEY_SUBTITLES, subtitle_service)
    container.register_instance(container.KEY_EXPORT, export_service)
    container.register_instance(container.KEY_VIDEO, video_engine)

    # --- plugins ------------------------------------------------------------
    plugin_context = PluginContext(
        container=container,
        settings=resolved_settings,
        events=events,
        output_dir=resolved_settings.output_path,
        data_dir=resolved_paths.plugins,
    )
    plugins = PluginRegistry(plugin_context, events)
    container.register_instance(container.KEY_PLUGINS, plugins)
    if load_plugins:
        plugins.discover(disabled=resolved_settings.disabled_plugins)

    events.publish(EventName.APP_READY, services=len(container.keys()))
    _log.debug("container ready with %d services", len(container.keys()))
    return container
