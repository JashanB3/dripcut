"""Export service: turns user intent into queued jobs.

This is the only module that knows how a UI action becomes a :class:`Job`. Each
method builds a closure, hands it to the queue, and returns immediately - so the
interface never blocks on FFmpeg.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from dripcut.core.config import Settings
from dripcut.core.errors import ValidationError
from dripcut.core.logging import get_logger
from dripcut.engines.export.presets import ExportPreset, get_preset
from dripcut.engines.export.queue import JobQueue
from dripcut.engines.video.encode import AudioMode, EncodeSettings, Quality
from dripcut.engines.video.engine import VideoEngine
from dripcut.models.clip import SplitPlan
from dripcut.models.job import Job, JobKind, JobResult
from dripcut.models.media import MediaInfo
from dripcut.services.split_service import SplitService
from dripcut.utils.fs import ensure_dir, safe_filename, unique_path

__all__ = ["ExportService"]

_log = get_logger("services.export")


class ExportService:
    """Builds and queues render jobs."""

    def __init__(
        self,
        queue: JobQueue,
        video: VideoEngine,
        split: SplitService,
        settings: Settings,
    ) -> None:
        self.queue = queue
        self.video = video
        self.split = split
        self.settings = settings

    # ------------------------------------------------------------------ helpers

    @property
    def default_output(self) -> Path:
        """Configured output directory, created on demand."""
        return ensure_dir(self.settings.output_path)

    def resolve_output(
        self, folder: str | Path | None, name: str, suffix: str, *, overwrite: bool = False
    ) -> Path:
        """Build a full output path from a folder, base name and suffix."""
        directory = ensure_dir(Path(folder).expanduser()) if folder else self.default_output
        filename = safe_filename(name, fallback="dripcut-output")
        target = directory / f"{filename}{suffix if not filename.endswith(suffix) else ''}"
        return target if overwrite else unique_path(target)

    def _queue(
        self,
        kind: JobKind,
        title: str,
        work: Callable[[Job], JobResult],
        *,
        source: Path | None = None,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Job:
        """Wrap ``work`` in a job and submit it."""
        job = Job(
            kind=kind,
            title=title,
            source=source,
            project_id=project_id,
            metadata=metadata or {},
        )
        return self.queue.submit_callable(job, work)

    @staticmethod
    def _progress(job: Job) -> Callable[[float, str], None]:
        """Progress callback that writes into the job."""

        def report(fraction: float, stage: str) -> None:
            if fraction < 0:
                job.stage = stage
            else:
                job.set_progress(fraction, stage)

        return report

    # -------------------------------------------------------------------- splits

    def queue_split(
        self,
        plan: SplitPlan,
        *,
        folder: str | Path | None = None,
        container: str = "mp4",
        quality: Quality = Quality.BALANCED,
        name_pattern: str = "{stem}-{index:03d}",
        accurate: bool = True,
        project_id: str | None = None,
        stem: str | None = None,
    ) -> Job:
        """Queue a job that renders every clip in a plan."""
        if plan.count == 0:
            raise ValidationError("Plan the split first, then export.")
        destination = ensure_dir(
            (Path(folder).expanduser() if folder else self.default_output)
            / safe_filename(f"{stem or plan.source.stem}-clips")
        )

        def work(job: Job) -> JobResult:
            """Render each segment and report the total."""
            outputs = self.split.render(
                plan,
                destination,
                container=container,
                quality=quality,
                name_pattern=name_pattern,
                accurate=accurate,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
                stem=stem,
            )
            return JobResult(
                outputs=outputs,
                message=f"{len(outputs)} clips in {destination.name}",
                data={"folder": str(destination)},
            )

        return self._queue(
            JobKind.SPLIT,
            f"Split {plan.source.name} into {plan.count} clips",
            work,
            source=plan.source,
            project_id=project_id,
            metadata={"mode": plan.mode.value, "count": plan.count},
        )

    # --------------------------------------------------------------------- tools

    def queue_trim(
        self,
        media: MediaInfo,
        *,
        start: float,
        end: float,
        folder: str | Path | None = None,
        name: str | None = None,
        container: str = "mp4",
        quality: Quality = Quality.HIGH,
        accurate: bool = True,
        project_id: str | None = None,
    ) -> Job:
        """Queue a trim."""
        target = self.resolve_output(folder, name or f"{media.stem}-trim", f".{container}")

        def work(job: Job) -> JobResult:
            """Render the trimmed range."""
            output = self.video.trim(
                media.path,
                target,
                start=start,
                end=end,
                settings=EncodeSettings.for_container(container, quality=quality),
                accurate=accurate,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.TRIM, f"Trim {media.name}", work, source=media.path, project_id=project_id
        )

    def queue_transform(
        self,
        media: MediaInfo,
        *,
        folder: str | Path | None = None,
        name: str | None = None,
        container: str = "mp4",
        quality: Quality = Quality.HIGH,
        kind: JobKind = JobKind.RESIZE,
        project_id: str | None = None,
        **transform_kwargs: Any,
    ) -> Job:
        """Queue any combination of crop, resize, rotate, fps and speed."""
        target = self.resolve_output(folder, name or f"{media.stem}-edit", f".{container}")

        def work(job: Job) -> JobResult:
            """Apply the transform in a single pass."""
            output = self.video.transform(
                media.path,
                target,
                settings=EncodeSettings.for_container(container, quality=quality),
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
                **transform_kwargs,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            kind, f"Render {media.name}", work, source=media.path, project_id=project_id
        )

    def queue_compress(
        self,
        media: MediaInfo,
        *,
        quality: Quality = Quality.SMALL,
        target_mb: float | None = None,
        max_height: int | None = None,
        folder: str | Path | None = None,
        name: str | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue a compression job."""
        target = self.resolve_output(folder, name or f"{media.stem}-small", ".mp4")

        def work(job: Job) -> JobResult:
            """Shrink the file."""
            output = self.video.compress(
                media.path,
                target,
                quality=quality,
                target_mb=target_mb,
                max_height=max_height,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            saved = max(0, media.size_bytes - output.stat().st_size)
            percent = (saved / media.size_bytes * 100) if media.size_bytes else 0
            return JobResult(outputs=[output], message=f"{output.name} ({percent:.0f}% smaller)")

        return self._queue(
            JobKind.COMPRESS, f"Compress {media.name}", work, source=media.path, project_id=project_id
        )

    def queue_convert(
        self,
        media: MediaInfo,
        *,
        container: str = "mp4",
        quality: Quality = Quality.BALANCED,
        folder: str | Path | None = None,
        name: str | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue a container/codec conversion."""
        target = self.resolve_output(folder, name or media.stem, f".{container}")

        def work(job: Job) -> JobResult:
            """Convert the file."""
            output = self.video.convert(
                media.path,
                target,
                quality=quality,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.CONVERT,
            f"Convert {media.name} to {container.upper()}",
            work,
            source=media.path,
            project_id=project_id,
        )

    def queue_extract_audio(
        self,
        media: MediaInfo,
        *,
        audio_format: str = "m4a",
        bitrate: str = "192k",
        mono: bool = False,
        folder: str | Path | None = None,
        name: str | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue audio extraction."""
        target = self.resolve_output(folder, name or media.stem, f".{audio_format}")

        def work(job: Job) -> JobResult:
            """Write the audio track."""
            output = self.video.extract_audio(
                media.path,
                target,
                bitrate=bitrate,
                mono=mono,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.AUDIO, f"Extract audio from {media.name}", work, source=media.path,
            project_id=project_id,
        )

    def queue_frames(
        self,
        media: MediaInfo,
        *,
        every_seconds: float | None = 1.0,
        fps: float | None = None,
        width: int | None = None,
        image_format: str = "png",
        folder: str | Path | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue frame extraction into a folder."""
        destination = ensure_dir(
            (Path(folder).expanduser() if folder else self.default_output)
            / safe_filename(f"{media.stem}-frames")
        )

        def work(job: Job) -> JobResult:
            """Write stills."""
            outputs = self.video.extract_frames(
                media.path,
                destination,
                every_seconds=every_seconds,
                fps=fps,
                width=width,
                image_format=image_format,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(
                outputs=outputs[:50],
                message=f"{len(outputs)} frames in {destination.name}",
                data={"folder": str(destination), "count": len(outputs)},
            )

        return self._queue(
            JobKind.FRAMES, f"Extract frames from {media.name}", work, source=media.path,
            project_id=project_id,
        )

    def queue_gif(
        self,
        media: MediaInfo,
        *,
        start: float = 0.0,
        end: float | None = None,
        fps: int = 15,
        width: int = 640,
        folder: str | Path | None = None,
        name: str | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue GIF creation."""
        target = self.resolve_output(folder, name or media.stem, ".gif")

        def work(job: Job) -> JobResult:
            """Render the GIF."""
            output = self.video.create_gif(
                media.path,
                target,
                start=start,
                end=end,
                fps=fps,
                width=width,
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.GIF, f"GIF from {media.name}", work, source=media.path, project_id=project_id
        )

    def queue_watermark(
        self,
        media: MediaInfo,
        *,
        logo: Path | None = None,
        text: str = "",
        position: str = "bottom-right",
        opacity: float = 0.85,
        font_size: int = 36,
        logo_width: int | None = None,
        folder: str | Path | None = None,
        name: str | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue an image or text watermark."""
        if not logo and not text.strip():
            raise ValidationError("Add a logo image or some watermark text.")
        target = self.resolve_output(folder, name or f"{media.stem}-watermarked", ".mp4")

        def work(job: Job) -> JobResult:
            """Overlay the watermark."""
            if logo:
                output = self.video.watermark_image(
                    media.path,
                    target,
                    Path(logo),
                    position=position,
                    opacity=opacity,
                    logo_width=logo_width,
                    on_progress=self._progress(job),
                    cancel_token=job.cancel_token,
                )
            else:
                output = self.video.watermark_text(
                    media.path,
                    target,
                    text,
                    position=position,
                    font_size=font_size,
                    opacity=opacity,
                    on_progress=self._progress(job),
                    cancel_token=job.cancel_token,
                )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.WATERMARK, f"Watermark {media.name}", work, source=media.path,
            project_id=project_id,
        )

    def queue_merge(
        self,
        sources: Sequence[Path],
        *,
        folder: str | Path | None = None,
        name: str = "merged",
        container: str = "mp4",
        quality: Quality = Quality.HIGH,
        project_id: str | None = None,
    ) -> Job:
        """Queue a merge of several files."""
        target = self.resolve_output(folder, name, f".{container}")

        def work(job: Job) -> JobResult:
            """Join the inputs."""
            output = self.video.merge(
                sources,
                target,
                settings=EncodeSettings.for_container(container, quality=quality),
                on_progress=self._progress(job),
                cancel_token=job.cancel_token,
            )
            return JobResult(outputs=[output], message=output.name)

        return self._queue(
            JobKind.MERGE, f"Merge {len(sources)} files", work, project_id=project_id
        )

    # -------------------------------------------------------------------- presets

    def queue_preset_export(
        self,
        media: MediaInfo,
        preset_name: str,
        *,
        folder: str | Path | None = None,
        name: str | None = None,
        start: float | None = None,
        end: float | None = None,
        project_id: str | None = None,
    ) -> Job:
        """Queue an export using a named preset (the one-click publish path)."""
        preset: ExportPreset = get_preset(preset_name)
        suffix = f".{preset.container}"
        target = self.resolve_output(folder, name or f"{media.stem}-{preset.container}", suffix)

        def work(job: Job) -> JobResult:
            """Render according to the preset."""
            if preset.audio_only:
                output = self.video.extract_audio(
                    media.path,
                    target,
                    on_progress=self._progress(job),
                    cancel_token=job.cancel_token,
                )
            elif preset.container == "gif":
                output = self.video.create_gif(
                    media.path,
                    target,
                    start=start or 0.0,
                    end=end,
                    fps=int(preset.fps or 15),
                    width=preset.width or 640,
                    on_progress=self._progress(job),
                    cancel_token=job.cancel_token,
                )
            else:
                settings = preset.to_settings()
                if preset.container == "mov" and preset.quality is Quality.LOSSLESS:
                    settings.video_codec = "prores"
                    settings.audio_codec = "pcm_s16le"
                    settings.audio_mode = AudioMode.KEEP
                output = self.video.transform(
                    media.path,
                    target,
                    resize=preset.size,
                    scale_mode=preset.scale_mode,
                    fps=preset.fps,
                    settings=settings,
                    on_progress=self._progress(job),
                    cancel_token=job.cancel_token,
                )
            return JobResult(outputs=[output], message=f"{output.name} \u00b7 {preset.name}")

        return self._queue(
            JobKind.CONVERT,
            f"Export {media.name} as {preset.name}",
            work,
            source=media.path,
            project_id=project_id,
            metadata={"preset": preset.name},
        )

    # ---------------------------------------------------------------------- batch

    def queue_batch(
        self,
        sources: Sequence[MediaInfo],
        operation: str,
        *,
        folder: str | Path | None = None,
        project_id: str | None = None,
        **options: Any,
    ) -> Job:
        """Queue one job that applies the same operation to many files.

        A single job rather than one per file, so the queue shows "Batch: 12 files"
        with honest overall progress instead of twelve rows racing each other.
        """
        if not sources:
            raise ValidationError("Add some files to the batch first.")
        destination = ensure_dir(
            (Path(folder).expanduser() if folder else self.default_output) / "batch"
        )
        handlers: dict[str, Callable[[MediaInfo, Job], list[Path]]] = {
            "compress": lambda info, job: [
                self.video.compress(
                    info.path,
                    destination / f"{info.stem}-small.mp4",
                    quality=options.get("quality", Quality.SMALL),
                    max_height=options.get("max_height"),
                    cancel_token=job.cancel_token,
                )
            ],
            "convert": lambda info, job: [
                self.video.convert(
                    info.path,
                    destination / f"{info.stem}.{options.get('container', 'mp4')}",
                    quality=options.get("quality", Quality.BALANCED),
                    cancel_token=job.cancel_token,
                )
            ],
            "resize": lambda info, job: [
                self.video.transform(
                    info.path,
                    destination / f"{info.stem}-resized.mp4",
                    resize=(options.get("width"), options.get("height")),
                    scale_mode=options.get("scale_mode", "fit"),
                    cancel_token=job.cancel_token,
                )
            ],
            "audio": lambda info, job: [
                self.video.extract_audio(
                    info.path,
                    destination / f"{info.stem}.{options.get('audio_format', 'm4a')}",
                    cancel_token=job.cancel_token,
                )
            ],
            "gif": lambda info, job: [
                self.video.create_gif(
                    info.path,
                    destination / f"{info.stem}.gif",
                    end=min(info.duration, options.get("gif_seconds", 6.0)),
                    width=options.get("width", 640),
                    cancel_token=job.cancel_token,
                )
            ],
            "thumbnail": lambda info, job: [
                self.video.thumbnail(
                    info.path,
                    destination / f"{info.stem}.jpg",
                    width=options.get("width", 1280),
                    cancel_token=job.cancel_token,
                )
            ],
        }
        handler = handlers.get(operation)
        if handler is None:
            raise ValidationError(f"Batch operation {operation!r} is not available.")

        def work(job: Job) -> JobResult:
            """Run the operation over every input, collecting failures."""
            outputs: list[Path] = []
            failures: list[str] = []
            total = len(sources)
            for position, info in enumerate(sources, start=1):
                job.cancel_token.raise_if_cancelled()
                job.set_progress((position - 1) / total, f"{info.name} ({position}/{total})")
                try:
                    outputs.extend(handler(info, job))
                except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                    _log.warning("batch item failed: %s (%s)", info.name, exc)
                    failures.append(info.name)
            message = f"{len(outputs)} files written"
            if failures:
                message += f", {len(failures)} skipped"
            return JobResult(
                outputs=outputs,
                message=message,
                data={"folder": str(destination), "failures": failures},
            )

        return self._queue(
            JobKind.BATCH,
            f"Batch {operation} \u00b7 {len(sources)} files",
            work,
            project_id=project_id,
            metadata={"operation": operation, "count": len(sources)},
        )
