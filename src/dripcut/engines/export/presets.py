"""Export presets: the sizes and codecs people actually publish to."""

from __future__ import annotations

from dataclasses import dataclass

from dripcut.engines.ffmpeg.filters import ScaleMode
from dripcut.engines.video.encode import EncodeSettings, Quality

__all__ = ["ExportPreset", "EXPORT_PRESETS", "preset_names", "get_preset"]


@dataclass(frozen=True, slots=True)
class ExportPreset:
    """A named combination of container, geometry and quality."""

    name: str
    container: str
    width: int | None = None
    height: int | None = None
    scale_mode: ScaleMode = ScaleMode.FILL
    quality: Quality = Quality.BALANCED
    fps: float | None = None
    description: str = ""
    audio_only: bool = False

    @property
    def resolution_label(self) -> str:
        """``1080x1920`` or ``Source``."""
        if self.width and self.height:
            return f"{self.width}\u00d7{self.height}"
        if self.height:
            return f"{self.height}p"
        return "Source"

    def to_settings(self) -> EncodeSettings:
        """Encoder settings for this preset."""
        return EncodeSettings.for_container(self.container, quality=self.quality, fps=self.fps)

    @property
    def size(self) -> tuple[int | None, int | None] | None:
        """``(width, height)`` or ``None`` when the source size is kept."""
        if self.width or self.height:
            return (self.width, self.height)
        return None


EXPORT_PRESETS: dict[str, ExportPreset] = {
    "Source quality": ExportPreset(
        name="Source quality",
        container="mp4",
        quality=Quality.HIGH,
        description="Same size as the original, high quality H.264.",
    ),
    "Vertical 1080x1920": ExportPreset(
        name="Vertical 1080x1920",
        container="mp4",
        width=1080,
        height=1920,
        scale_mode=ScaleMode.FILL,
        description="Full-frame vertical for Reels, Shorts and TikTok.",
    ),
    "Square 1080x1080": ExportPreset(
        name="Square 1080x1080",
        container="mp4",
        width=1080,
        height=1080,
        scale_mode=ScaleMode.FILL,
        description="Square feed posts.",
    ),
    "Landscape 1920x1080": ExportPreset(
        name="Landscape 1920x1080",
        container="mp4",
        width=1920,
        height=1080,
        scale_mode=ScaleMode.FIT,
        description="Standard 16:9 upload.",
    ),
    "Landscape 1280x720": ExportPreset(
        name="Landscape 1280x720",
        container="mp4",
        width=1280,
        height=720,
        scale_mode=ScaleMode.FIT,
        quality=Quality.SMALL,
        description="Smaller 16:9 for quick review copies.",
    ),
    "ProRes master": ExportPreset(
        name="ProRes master",
        container="mov",
        quality=Quality.LOSSLESS,
        description="Editing master for Resolve or Premiere. Large files.",
    ),
    "WebM (VP9)": ExportPreset(
        name="WebM (VP9)",
        container="webm",
        quality=Quality.BALANCED,
        description="Open format for the web.",
    ),
    "MKV passthrough": ExportPreset(
        name="MKV passthrough",
        container="mkv",
        quality=Quality.HIGH,
        description="Flexible container, keeps multiple tracks.",
    ),
    "GIF 640 wide": ExportPreset(
        name="GIF 640 wide",
        container="gif",
        width=640,
        fps=15,
        description="Short looping clip, no audio.",
    ),
    "Audio only (M4A)": ExportPreset(
        name="Audio only (M4A)",
        container="m4a",
        audio_only=True,
        description="Strip the picture, keep the sound.",
    ),
}


def preset_names() -> list[str]:
    """Preset names in menu order."""
    return list(EXPORT_PRESETS)


def get_preset(name: str) -> ExportPreset:
    """Look up a preset, defaulting to source quality."""
    return EXPORT_PRESETS.get(name, EXPORT_PRESETS["Source quality"])
