"""Encoder settings and the single place output codec arguments are built.

Having exactly one function that turns settings into FFmpeg arguments is what
keeps quality consistent between a trim, a split clip and a batch export - and
what makes "why does this look worse than that" a one-file investigation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = ["Quality", "AudioMode", "EncodeSettings", "CONTAINER_CODECS"]


class Quality(StrEnum):
    """Quality presets exposed in the UI, mapped to CRF and encoder speed."""

    LOSSLESS = "lossless"
    HIGH = "high"
    BALANCED = "balanced"
    SMALL = "small"
    TINY = "tiny"

    @property
    def crf(self) -> int:
        """Constant-rate-factor for software encoders."""
        return {
            Quality.LOSSLESS: 0,
            Quality.HIGH: 17,
            Quality.BALANCED: 21,
            Quality.SMALL: 26,
            Quality.TINY: 31,
        }[self]

    @property
    def preset(self) -> str:
        """libx264/libx265 speed preset."""
        return {
            Quality.LOSSLESS: "medium",
            Quality.HIGH: "slow",
            Quality.BALANCED: "medium",
            Quality.SMALL: "medium",
            Quality.TINY: "faster",
        }[self]

    @property
    def hw_quality(self) -> int:
        """VideoToolbox ``-q:v`` equivalent (1-100, higher is better)."""
        return {
            Quality.LOSSLESS: 100,
            Quality.HIGH: 78,
            Quality.BALANCED: 62,
            Quality.SMALL: 48,
            Quality.TINY: 34,
        }[self]

    @property
    def nvenc_cq(self) -> int:
        """NVENC constant-quality value; lower is higher quality."""
        return {
            Quality.LOSSLESS: 0,
            Quality.HIGH: 18,
            Quality.BALANCED: 23,
            Quality.SMALL: 28,
            Quality.TINY: 33,
        }[self]

    @property
    def label(self) -> str:
        """Radio label."""
        return {
            Quality.LOSSLESS: "Lossless (huge files)",
            Quality.HIGH: "High",
            Quality.BALANCED: "Balanced",
            Quality.SMALL: "Small",
            Quality.TINY: "Tiny (social previews)",
        }[self]


class AudioMode(StrEnum):
    """What to do with the audio track."""

    KEEP = "keep"  # re-encode with the configured codec
    COPY = "copy"  # pass through untouched
    MUTE = "mute"  # drop the track


CONTAINER_CODECS: dict[str, tuple[str, str]] = {
    # container -> (default video codec, default audio codec)
    "mp4": ("h264", "aac"),
    "mov": ("h264", "aac"),
    "mkv": ("h264", "aac"),
    "webm": ("vp9", "libopus"),
    "avi": ("mpeg4", "mp3"),
    "gif": ("gif", ""),
}


@dataclass(slots=True)
class EncodeSettings:
    """Everything needed to describe an output stream.

    ``stream_copy`` is the fast path: no re-encode at all. It is only valid when
    no filter changes pixels and the container accepts the source codec, which
    :class:`~dripcut.engines.video.engine.VideoEngine` checks before honouring it.
    """

    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"
    quality: Quality = Quality.BALANCED
    crf: int | None = None
    preset: str | None = None
    audio_mode: AudioMode = AudioMode.KEEP
    audio_bitrate: str = "192k"
    fps: float | None = None
    hardware: bool | None = None
    stream_copy: bool = False
    faststart: bool = True
    pixel_format: str = "yuv420p"
    extra_output_args: list[str] = field(default_factory=list)

    @classmethod
    def for_container(cls, container: str, **overrides: object) -> EncodeSettings:
        """Sensible defaults for a container, then apply ``overrides``."""
        video_codec, audio_codec = CONTAINER_CODECS.get(container.lower(), ("h264", "aac"))
        settings = cls(container=container.lower(), video_codec=video_codec, audio_codec=audio_codec)
        for key, value in overrides.items():
            if hasattr(settings, key) and value is not None:
                setattr(settings, key, value)
        return settings

    @property
    def suffix(self) -> str:
        """Output file suffix including the dot."""
        return f".{self.container.lstrip('.').lower()}"

    def resolved_crf(self) -> int:
        """Explicit CRF if set, otherwise the preset's value."""
        return self.crf if self.crf is not None else self.quality.crf

    def resolved_preset(self) -> str:
        """Explicit encoder preset if set, otherwise the quality preset."""
        return self.preset or self.quality.preset

    def build_args(self, *, video_encoder: str, has_audio: bool, has_video: bool = True) -> list[str]:
        """Build the output-side FFmpeg arguments.

        Args:
            video_encoder: Concrete encoder name chosen by the runner (may be a
                VideoToolbox encoder).
            has_audio: Whether the source has an audio track.
            has_video: Whether a video track should be written.

        Returns:
            Argument list to place immediately before the output path.
        """
        args: list[str] = []

        if self.stream_copy:
            args += ["-c", "copy"]
            if self.container in {"mp4", "mov"} and self.faststart:
                args += ["-movflags", "+faststart"]
            args += self.extra_output_args
            return args

        if has_video:
            args += ["-c:v", video_encoder]
            if video_encoder.endswith("videotoolbox"):
                args += ["-q:v", str(self.quality.hw_quality), "-allow_sw", "1"]
            elif video_encoder.endswith("_nvenc"):
                args += ["-cq:v", str(self.quality.nvenc_cq), "-preset", "p4"]
            elif video_encoder in {"libx264", "libx265"}:
                args += ["-crf", str(self.resolved_crf()), "-preset", self.resolved_preset()]
                if self.resolved_crf() == 0 and video_encoder == "libx264":
                    args += ["-qp", "0"]
                configured_threads = os.environ.get("DRIPCUT_FFMPEG_THREADS")
                if configured_threads is None and os.environ.get("DRIPCUT_ENV", "").lower() in {
                    "production",
                    "prod",
                }:
                    configured_threads = "1"
                if configured_threads:
                    try:
                        thread_count = max(1, min(16, int(configured_threads)))
                    except ValueError:
                        thread_count = 1
                    args += ["-threads", str(thread_count)]
            elif video_encoder == "libvpx-vp9":
                args += ["-crf", str(self.resolved_crf()), "-b:v", "0", "-row-mt", "1"]
            elif video_encoder == "prores_ks":
                args += ["-profile:v", "3"]
            if self.pixel_format and not video_encoder.startswith("prores"):
                args += ["-pix_fmt", self.pixel_format]
            if self.fps:
                args += ["-r", f"{self.fps:g}"]
        else:
            args.append("-vn")

        if not has_audio or self.audio_mode is AudioMode.MUTE:
            args.append("-an")
        elif self.audio_mode is AudioMode.COPY:
            args += ["-c:a", "copy"]
        else:
            args += ["-c:a", self.audio_codec, "-b:a", self.audio_bitrate]

        if self.container in {"mp4", "mov"} and self.faststart:
            args += ["-movflags", "+faststart"]
        args += self.extra_output_args
        return args
