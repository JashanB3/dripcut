"""Caption styling and subtitle formats."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

__all__ = ["SubtitleFormat", "CaptionStyle"]


class SubtitleFormat(StrEnum):
    """Subtitle containers DripCut can write."""

    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"
    TXT = "txt"

    @property
    def suffix(self) -> str:
        """File suffix including the dot."""
        return f".{self.value}"

    @property
    def supports_styling(self) -> bool:
        """True when the format can carry fonts, colours and positioning."""
        return self is SubtitleFormat.ASS


@dataclass(slots=True)
class CaptionStyle:
    """A burn-in caption look.

    Values map onto ASS style fields; DripCut writes ASS for burn-in because it is
    the only widely supported format that survives FFmpeg's ``subtitles`` filter
    with fonts, outlines and safe-area positioning intact.
    """

    name: str = "Clean"
    font_name: str = "Helvetica"
    font_size: int = 52
    bold: bool = True
    italic: bool = False
    uppercase: bool = False
    primary_color: str = "#FFFFFF"
    outline_color: str = "#0B0E17"
    back_color: str = "#0B0E17"
    outline_width: float = 3.0
    shadow: float = 0.0
    box_opacity: float = 0.0  # 0 = no box, 1 = solid plate behind the text
    alignment: int = 2  # libass numpad alignment: 2 = bottom-centre
    margin_v: int = 96
    margin_h: int = 64
    max_chars: int = 34
    max_lines: int = 2
    letter_spacing: float = 0.0
    karaoke: bool = False  # word-by-word highlight

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation stored in project manifests."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptionStyle:
        """Rebuild, ignoring unknown keys so presets can gain fields safely."""
        known = set(cls.__slots__)
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def scaled(self, factor: float) -> CaptionStyle:
        """Return a copy with sizes scaled for a different output resolution."""
        clone = CaptionStyle.from_dict(self.to_dict())
        clone.font_size = max(12, int(round(self.font_size * factor)))
        clone.outline_width = round(self.outline_width * factor, 2)
        clone.margin_v = max(8, int(round(self.margin_v * factor)))
        clone.margin_h = max(8, int(round(self.margin_h * factor)))
        return clone

    def fitted_to_video(self, width: int, height: int) -> CaptionStyle:
        """Return a style tuned for the actual rendered frame.

        Portrait clips need different caption geometry from landscape clips: using
        the 1920px height to scale text makes subtitles huge and too wide for a
        9:16 canvas. The portrait fit scales from width, shortens lines, and moves
        captions to the center so they read like mobile-first social captions.
        """
        width = max(1, int(width or 1))
        height = max(1, int(height or 1))
        if height > width * 1.1:
            factor = min(width / 1080, height / 1920)
            clone = self.scaled(factor)
            clone.alignment = 5
            clone.font_size = max(28, min(50, int(round(clone.font_size * 0.88))))
            if clone.outline_width > 0:
                clone.outline_width = round(max(1.8, min(3.2, clone.outline_width * 0.85)), 2)
            clone.margin_h = max(48, int(width * 0.09))
            clone.margin_v = max(24, int(height * 0.04))
            clone.max_chars = min(clone.max_chars, 24)
            clone.max_lines = min(max(1, clone.max_lines), 2)
            return clone
        if abs(width - height) <= max(width, height) * 0.12:
            clone = self.scaled(min(width, height) / 1080)
            clone.max_chars = min(clone.max_chars, 30)
            clone.max_lines = min(max(1, clone.max_lines), 2)
            return clone
        return self.scaled(height / 1080)
