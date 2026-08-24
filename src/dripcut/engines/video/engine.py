"""The video engine: one method per tool, all of them cancellable.

Every method follows the same contract:

* takes a source path plus tool-specific parameters,
* writes to an explicit destination (never in place),
* reports progress through an optional callback,
* honours a :class:`~dripcut.utils.concurrency.CancelToken`,
* returns the paths it produced.

Nothing here knows about projects, queues or the UI, so the same engine backs the
workspace, the batch runner and the CLI.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

from dripcut.core.errors import ValidationError
from dripcut.core.logging import get_logger
from dripcut.engines.ffmpeg.filters import (
    FilterGraph,
    ScaleMode,
    crop_filter,
    fps_filter,
    rotate_filters,
    scale_filter,
    subtitle_filter,
    watermark_overlay,
)
from dripcut.engines.ffmpeg.probe import MediaProbe
from dripcut.engines.ffmpeg.runner import FFmpegRunner, ProgressCallback
from dripcut.engines.video.encode import AudioMode, EncodeSettings, Quality  # noqa: F401
from dripcut.engines.video.portrait import build_blur_background_filters, build_tracked_crop
from dripcut.models.media import MediaInfo
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir, unique_path

__all__ = ["VideoEngine"]

_log = get_logger("engines.video")

# Codecs that can be stream-copied into a given container without re-encoding.
_COPY_SAFE: dict[str, frozenset[str]] = {
    "mp4": frozenset({"h264", "hevc", "mpeg4", "av1"}),
    "mov": frozenset({"h264", "hevc", "prores", "mpeg4"}),
    "mkv": frozenset({"h264", "hevc", "vp9", "av1", "mpeg4", "theora"}),
    "webm": frozenset({"vp8", "vp9", "av1"}),
}


class VideoEngine:
    """FFmpeg-backed implementation of DripCut's video tools."""

    def __init__(self, runner: FFmpegRunner, probe: MediaProbe) -> None:
        self.runner = runner
        self.probe = probe

    # ------------------------------------------------------------------ helpers

    def _info(self, source: Path | MediaInfo) -> MediaInfo:
        """Accept either a path or an already-probed :class:`MediaInfo`."""
        return source if isinstance(source, MediaInfo) else self.probe.probe(source)

    def can_stream_copy(self, info: MediaInfo, container: str) -> bool:
        """True when the source video codec fits ``container`` untouched."""
        if not info.video:
            return False
        allowed = _COPY_SAFE.get(container.lower())
        return bool(allowed and info.video.codec.lower() in allowed)

    def _encoder(self, settings: EncodeSettings) -> str:
        """Resolve the concrete encoder for these settings."""
        return self.runner.pick_video_encoder(settings.video_codec, hardware=settings.hardware)

    def _finalise(self, destination: Path, *, overwrite: bool) -> Path:
        """Create the parent directory and pick a free filename if needed."""
        ensure_dir(destination.parent)
        return destination if overwrite else unique_path(destination)

    # ------------------------------------------------------------------ trimming

    def trim(
        self,
        source: Path,
        destination: Path,
        *,
        start: float = 0.0,
        end: float | None = None,
        settings: EncodeSettings | None = None,
        accurate: bool = True,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        overwrite: bool = True,
    ) -> Path:
        """Keep the range ``[start, end)`` of ``source``.

        Two strategies are available and the difference is visible to users:

        * ``accurate=False`` seeks before the input and stream-copies. It is nearly
          instant but can only cut on keyframes, so the clip may start up to a
          couple of seconds early.
        * ``accurate=True`` re-encodes and lands on the exact frame.

        Args:
            source: Input file.
            destination: Output file; the suffix decides the container.
            start: Offset in seconds.
            end: End offset in seconds, or ``None`` for "until the end".
            settings: Encoder settings; defaults are derived from the suffix.
            accurate: Frame-accurate re-encode instead of a keyframe copy.
            on_progress: Progress callback.
            cancel_token: Cancellation token.
            overwrite: Replace ``destination`` instead of adding a suffix.

        Returns:
            The written file path.
        """
        info = self._info(source)
        end_time = info.duration if end is None else min(float(end), info.duration)
        if end_time - start < 0.02:
            raise ValidationError(
                "That range is too short to export.", hint="Pick at least 0.02 seconds."
            )
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        target = self._finalise(destination, overwrite=overwrite)
        duration = end_time - start

        args: list[str] = []
        if accurate:
            # Input seek gets us close fast, output seek lands the exact frame.
            fast_seek = max(0.0, start - 2.0)
            args += ["-ss", f"{fast_seek:.3f}", "-i", str(info.path)]
            args += ["-ss", f"{start - fast_seek:.3f}", "-t", f"{duration:.3f}"]
            config.stream_copy = False
        else:
            args += ["-ss", f"{start:.3f}", "-i", str(info.path), "-t", f"{duration:.3f}"]
            config.stream_copy = self.can_stream_copy(info, container)
            if config.stream_copy:
                args += ["-avoid_negative_ts", "make_zero"]

        args += config.build_args(
            video_encoder=self._encoder(config),
            has_audio=info.has_audio,
            has_video=info.has_video,
        )
        args.append(str(target))

        self.runner.run(
            args,
            duration=duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Trimming",
        )
        _log.info("trimmed %s -> %s (%.2fs)", info.name, target.name, duration)
        return target

    def cut_out(
        self,
        source: Path,
        destination: Path,
        *,
        remove: Sequence[tuple[float, float]],
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Remove ranges from the middle of a file and join what is left.

        Implemented as select/aselect expressions in a single pass, which avoids
        writing intermediate files - important on a laptop SSD.
        """
        info = self._info(source)
        keep = _invert_ranges(remove, info.duration)
        if not keep:
            raise ValidationError("Removing those ranges would leave nothing behind.")
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        between = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keep)
        video_filter = f"select='{between}',setpts=N/FRAME_RATE/TB"
        audio_filter = f"aselect='{between}',asetpts=N/SR/TB"

        args = ["-i", str(info.path), "-vf", video_filter]
        if info.has_audio:
            args += ["-af", audio_filter]
        args += config.build_args(
            video_encoder=self._encoder(config), has_audio=info.has_audio
        )
        args.append(str(target))

        self.runner.run(
            args,
            duration=sum(e - s for s, e in keep),
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Cutting",
        )
        return target

    # -------------------------------------------------------------------- merging

    def merge(
        self,
        sources: Sequence[Path],
        destination: Path,
        *,
        settings: EncodeSettings | None = None,
        normalise: bool | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Join files end to end.

        When every input shares codec, resolution and frame rate DripCut uses the
        concat *demuxer* with ``-c copy``: no quality loss and no encoding time.
        Mismatched inputs fall back to the concat *filter*, which re-encodes.
        """
        paths = [Path(p) for p in sources]
        if len(paths) < 2:
            raise ValidationError("Pick at least two files to merge.")
        infos = [self._info(path) for path in paths]
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        target = self._finalise(destination, overwrite=True)
        total = sum(info.duration for info in infos)

        uniform = _streams_match(infos)
        needs_encode = normalise if normalise is not None else not uniform

        if not needs_encode:
            with NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
                for info in infos:
                    escaped = str(info.path).replace("'", "'\\''")
                    handle.write(f"file '{escaped}'\n")
                list_file = Path(handle.name)
            try:
                args = [
                    "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy",
                ]
                if container in {"mp4", "mov"}:
                    args += ["-movflags", "+faststart"]
                args.append(str(target))
                self.runner.run(
                    args,
                    duration=total,
                    on_progress=on_progress,
                    cancel_token=cancel_token,
                    outputs=[target],
                    stage="Merging",
                )
            finally:
                list_file.unlink(missing_ok=True)
            return target

        # Re-encoding path: normalise to the first input's geometry.
        reference = next((i for i in infos if i.video), infos[0])
        width, height = (reference.video.display_resolution if reference.video else (1920, 1080))
        fps = reference.fps
        with_audio = all(info.has_audio for info in infos)

        args: list[str] = []
        for info in infos:
            args += ["-i", str(info.path)]
        chains: list[str] = []
        labels: list[str] = []
        for index in range(len(infos)):
            chains.append(
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g}[v{index}]"
            )
            labels.append(f"[v{index}]")
            if with_audio:
                chains.append(f"[{index}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{index}]")
                labels.append(f"[a{index}]")
        concat = (
            f"{''.join(labels)}concat=n={len(infos)}:v=1:a={1 if with_audio else 0}"
            f"[outv]{'[outa]' if with_audio else ''}"
        )
        args += ["-filter_complex", ";".join([*chains, concat]), "-map", "[outv]"]
        if with_audio:
            args += ["-map", "[outa]"]
        config.stream_copy = False
        args += config.build_args(video_encoder=self._encoder(config), has_audio=with_audio)
        args.append(str(target))

        self.runner.run(
            args,
            duration=total,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Merging",
        )
        return target

    # ------------------------------------------------------------------ transforms

    def transform(
        self,
        source: Path,
        destination: Path,
        *,
        crop: tuple[int, int, int, int] | None = None,
        resize: tuple[int | None, int | None] | None = None,
        scale_mode: ScaleMode = ScaleMode.FIT,
        rotate: int = 0,
        flip: str = "none",
        fps: float | None = None,
        smooth_fps: bool = False,
        speed: float = 1.0,
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Apply any combination of geometry and timing changes in one pass.

        Crop, resize, rotate, frame rate and speed all end up as a single filter
        chain, so a user who does three things pays for one encode instead of three.
        """
        info = self._info(source)
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        graph = FilterGraph()
        if crop:
            graph.add(crop_filter(*crop))
        if rotate or flip != "none":
            graph.extend(rotate_filters(rotate, flip=flip))
        if resize:
            graph.extend(scale_filter(resize[0], resize[1], mode=scale_mode))
        if fps:
            graph.extend(fps_filter(fps, smooth=smooth_fps))
        if speed and abs(speed - 1.0) > 1e-3:
            graph.add(f"setpts={1 / speed:.6f}*PTS")
        graph.ensure_even()

        args = ["-i", str(info.path), *graph.as_args()]
        if speed and abs(speed - 1.0) > 1e-3 and info.has_audio:
            args += ["-af", _atempo_chain(speed)]
        args += config.build_args(
            video_encoder=self._encoder(config), has_audio=info.has_audio
        )
        args.append(str(target))

        expected = info.duration / speed if speed else info.duration
        self.runner.run(
            args,
            duration=expected,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Rendering",
        )
        return target

    def portrait_transform(
        self,
        source: Path,
        destination: Path,
        *,
        mode: str = "ai_tracking",
        target_size: tuple[int, int] = (1080, 1920),
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Render a 9:16 portrait clip with tracking or a blurred backdrop."""
        info = self._info(source)
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)
        width, height = target_size
        mode_name = str(mode)

        if mode_name == "blur_background":
            filter_complex = ";".join(build_blur_background_filters(width, height))
            args: list[str] = ["-i", str(info.path), "-filter_complex", filter_complex, "-map", "[outv]"]
            if info.has_audio:
                args += ["-map", "0:a"]
        else:
            graph = FilterGraph()
            if mode_name == "ai_tracking" and info.video and info.video.orientation == "landscape":
                analysis = build_tracked_crop(
                    info.path,
                    info.duration,
                    target_aspect=width / height,
                    on_progress=on_progress,
                )
                if analysis.has_tracking:
                    crop = analysis.crop
                    graph.add(
                        "crop="
                        f"w='trunc(({crop.width})/2)*2':"
                        f"h='trunc(({crop.height})/2)*2':"
                        f"x='trunc(({crop.x})/2)*2':"
                        f"y='trunc(({crop.y})/2)*2'"
                    )
                else:
                    graph.extend(scale_filter(width, height, mode=ScaleMode.FILL))
            else:
                graph.extend(scale_filter(width, height, mode=ScaleMode.FILL))
            graph.add(f"scale={width}:{height}:flags=lanczos")
            graph.ensure_even()
            args = ["-i", str(info.path), *graph.as_args()]

        args += config.build_args(video_encoder=self._encoder(config), has_audio=info.has_audio)
        args.append(str(target))
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Rendering portrait",
        )
        return target

    def render_segment(
        self,
        source: Path,
        destination: Path,
        *,
        start: float,
        end: float,
        output_format: str = "source",
        portrait_mode: str = "center_crop",
        target_size: tuple[int, int] | None = None,
        resize: tuple[int | None, int | None] | None = None,
        subtitles: Path | None = None,
        caption_overlays: Sequence[tuple[Path, float, float]] | None = None,
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Trim, reframe, caption, and encode one source segment in one pass."""
        info = self._info(source)
        duration = min(float(end), info.duration) - max(0.0, float(start))
        if duration < 0.02:
            raise ValidationError("That range is too short to export.")
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)
        profile = str(output_format)
        width, height = target_size or {
            "portrait": (1080, 1920),
            "square": (1080, 1080),
            "landscape": (1920, 1080),
        }.get(profile, (0, 0))

        fast_seek = max(0.0, float(start) - 2.0)
        args: list[str] = [
            "-ss",
            f"{fast_seek:.3f}",
            "-i",
            str(info.path),
        ]
        for overlay_path, _, _ in caption_overlays or []:
            args += ["-loop", "1", "-framerate", "1", "-i", str(overlay_path)]
        args += [
            "-ss",
            f"{float(start) - fast_seek:.3f}",
            "-t",
            f"{duration:.3f}",
        ]

        if profile == "portrait" and portrait_mode == "blur_background":
            chains = build_blur_background_filters(width, height)
            output_label = "outv"
            if subtitles is not None:
                chains.append(f"[outv]{subtitle_filter(str(subtitles))}[captioned]")
                output_label = "captioned"
            for index, (_, cue_start, cue_end) in enumerate(
                caption_overlays or [], start=1
            ):
                next_label = f"captioned{index}"
                chains.append(
                    f"[{output_label}][{index}:v]overlay=0:0:"
                    f"enable='between(t,{cue_start:.3f},{cue_end:.3f})'[{next_label}]"
                )
                output_label = next_label
            args += ["-filter_complex", ";".join(chains), "-map", f"[{output_label}]"]
            if info.has_audio:
                args += ["-map", "0:a?"]
        else:
            graph = FilterGraph()
            if resize:
                graph.extend(scale_filter(resize[0], resize[1], mode=ScaleMode.FILL))
            elif profile == "portrait":
                if (
                    portrait_mode == "ai_tracking"
                    and info.video
                    and info.video.orientation == "landscape"
                ):
                    analysis = build_tracked_crop(
                        info.path,
                        duration,
                        target_aspect=width / height,
                        source_offset=float(start),
                        on_progress=on_progress,
                    )
                    if analysis.has_tracking:
                        crop = analysis.crop
                        graph.add(
                            "crop="
                            f"w='trunc(({crop.width})/2)*2':"
                            f"h='trunc(({crop.height})/2)*2':"
                            f"x='trunc(({crop.x})/2)*2':"
                            f"y='trunc(({crop.y})/2)*2'"
                        )
                        graph.add(f"scale={width}:{height}:flags=lanczos")
                    else:
                        graph.extend(scale_filter(width, height, mode=ScaleMode.FILL))
                else:
                    graph.extend(scale_filter(width, height, mode=ScaleMode.FILL))
            elif profile in {"landscape", "square"}:
                graph.extend(scale_filter(width, height, mode=ScaleMode.FILL))
            if subtitles is not None:
                graph.add(subtitle_filter(str(subtitles)))
            graph.ensure_even()
            if caption_overlays:
                chains = [f"[0:v]{graph.render()}[base]"]
                output_label = "base"
                for index, (_, cue_start, cue_end) in enumerate(caption_overlays, start=1):
                    next_label = f"captioned{index}"
                    chains.append(
                        f"[{output_label}][{index}:v]overlay=0:0:"
                        f"enable='between(t,{cue_start:.3f},{cue_end:.3f})'[{next_label}]"
                    )
                    output_label = next_label
                args += [
                    "-filter_complex",
                    ";".join(chains),
                    "-map",
                    f"[{output_label}]",
                ]
                if info.has_audio:
                    args += ["-map", "0:a?"]
            else:
                args += graph.as_args()

        args += config.build_args(
            video_encoder=self._encoder(config), has_audio=info.has_audio
        )
        args.append(str(target))
        self.runner.run(
            args,
            duration=duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Creating final clip",
        )
        return target

    def compress(
        self,
        source: Path,
        destination: Path,
        *,
        quality: Quality = Quality.SMALL,
        target_mb: float | None = None,
        max_height: int | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Shrink a file, either by quality preset or to a size budget.

        With ``target_mb`` the engine computes a bitrate from the duration and runs
        a single-pass VBR encode - accurate enough for upload limits and half the
        time of a two-pass run, which matters on battery.
        """
        info = self._info(source)
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = EncodeSettings.for_container(container, quality=quality)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        graph = FilterGraph()
        if max_height and info.video and info.video.display_resolution[1] > max_height:
            graph.extend(scale_filter(None, max_height, mode=ScaleMode.STRETCH))
        graph.ensure_even()

        args = ["-i", str(info.path), *graph.as_args()]
        if target_mb and info.duration > 0:
            audio_kbps = 128 if info.has_audio else 0
            total_kbps = (target_mb * 8 * 1024) / info.duration
            video_kbps = max(200, int(total_kbps - audio_kbps))
            encoder = self._encoder(config)
            args += ["-c:v", encoder, "-b:v", f"{video_kbps}k", "-maxrate", f"{int(video_kbps * 1.45)}k",
                     "-bufsize", f"{int(video_kbps * 2)}k", "-pix_fmt", "yuv420p"]
            args += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if info.has_audio else ["-an"]
            if container in {"mp4", "mov"}:
                args += ["-movflags", "+faststart"]
        else:
            args += config.build_args(
                video_encoder=self._encoder(config), has_audio=info.has_audio
            )
        args.append(str(target))

        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Compressing",
        )
        return target

    def convert(
        self,
        source: Path,
        destination: Path,
        *,
        quality: Quality = Quality.BALANCED,
        allow_copy: bool = True,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Change container (and codec when the container demands it)."""
        info = self._info(source)
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = EncodeSettings.for_container(container, quality=quality)
        config.stream_copy = allow_copy and self.can_stream_copy(info, container)
        target = self._finalise(destination, overwrite=True)

        args = ["-i", str(info.path)]
        args += config.build_args(
            video_encoder=self._encoder(config), has_audio=info.has_audio
        )
        args.append(str(target))
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Converting",
        )
        return target

    # --------------------------------------------------------------- extraction

    def extract_audio(
        self,
        source: Path,
        destination: Path,
        *,
        codec: str | None = None,
        bitrate: str = "192k",
        sample_rate: int | None = None,
        mono: bool = False,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Write the audio track to its own file."""
        info = self._info(source)
        if not info.has_audio:
            raise ValidationError(f"{info.name} has no audio track.")
        suffix = destination.suffix.lower()
        chosen = codec or {
            ".mp3": "libmp3lame",
            ".m4a": "aac",
            ".aac": "aac",
            ".wav": "pcm_s16le",
            ".flac": "flac",
            ".ogg": "libvorbis",
            ".opus": "libopus",
        }.get(suffix, "aac")
        target = self._finalise(destination, overwrite=True)

        args = ["-i", str(info.path), "-vn", "-c:a", chosen]
        if chosen != "pcm_s16le" and chosen != "flac":
            args += ["-b:a", bitrate]
        if sample_rate:
            args += ["-ar", str(sample_rate)]
        if mono:
            args += ["-ac", "1"]
        args.append(str(target))

        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Extracting audio",
        )
        return target

    def extract_frames(
        self,
        source: Path,
        directory: Path,
        *,
        every_seconds: float | None = None,
        fps: float | None = None,
        width: int | None = None,
        image_format: str = "png",
        quality: int = 2,
        start: float = 0.0,
        end: float | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> list[Path]:
        """Write still frames into ``directory`` and return them sorted."""
        info = self._info(source)
        ensure_dir(directory)
        pattern = directory / f"{info.stem}-%05d.{image_format.lstrip('.')}"

        graph = FilterGraph()
        if fps:
            graph.add(f"fps={fps:g}")
        elif every_seconds and every_seconds > 0:
            graph.add(f"fps=1/{every_seconds:g}")
        if width:
            graph.add(f"scale={int(width)}:-2:flags=lanczos")

        args: list[str] = []
        if start:
            args += ["-ss", f"{start:.3f}"]
        args += ["-i", str(info.path)]
        if end is not None:
            args += ["-t", f"{max(0.05, end - start):.3f}"]
        args += graph.as_args()
        if image_format.lower() in {"jpg", "jpeg"}:
            args += ["-q:v", str(max(1, min(31, quality)))]
        args += ["-vsync", "vfr", str(pattern)]

        self.runner.run(
            args,
            duration=(end or info.duration) - start,
            on_progress=on_progress,
            cancel_token=cancel_token,
            stage="Extracting frames",
        )
        return sorted(directory.glob(f"{info.stem}-*.{image_format.lstrip('.')}"))

    def create_gif(
        self,
        source: Path,
        destination: Path,
        *,
        start: float = 0.0,
        end: float | None = None,
        fps: int = 15,
        width: int = 640,
        dither: str = "bayer",
        loop: int = 0,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Render a GIF using a generated palette.

        The palettegen/paletteuse pair costs one extra pass but produces files
        roughly 40% smaller with visibly less banding than the naive conversion.
        """
        info = self._info(source)
        end_time = info.duration if end is None else min(end, info.duration)
        duration = max(0.1, end_time - start)
        target = self._finalise(destination.with_suffix(".gif"), overwrite=True)

        filter_complex = (
            f"fps={fps},scale={int(width)}:-1:flags=lanczos,split[a][b];"
            f"[a]palettegen=max_colors=192:stats_mode=diff[p];"
            f"[b][p]paletteuse=dither={dither}:diff_mode=rectangle"
        )
        args = [
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(info.path),
            "-filter_complex", filter_complex, "-loop", str(loop), str(target),
        ]
        self.runner.run(
            args,
            duration=duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Rendering GIF",
        )
        return target

    def thumbnail(
        self,
        source: Path,
        destination: Path,
        *,
        at: float | None = None,
        width: int = 640,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Grab one representative still, used for project cards.

        With no explicit time, FFmpeg's ``thumbnail`` filter picks the most
        representative frame from the first few seconds rather than a black fade-in.
        """
        info = self._info(source)
        target = self._finalise(destination, overwrite=True)
        args: list[str] = []
        if at is not None:
            args += ["-ss", f"{max(0.0, min(at, max(0.0, info.duration - 0.1))):.3f}"]
        args += ["-i", str(info.path)]
        if at is None:
            args += ["-vf", f"thumbnail=100,scale={int(width)}:-2:flags=lanczos"]
        else:
            args += ["-vf", f"scale={int(width)}:-2:flags=lanczos"]
        args += ["-frames:v", "1", str(target)]
        self.runner.run(args, cancel_token=cancel_token, outputs=[target], stage="Thumbnail")
        return target

    def make_proxy(
        self,
        source: Path,
        destination: Path,
        *,
        height: int = 480,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Build a small preview copy so the browser player stays responsive.

        4K H.265 files stutter badly in a web preview on integrated graphics; a
        480p proxy plays instantly and is cheap to produce with VideoToolbox.
        """
        info = self._info(source)
        target = self._finalise(destination.with_suffix(".mp4"), overwrite=True)
        args = [
            "-i", str(info.path),
            "-vf", f"scale=-2:{int(height)}:flags=fast_bilinear",
            "-c:v", self.runner.pick_video_encoder("h264"),
            "-q:v", "55", "-allow_sw", "1", "-pix_fmt", "yuv420p",
        ]
        if not self.runner.pick_video_encoder("h264").endswith("videotoolbox"):
            args = [a for a in args if a not in {"-q:v", "55", "-allow_sw", "1"}]
            args += ["-crf", "28", "-preset", "veryfast"]
        args += (["-c:a", "aac", "-b:a", "128k"] if info.has_audio else ["-an"])
        args += ["-movflags", "+faststart", str(target)]
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Building preview",
        )
        return target

    # --------------------------------------------------------------- watermark

    def watermark_image(
        self,
        source: Path,
        destination: Path,
        logo: Path,
        *,
        position: str = "bottom-right",
        margin: int = 24,
        opacity: float = 0.85,
        logo_width: int | None = None,
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Overlay a PNG/logo on the video."""
        info = self._info(source)
        if not Path(logo).exists():
            raise ValidationError("That watermark image could not be found.")
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        logo_filters, overlay = watermark_overlay(
            position, margin=margin, opacity=opacity, scale_width=logo_width
        )
        filter_complex = f"[1:v]{','.join(logo_filters)}[wm];[0:v][wm]{overlay}[outv]"
        args = [
            "-i", str(info.path), "-i", str(logo),
            "-filter_complex", filter_complex, "-map", "[outv]",
        ]
        if info.has_audio:
            args += ["-map", "0:a"]
        args += config.build_args(video_encoder=self._encoder(config), has_audio=info.has_audio)
        args.append(str(target))
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Watermarking",
        )
        return target

    def watermark_text(
        self,
        source: Path,
        destination: Path,
        text: str,
        *,
        position: str = "bottom-right",
        font_size: int = 36,
        color: str = "white",
        opacity: float = 0.8,
        margin: int = 32,
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Burn a text watermark (handle, URL, "draft") into the picture."""
        info = self._info(source)
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        positions = {
            "top-left": f"x={margin}:y={margin}",
            "top-right": f"x=w-tw-{margin}:y={margin}",
            "bottom-left": f"x={margin}:y=h-th-{margin}",
            "bottom-right": f"x=w-tw-{margin}:y=h-th-{margin}",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019")
        draw = (
            f"drawtext=text='{escaped}':fontsize={font_size}:fontcolor={color}@{opacity:.2f}"
            f":{positions.get(position, positions['bottom-right'])}"
            f":shadowcolor=black@0.45:shadowx=2:shadowy=2"
        )
        args = ["-i", str(info.path), "-vf", draw]
        args += config.build_args(video_encoder=self._encoder(config), has_audio=info.has_audio)
        args.append(str(target))
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Watermarking",
        )
        return target

    # --------------------------------------------------------------- subtitles

    def burn_subtitles(
        self,
        source: Path,
        destination: Path,
        subtitles: Path,
        *,
        force_style: str = "",
        settings: EncodeSettings | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Burn a subtitle file into the picture (always a re-encode)."""
        info = self._info(source)
        if not Path(subtitles).exists():
            raise ValidationError("That subtitle file could not be found.")
        container = destination.suffix.lstrip(".").lower() or "mp4"
        config = settings or EncodeSettings.for_container(container)
        config.stream_copy = False
        target = self._finalise(destination, overwrite=True)

        graph = FilterGraph().add(subtitle_filter(str(subtitles), force_style=force_style))
        graph.ensure_even()
        args = ["-i", str(info.path), *graph.as_args()]
        args += config.build_args(video_encoder=self._encoder(config), has_audio=info.has_audio)
        args.append(str(target))
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Burning captions",
        )
        return target

    def attach_subtitles(
        self,
        source: Path,
        destination: Path,
        subtitles: Path,
        *,
        language: str = "eng",
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Mux subtitles as a soft track - instant, and viewers can switch it off."""
        info = self._info(source)
        target = self._finalise(destination, overwrite=True)
        codec = "mov_text" if target.suffix.lower() in {".mp4", ".mov", ".m4v"} else "srt"
        args = [
            "-i", str(info.path), "-i", str(subtitles),
            "-map", "0", "-map", "1",
            "-c", "copy", "-c:s", codec,
            "-metadata:s:s:0", f"language={language}",
            str(target),
        ]
        self.runner.run(
            args, duration=info.duration, cancel_token=cancel_token, outputs=[target], stage="Muxing"
        )
        return target

    # ------------------------------------------------------------------ analysis

    def loudness(self, source: Path) -> dict[str, float]:
        """Measure integrated loudness with the EBU R128 filter.

        Returns:
            Mapping with ``lufs``, ``true_peak`` and ``lra`` (zeros when unknown).
        """
        info = self._info(source)
        if not info.has_audio:
            return {"lufs": 0.0, "true_peak": 0.0, "lra": 0.0}
        stderr = self.runner.probe_stderr(
            ["-i", str(info.path), "-af", "loudnorm=print_format=json", "-f", "null", "-"]
        )
        start, end = stderr.rfind("{"), stderr.rfind("}")
        if 0 <= start < end:
            try:
                payload = json.loads(stderr[start : end + 1])
                return {
                    "lufs": float(payload.get("input_i", 0.0)),
                    "true_peak": float(payload.get("input_tp", 0.0)),
                    "lra": float(payload.get("input_lra", 0.0)),
                }
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        return {"lufs": 0.0, "true_peak": 0.0, "lra": 0.0}

    def normalise_audio(
        self,
        source: Path,
        destination: Path,
        *,
        target_lufs: float = -14.0,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Bring audio to a platform loudness target (-14 LUFS suits most feeds)."""
        info = self._info(source)
        target = self._finalise(destination, overwrite=True)
        args = [
            "-i", str(info.path),
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(target),
        ]
        self.runner.run(
            args,
            duration=info.duration,
            on_progress=on_progress,
            cancel_token=cancel_token,
            outputs=[target],
            stage="Normalising audio",
        )
        return target


def _invert_ranges(remove: Sequence[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Return the ranges to keep given the ranges to remove."""
    ordered = sorted((max(0.0, s), min(duration, e)) for s, e in remove if e > s)
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in ordered:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.01:
        keep.append((cursor, duration))
    return [(s, e) for s, e in keep if e - s > 0.05]


def _streams_match(infos: Sequence[MediaInfo]) -> bool:
    """True when every input shares codec, geometry, frame rate and audio layout."""
    first = infos[0]
    if not first.video:
        return False
    for info in infos[1:]:
        if not info.video:
            return False
        if (
            info.video.codec != first.video.codec
            or info.video.display_resolution != first.video.display_resolution
            or abs(info.video.fps - first.video.fps) > 0.02
            or info.has_audio != first.has_audio
        ):
            return False
        if info.audio and first.audio and (
            info.audio.codec != first.audio.codec
            or info.audio.sample_rate != first.audio.sample_rate
            or info.audio.channels != first.audio.channels
        ):
            return False
    return True


def _atempo_chain(speed: float) -> str:
    """Build an ``atempo`` chain; the filter only accepts 0.5-2.0 per instance."""
    remaining = speed
    parts: list[str] = []
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.6f}")
    return ",".join(parts)
