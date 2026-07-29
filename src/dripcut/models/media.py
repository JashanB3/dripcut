"""Media description produced by ffprobe."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dripcut.utils.fs import human_size
from dripcut.utils.timecode import format_clock, format_timecode

__all__ = ["VideoStream", "AudioStream", "Chapter", "MediaInfo"]


@dataclass(frozen=True, slots=True)
class VideoStream:
    """A single video track."""

    index: int
    codec: str
    width: int
    height: int
    fps: float
    bit_rate: int | None = None
    pix_fmt: str = ""
    rotation: int = 0

    @property
    def resolution(self) -> str:
        """``1920x1080`` style label."""
        return f"{self.width}x{self.height}"

    @property
    def display_resolution(self) -> tuple[int, int]:
        """Width and height after applying container rotation metadata."""
        if abs(self.rotation) % 180 == 90:
            return self.height, self.width
        return self.width, self.height

    @property
    def aspect_ratio(self) -> float:
        """Display aspect ratio as a float, or ``0`` for degenerate streams."""
        width, height = self.display_resolution
        return width / height if height else 0.0

    @property
    def orientation(self) -> str:
        """``portrait``, ``landscape`` or ``square``."""
        ratio = self.aspect_ratio
        if ratio == 0:
            return "unknown"
        if ratio > 1.05:
            return "landscape"
        return "portrait" if ratio < 0.95 else "square"


@dataclass(frozen=True, slots=True)
class AudioStream:
    """A single audio track."""

    index: int
    codec: str
    channels: int
    sample_rate: int
    bit_rate: int | None = None
    language: str = ""

    @property
    def layout(self) -> str:
        """Human channel layout."""
        return {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(self.channels, f"{self.channels}ch")


@dataclass(frozen=True, slots=True)
class Chapter:
    """A container chapter marker (MP4/MKV), used by the chapter split mode."""

    index: int
    start: float
    end: float
    title: str = ""

    @property
    def duration(self) -> float:
        """Chapter length in seconds."""
        return max(0.0, self.end - self.start)


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Everything DripCut knows about a file on disk.

    Constructed by :class:`dripcut.engines.ffmpeg.probe.MediaProbe`; treated as
    immutable everywhere else so two panels can never disagree about a duration.
    """

    path: Path
    duration: float
    size_bytes: int
    container: str
    video: VideoStream | None = None
    audio: AudioStream | None = None
    chapters: tuple[Chapter, ...] = ()
    extra_streams: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def name(self) -> str:
        """File name including suffix."""
        return self.path.name

    @property
    def stem(self) -> str:
        """File name without suffix - the default basis for output names."""
        return self.path.stem

    @property
    def has_video(self) -> bool:
        """True when a video track is present."""
        return self.video is not None

    @property
    def has_audio(self) -> bool:
        """True when an audio track is present."""
        return self.audio is not None

    @property
    def fps(self) -> float:
        """Frame rate, defaulting to 30 for audio-only media."""
        return self.video.fps if self.video else 30.0

    @property
    def duration_label(self) -> str:
        """Compact duration for chips."""
        return format_clock(self.duration)

    @property
    def timecode_label(self) -> str:
        """Full timecode for the workspace header."""
        return format_timecode(self.duration)

    @property
    def size_label(self) -> str:
        """Human file size."""
        return human_size(self.size_bytes)

    @property
    def bitrate_mbps(self) -> float:
        """Overall bitrate in Mbit/s."""
        if self.duration <= 0:
            return 0.0
        return (self.size_bytes * 8) / self.duration / 1_000_000

    def summary_rows(self) -> list[tuple[str, str]]:
        """Label/value pairs rendered by the media inspector card."""
        rows: list[tuple[str, str]] = [
            ("File", self.name),
            ("Duration", self.timecode_label),
            ("Size", self.size_label),
            ("Container", self.container.upper()),
        ]
        if self.video:
            width, height = self.video.display_resolution
            rows += [
                ("Video", f"{self.video.codec} \u00b7 {width}\u00d7{height} \u00b7 {self.video.fps:.2f} fps"),
                ("Orientation", self.video.orientation),
            ]
        if self.audio:
            rows.append(
                ("Audio", f"{self.audio.codec} \u00b7 {self.audio.layout} \u00b7 {self.audio.sample_rate} Hz")
            )
        rows.append(("Bitrate", f"{self.bitrate_mbps:.1f} Mbit/s"))
        if self.chapters:
            rows.append(("Chapters", str(len(self.chapters))))
        return rows
