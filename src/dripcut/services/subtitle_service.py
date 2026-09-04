"""Subtitle orchestration: generate files, burn them in, keep styles per project."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from dripcut.core.config import Settings
from dripcut.core.errors import DependencyError, FFmpegError, ValidationError
from dripcut.core.logging import get_logger
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.engines.subtitle.generator import Cue, SubtitleEngine
from dripcut.engines.subtitle.styles import get_preset, preset_names
from dripcut.engines.video.encode import EncodeSettings, Quality
from dripcut.engines.video.engine import VideoEngine
from dripcut.models.media import MediaInfo
from dripcut.models.subtitle import CaptionStyle, SubtitleFormat
from dripcut.models.transcript import Transcript
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir

__all__ = ["SubtitleService"]

_log = get_logger("services.subtitles")

ProgressFn = Callable[[float, str], None]


class SubtitleService:
    """Writes subtitle files and burns captions into video."""

    def __init__(
        self,
        engine: SubtitleEngine,
        video: VideoEngine,
        settings: Settings,
    ) -> None:
        self.engine = engine
        self.video = video
        self.settings = settings

    def presets(self) -> list[str]:
        """Available caption preset names."""
        return preset_names()

    def preset(self, name: str) -> CaptionStyle:
        """Load a caption preset by name."""
        return get_preset(name)

    def can_burn(self) -> bool:
        """True when this FFmpeg build can hardcode styled subtitles."""
        return self.video.runner.has_filter("subtitles") or _python_renderer_available()

    def can_overlay(self) -> bool:
        """True when timed PNG captions can be composited in the final FFmpeg pass."""
        return self.video.runner.has_filter("overlay") and _python_renderer_available()

    def prepare_overlays(
        self,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        video_size: tuple[int, int] = (1920, 1080),
    ) -> list[tuple[Path, float, float]]:
        """Render one transparent caption image per cue for timed FFmpeg overlays."""
        if transcript.is_empty:
            return []
        from PIL import Image, ImageDraw  # noqa: PLC0415

        width, height = video_size
        render_style = (style or CaptionStyle()).fitted_to_video(width, height)
        cues = self.engine.build_cues(transcript, render_style)
        font = _load_font(
            render_style.font_name,
            render_style.font_size,
            bold=render_style.bold,
        )
        ensure_dir(destination)
        overlays: list[tuple[Path, float, float]] = []
        for index, cue in enumerate(cues, start=1):
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            _draw_caption(ImageDraw.Draw(image), image.size, cue.text, render_style, font)
            path = destination / f"caption-{index:03d}.png"
            image.save(path, format="PNG", optimize=True)
            overlays.append((path, cue.start, cue.end))
        return overlays

    def write(
        self,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        subtitle_format: str | SubtitleFormat = SubtitleFormat.SRT,
        video_size: tuple[int, int] = (1920, 1080),
        offset: float = 0.0,
    ) -> Path:
        """Write a subtitle file for a transcript."""
        chosen = SubtitleFormat(str(subtitle_format))
        target = destination.with_suffix(chosen.suffix)
        ensure_dir(target.parent)
        written = self.engine.write(
            transcript,
            target,
            style=style,
            subtitle_format=chosen,
            video_size=video_size,
            offset=offset,
        )
        _log.info("wrote %s", written.name)
        return written

    def preview_lines(
        self, transcript: Transcript, style: CaptionStyle, *, limit: int = 12
    ) -> list[tuple[str, str]]:
        """``(timecode, text)`` rows for the caption preview list."""
        from dripcut.utils.timecode import format_timecode  # local import keeps the API tidy

        cues = self.engine.build_cues(transcript, style)[:limit]
        return [
            (f"{format_timecode(cue.start, millis=False)}", cue.text.replace("\n", " \u23ce "))
            for cue in cues
        ]

    def burn(
        self,
        media: MediaInfo,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        quality: Quality = Quality.HIGH,
        offset: float = 0.0,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
        timings: dict[str, float] | None = None,
    ) -> Path:
        """Burn captions into the picture.

        ASS is always used as the intermediate format, even when the user asked for
        SRT elsewhere, because it is the only way the chosen font, outline and safe
        margins survive into the render.
        """
        if transcript.is_empty:
            raise ValidationError(
                "There is no transcript to burn yet.", hint="Run Transcribe first."
            )
        caption_style = style or CaptionStyle()
        width, height = media.video.display_resolution if media.video else (1920, 1080)
        ass_path = destination.with_suffix(".dripcut.ass")
        preparation_started = time.monotonic()
        self.engine.write(
            transcript,
            ass_path,
            style=caption_style,
            subtitle_format=SubtitleFormat.ASS,
            video_size=(width, height),
            offset=offset,
        )
        if timings is not None:
            timings["subtitle_preparation_seconds"] = round(
                time.monotonic() - preparation_started, 3
            )
        encoding_started = time.monotonic()
        if not self.video.runner.has_filter("subtitles"):
            ass_path.unlink(missing_ok=True)
            rendered = self._burn_with_python(
                media,
                transcript,
                destination,
                style=caption_style,
                quality=quality,
                offset=offset,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
            if timings is not None:
                timings["caption_encoding_seconds"] = round(
                    time.monotonic() - encoding_started, 3
                )
            return rendered
        try:
            rendered = self.video.burn_subtitles(
                media.path,
                destination,
                ass_path,
                settings=EncodeSettings.for_container(
                    destination.suffix.lstrip(".") or "mp4", quality=quality
                ),
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
            if timings is not None:
                timings["caption_encoding_seconds"] = round(
                    time.monotonic() - encoding_started, 3
                )
            return rendered
        finally:
            ass_path.unlink(missing_ok=True)

    def attach(
        self,
        media: MediaInfo,
        subtitles: Path,
        destination: Path,
        *,
        language: str = "eng",
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Mux subtitles as a switchable track instead of burning them."""
        return self.video.attach_subtitles(
            media.path, destination, subtitles, language=language, cancel_token=cancel_token
        )

    def _burn_with_python(
        self,
        media: MediaInfo,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle,
        quality: Quality,
        offset: float = 0.0,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Fallback burn-in path for FFmpeg builds without the subtitles filter."""
        if not _python_renderer_available():
            raise DependencyError(
                "Caption rendering needs OpenCV and Pillow.",
                hint="Install the project dependencies again, then retry.",
            )

        ensure_dir(destination.parent)
        target = destination
        width, height = media.video.display_resolution if media.video else (1920, 1080)
        render_style = style.fitted_to_video(width, height)
        clip_cues = list(
            _clip_cues(self.engine.build_cues(transcript, render_style), media.duration, offset)
        )
        if not clip_cues:
            shutil.copyfile(media.path, target)
            return target

        encoders = _caption_video_encoders(self.video.runner, target)
        last_error: FFmpegError | None = None
        for index, encoder in enumerate(encoders):
            try:
                return _stream_captioned_video(
                    self.video.runner,
                    media,
                    clip_cues,
                    target,
                    style=render_style,
                    quality=quality,
                    encoder=encoder,
                    on_progress=on_progress,
                    cancel_token=cancel_token,
                )
            except FFmpegError as exc:
                last_error = exc
                if index < len(encoders) - 1:
                    _log.warning("caption encoder %s failed; retrying", encoder)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise DependencyError("No video encoder is available for caption rendering.")


def _stream_captioned_video(
    runner: FFmpegRunner,
    media: MediaInfo,
    clip_cues: Sequence[Cue],
    destination: Path,
    *,
    style: CaptionStyle,
    quality: Quality,
    encoder: str,
    on_progress: ProgressFn | None,
    cancel_token: CancelToken | None,
) -> Path:
    """Draw captions in Python while FFmpeg performs the fast final encode."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from PIL import Image, ImageDraw  # noqa: PLC0415

    capture = cv2.VideoCapture(str(media.path))
    if not capture.isOpened():
        raise ValidationError(f"{media.name} could not be opened for caption rendering.")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or (media.video.fps if media.video else 30.0) or 30.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or (media.video.width if media.video else 0))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or (media.video.height if media.video else 0))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or max(1, media.duration * fps))
    if width <= 0 or height <= 0:
        capture.release()
        raise ValidationError(f"{media.name} has no readable video frames.")

    command = [
        runner.resolve_binary(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *_caption_ffmpeg_args(media, destination, width, height, fps, encoder, quality),
    ]
    stderr_buffer: deque[str] = deque(maxlen=60)
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:  # pragma: no cover - host dependent
        capture.release()
        raise FFmpegError(
            "FFmpeg could not be started.",
            command=command,
            hint="Check that FFmpeg is installed and available, then try again.",
        ) from exc

    stderr_thread = threading.Thread(
        target=_drain_binary_stderr, args=(process.stderr, stderr_buffer), daemon=True
    )
    stderr_thread.start()

    scaled = style
    font = _load_font(scaled.font_name, scaled.font_size, bold=scaled.bold)
    active_index = 0
    frame_index = 0
    cancelled = False
    broken_pipe = False
    try:
        while True:
            if cancel_token is not None and cancel_token.cancelled:
                cancelled = True
                break
            ok, frame = capture.read()
            if not ok:
                break
            seconds = frame_index / fps if fps > 0 else 0.0
            while active_index < len(clip_cues) and clip_cues[active_index].end <= seconds:
                active_index += 1
            active = (
                clip_cues[active_index]
                if active_index < len(clip_cues)
                and clip_cues[active_index].start <= seconds < clip_cues[active_index].end
                else None
            )
            if active is not None:
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(image)
                _draw_caption(draw, image.size, active.text, scaled, font)
                frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
            try:
                if process.stdin is None:  # pragma: no cover - defensive
                    broken_pipe = True
                    break
                process.stdin.write(np.ascontiguousarray(frame).tobytes())
            except BrokenPipeError:
                broken_pipe = True
                break
            frame_index += 1
            if on_progress and frame_index % max(1, int(fps)) == 0:
                on_progress(min(0.98, frame_index / max(frame_count, 1) * 0.98), "Burning captions")
    finally:
        capture.release()
        if process.stdin is not None:
            try:
                process.stdin.close()
            except BrokenPipeError:
                broken_pipe = True

    if cancelled:
        _terminate_process(process)
    else:
        process.wait()
    stderr_thread.join(timeout=2)
    stderr_tail = "\n".join(stderr_buffer).strip()

    if cancelled:
        destination.unlink(missing_ok=True)
        raise ValidationError("Caption render was cancelled.")
    if process.returncode != 0 or broken_pipe:
        destination.unlink(missing_ok=True)
        raise FFmpegError(
            "FFmpeg could not finish the caption render.",
            command=command,
            stderr_tail=stderr_tail,
            returncode=process.returncode,
            hint=stderr_tail.splitlines()[-1] if stderr_tail else "Try Small quality, then render again.",
        )
    if on_progress:
        on_progress(1.0, "Burning captions")
    return destination


def _caption_ffmpeg_args(
    media: MediaInfo,
    destination: Path,
    width: int,
    height: int,
    fps: float,
    encoder: str,
    quality: Quality,
) -> list[str]:
    """Build an FFmpeg command that accepts BGR frames on stdin."""
    container = destination.suffix.lstrip(".").lower()
    args = [
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s:v",
        f"{width}x{height}",
        "-r",
        f"{fps:g}",
        "-i",
        "pipe:0",
    ]
    if media.has_audio:
        args += ["-i", str(media.path)]
    args += ["-map", "0:v:0"]
    if media.has_audio:
        args += ["-map", "1:a:0?"]

    args += _caption_video_args(encoder, quality, width, height, fps)
    args += ["-c:a", "copy"] if media.has_audio else ["-an"]
    args += ["-shortest"]
    if container in {"mp4", "mov"}:
        args += ["-movflags", "+faststart"]
    args.append(str(destination))
    return args


def _caption_video_args(
    encoder: str, quality: Quality, width: int, height: int, fps: float
) -> list[str]:
    """Fast encoder settings for Python-rendered captions."""
    if encoder == "h264_videotoolbox":
        return [
            "-c:v",
            encoder,
            "-b:v",
            _caption_bitrate(width, height, fps, quality),
            "-pix_fmt",
            "yuv420p",
        ]
    if encoder == "libvpx-vp9":
        return [
            "-c:v",
            encoder,
            "-deadline",
            "realtime",
            "-cpu-used",
            "8",
            "-crf",
            str(quality.crf),
            "-b:v",
            "0",
        ]
    return [
        "-c:v",
        encoder,
        "-crf",
        str(quality.crf),
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
    ]


def _caption_video_encoders(runner: FFmpegRunner, destination: Path) -> list[str]:
    """Prefer hardware H.264 for caption renders, falling back to software."""
    container = destination.suffix.lstrip(".").lower()
    if container == "webm":
        return ["libvpx-vp9"] if runner.has_encoder("libvpx-vp9") else ["libx264"]
    preferred = runner.pick_video_encoder("h264", hardware=True)
    encoders = [preferred]
    if preferred != "libx264" and runner.has_encoder("libx264"):
        encoders.append("libx264")
    return encoders


def _caption_bitrate(width: int, height: int, fps: float, quality: Quality) -> str:
    """Reasonable VideoToolbox bitrate target scaled by resolution and FPS."""
    base_mbps = {
        Quality.LOSSLESS: 16.0,
        Quality.HIGH: 10.0,
        Quality.BALANCED: 6.0,
        Quality.SMALL: 3.5,
        Quality.TINY: 2.0,
    }[quality]
    scale = max(0.25, (width * height) / (1920 * 1080)) * max(0.5, fps / 30.0)
    return f"{max(900, int(base_mbps * scale * 1000))}k"


def _drain_binary_stderr(stream: object, buffer: deque[str]) -> None:
    """Collect byte stderr from a streaming FFmpeg process."""
    if stream is None:  # pragma: no cover - defensive
        return
    for line in iter(stream.readline, b""):  # type: ignore[attr-defined]
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            buffer.append(text)


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    """Stop FFmpeg without leaving it waiting for more piped frames."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:  # pragma: no cover - rare
        process.kill()


def _python_renderer_available() -> bool:
    """True when the Pillow/OpenCV fallback renderer can be used."""
    try:
        import cv2  # noqa: F401, PLC0415
        import numpy  # noqa: F401, PLC0415
        import PIL  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


def _clip_cues(cues: Iterable[Cue], duration: float, offset: float) -> Iterable[Cue]:
    """Yield transcript cues rebased onto one rendered clip."""
    end_limit = offset + duration
    for cue in cues:
        if cue.end <= offset or cue.start >= end_limit:
            continue
        yield Cue(
            max(0.0, cue.start - offset),
            min(duration, max(0.05, cue.end - offset)),
            cue.text,
            cue.words,
        )


def _load_font(name: str, size: int, *, bold: bool) -> Any:
    """Find a usable local font for Pillow text rendering."""
    from PIL import ImageFont  # noqa: PLC0415

    candidates = [
        name,
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_caption(
    draw: Any,
    size: tuple[int, int],
    text: str,
    style: CaptionStyle,
    font: Any,
) -> None:
    """Draw one caption cue onto a Pillow image."""
    width, height = size
    lines = text.splitlines() or [text]
    spacing = max(4, int(style.font_size * 0.16))
    bbox = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=spacing)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    align = int(style.alignment)
    if align in {1, 4, 7}:
        x = style.margin_h
        anchor = "la"
    elif align in {3, 6, 9}:
        x = width - style.margin_h - text_w
        anchor = "la"
    else:
        x = (width - text_w) / 2
        anchor = "la"

    if align in {7, 8, 9}:
        y = style.margin_v
    elif align in {4, 5, 6}:
        y = (height - text_h) / 2
    else:
        y = height - style.margin_v - text_h

    if style.box_opacity > 0:
        padding = max(12, int(style.font_size * 0.35))
        draw.rounded_rectangle(
            (x - padding, y - padding, x + text_w + padding, y + text_h + padding),
            radius=max(8, padding // 2),
            fill=_rgb(style.back_color),
        )
    if style.shadow > 0:
        offset = max(1, int(style.shadow))
        draw.multiline_text(
            (x + offset, y + offset),
            "\n".join(lines),
            font=font,
            fill=(0, 0, 0),
            spacing=spacing,
            align="center",
            anchor=anchor,
        )
    draw.multiline_text(
        (x, y),
        "\n".join(lines),
        font=font,
        fill=_rgb(style.primary_color),
        spacing=spacing,
        align="center",
        stroke_width=max(0, int(round(style.outline_width))),
        stroke_fill=_rgb(style.outline_color),
        anchor=anchor,
    )


def _rgb(value: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` into an RGB tuple."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return (255, 255, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (255, 255, 255)
