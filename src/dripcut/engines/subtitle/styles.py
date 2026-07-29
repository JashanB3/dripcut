"""Caption presets and ASS style serialisation.

Colour handling is the fiddly part: ASS stores colours as ``&HAABBGGRR`` - alpha
first, then *reversed* RGB. Getting that wrong yields blue text where you asked for
red, so the conversion lives in one tested function.
"""

from __future__ import annotations

from dripcut.models.subtitle import CaptionStyle

__all__ = [
    "CAPTION_PRESETS",
    "preset_names",
    "get_preset",
    "hex_to_ass_colour",
    "force_style_string",
]


CAPTION_PRESETS: dict[str, CaptionStyle] = {
    "Clean": CaptionStyle(
        name="Clean",
        font_name="Helvetica Neue",
        font_size=48,
        bold=False,
        primary_color="#FFFFFF",
        outline_color="#0B0E17",
        outline_width=2.5,
        margin_v=88,
        max_chars=38,
    ),
    "Punch": CaptionStyle(
        name="Punch",
        font_name="Helvetica",
        font_size=64,
        bold=True,
        uppercase=True,
        primary_color="#FFFFFF",
        outline_color="#05070C",
        outline_width=5.0,
        shadow=1.0,
        margin_v=140,
        max_chars=22,
        max_lines=2,
    ),
    "Plate": CaptionStyle(
        name="Plate",
        font_name="Helvetica Neue",
        font_size=46,
        bold=True,
        primary_color="#F7F9FF",
        outline_color="#101526",
        back_color="#101526",
        box_opacity=0.72,
        outline_width=0.0,
        margin_v=96,
        max_chars=34,
    ),
    "Signal": CaptionStyle(
        name="Signal",
        font_name="Avenir Next",
        font_size=54,
        bold=True,
        primary_color="#7DF9D5",
        outline_color="#06121B",
        outline_width=3.5,
        margin_v=120,
        max_chars=28,
        letter_spacing=0.6,
    ),
    "Documentary": CaptionStyle(
        name="Documentary",
        font_name="Georgia",
        font_size=42,
        bold=False,
        italic=True,
        primary_color="#F2ECDF",
        outline_color="#161310",
        outline_width=2.0,
        margin_v=72,
        max_chars=44,
        max_lines=2,
    ),
    "Karaoke": CaptionStyle(
        name="Karaoke",
        font_name="Helvetica",
        font_size=58,
        bold=True,
        uppercase=True,
        primary_color="#FFFFFF",
        outline_color="#0A0D16",
        outline_width=4.0,
        margin_v=132,
        max_chars=24,
        karaoke=True,
    ),
}


def preset_names() -> list[str]:
    """Preset names in menu order."""
    return list(CAPTION_PRESETS)


def get_preset(name: str) -> CaptionStyle:
    """Return a copy of a preset, falling back to ``Clean``."""
    preset = CAPTION_PRESETS.get(name) or CAPTION_PRESETS["Clean"]
    return CaptionStyle.from_dict(preset.to_dict())


def hex_to_ass_colour(value: str, *, alpha: float = 1.0) -> str:
    """Convert ``#RRGGBB`` to ASS ``&HAABBGGRR``.

    Args:
        value: Hex colour, with or without the leading ``#``.
        alpha: Opacity from 0 (transparent) to 1 (opaque).
    """
    text = (value or "#FFFFFF").lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        text = "FFFFFF"
    try:
        red, green, blue = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        red, green, blue = 255, 255, 255
    transparency = int(round((1.0 - max(0.0, min(1.0, alpha))) * 255))
    return f"&H{transparency:02X}{blue:02X}{green:02X}{red:02X}"


def force_style_string(style: CaptionStyle) -> str:
    """Build the ``force_style`` value for FFmpeg's ``subtitles`` filter.

    Used when burning an SRT directly, where there is no ASS header to carry the
    look. Values map onto libass style fields.
    """
    parts = [
        f"FontName={style.font_name}",
        f"FontSize={style.font_size}",
        f"Bold={1 if style.bold else 0}",
        f"Italic={1 if style.italic else 0}",
        f"PrimaryColour={hex_to_ass_colour(style.primary_color)}",
        f"OutlineColour={hex_to_ass_colour(style.outline_color)}",
        f"BackColour={hex_to_ass_colour(style.back_color, alpha=style.box_opacity or 0.0)}",
        f"BorderStyle={3 if style.box_opacity > 0 else 1}",
        f"Outline={style.outline_width:g}",
        f"Shadow={style.shadow:g}",
        f"Alignment={style.alignment}",
        f"MarginV={style.margin_v}",
        f"MarginL={style.margin_h}",
        f"MarginR={style.margin_h}",
    ]
    if style.letter_spacing:
        parts.append(f"Spacing={style.letter_spacing:g}")
    return ",".join(parts)
