"""Split orchestration: plan, then render, as two separate steps."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from dripcut.core.config import Settings
from dripcut.core.errors import ValidationError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.engines.split.base import SplitContext
from dripcut.engines.split.registry import SplitRegistry
from dripcut.engines.video.encode import EncodeSettings, Quality
from dripcut.engines.video.engine import VideoEngine
from dripcut.models.clip import Segment, SplitMode, SplitPlan
from dripcut.models.media import MediaInfo
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir, safe_filename

__all__ = ["SplitService"]

_log = get_logger("services.split")

ProgressFn = Callable[[float, str], None]


class SplitService:
    """Plans splits with the strategy registry and renders the resulting segments."""

    def __init__(
        self,
        registry: SplitRegistry,
        video: VideoEngine,
        runner: FFmpegRunner,
        events: EventBus,
        settings: Settings,
        ai_service: Any = None,
    ) -> None:
        self.registry = registry
        self.video = video
        self.runner = runner
        self.events = events
        self.settings = settings
        self.ai_service = ai_service

    # ---------------------------------------------------------------------- plan

    def default_parameters(self, mode: SplitMode | str) -> dict[str, Any]:
        """Sensible starting values for a mode, taken from settings."""
        video = self.settings.video
        table: dict[SplitMode, dict[str, Any]] = {
            SplitMode.FIXED: {"clip_length": 30.0, "overlap": 0.0, "drop_last_shorter_than": 2.0},
            SplitMode.SCENE: {"threshold": video.scene_threshold, "min_scene_seconds": 1.5},
            SplitMode.SILENCE: {
                "threshold_db": video.silence_threshold_db,
                "min_silence": video.silence_min_duration,
                "pad": 0.15,
                "keep_silence_as_clips": False,
            },
            SplitMode.TIMESTAMPS: {"timestamps": "", "ranges": "", "titles": ""},
            SplitMode.CHAPTERS: {"use_titles": True},
            SplitMode.AI_HIGHLIGHT: {
                "target_length": 45.0,
                "max_clips": 8,
                "focus": "auto",
                "min_score": 0.35,
                "pad_before": 0.35,
                "pad_after": 0.6,
            },
        }
        return dict(table.get(SplitMode(str(mode)), {}))

    def plan(
        self,
        media: MediaInfo,
        mode: SplitMode | str,
        parameters: dict[str, Any] | None = None,
        *,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> SplitPlan:
        """Compute a split plan without rendering anything."""
        strategy = self.registry.get(mode)
        merged = {**self.default_parameters(mode), **(parameters or {})}
        if strategy.requires_ai and (self.ai_service is None or not self.ai_service.enabled):
            raise ValidationError(
                "This mode needs AI features, which are switched off.",
                hint="Turn them on in Settings, or pick another split mode.",
            )
        context = SplitContext(
            media=media,
            parameters=merged,
            cancel_token=cancel_token,
            on_progress=on_progress,
            services={"runner": self.runner, "ai": self.ai_service, "video": self.video},
        )
        plan = strategy.plan(context)
        self.events.publish(
            EventName.SPLIT_PLANNED,
            path=str(media.path),
            mode=plan.mode.value,
            count=plan.count,
        )
        _log.info("planned %d clips from %s using %s", plan.count, media.name, plan.mode.value)
        return plan

    # -------------------------------------------------------------------- render

    def render(
        self,
        plan: SplitPlan,
        destination: Path,
        *,
        name_pattern: str = "{stem}-{index:03d}",
        container: str = "mp4",
        quality: Quality = Quality.BALANCED,
        accurate: bool = True,
        resize: tuple[int | None, int | None] | None = None,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
        stem: str | None = None,
    ) -> list[Path]:
        """Render every segment in a plan.

        Segments render sequentially. Two FFmpeg processes fighting over the same
        source file are slower than one on a laptop SSD, and sequential rendering
        gives honest per-clip progress.
        """
        if plan.count == 0:
            raise ValidationError("There is nothing in this plan to render.")
        output_dir = ensure_dir(destination)
        base_stem = safe_filename(stem or plan.source.stem)
        settings = EncodeSettings.for_container(container, quality=quality)
        outputs: list[Path] = []
        total = plan.count

        for position, segment in enumerate(plan.segments, start=1):
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            filename = segment.output_name(base_stem, settings.suffix, pattern=name_pattern)
            target = output_dir / safe_filename(filename, fallback=f"{base_stem}-{position:03d}")

            def segment_progress(fraction: float, stage: str, _position: int = position) -> None:
                """Map a single clip's progress onto the whole plan."""
                if on_progress is None:
                    return
                share = max(0.0, fraction) / total
                base = (_position - 1) / total
                on_progress(min(0.999, base + share), f"Clip {_position} of {total} \u00b7 {stage}")

            if resize:
                # Two passes: cut first (cheap, exact), then reframe the short clip.
                # Reframing the whole source once per segment would be far slower.
                scratch = target.with_name(f".{target.stem}-cut{settings.suffix}")
                try:
                    self.video.trim(
                        plan.source,
                        scratch,
                        start=segment.start,
                        end=segment.end,
                        settings=EncodeSettings.for_container(container, quality=quality),
                        accurate=accurate,
                        on_progress=segment_progress,
                        cancel_token=cancel_token,
                    )
                    rendered = self.video.transform(
                        scratch,
                        target,
                        resize=resize,
                        settings=EncodeSettings.for_container(container, quality=quality),
                        on_progress=segment_progress,
                        cancel_token=cancel_token,
                    )
                finally:
                    scratch.unlink(missing_ok=True)
            else:
                rendered = self.video.trim(
                    plan.source,
                    target,
                    start=segment.start,
                    end=segment.end,
                    settings=EncodeSettings.for_container(container, quality=quality),
                    accurate=accurate,
                    on_progress=segment_progress,
                    cancel_token=cancel_token,
                )
            outputs.append(rendered)

        if on_progress:
            on_progress(1.0, f"{len(outputs)} clips written")
        _log.info("rendered %d clips into %s", len(outputs), output_dir)
        return outputs

    def render_one(
        self,
        source: Path,
        segment: Segment,
        destination: Path,
        *,
        quality: Quality = Quality.BALANCED,
        accurate: bool = True,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Render a single segment - used by the "export this clip" button."""
        container = destination.suffix.lstrip(".") or "mp4"
        return self.video.trim(
            source,
            destination,
            start=segment.start,
            end=segment.end,
            settings=EncodeSettings.for_container(container, quality=quality),
            accurate=accurate,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )
