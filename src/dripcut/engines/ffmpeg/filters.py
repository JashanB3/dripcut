"""Composable FFmpeg filter-graph builders.

Filter strings are notoriously easy to get subtly wrong, so every transform lives
here as a small, individually testable function, and :class:`FilterGraph` composes
them in order. Engines never concatenate filter strings by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "ScaleMode",
    "FilterGraph",
    "scale_filter",
    "crop_filter",
    "rotate_filters",
    "fps_filter",
    "pad_to_aspect",
    "watermark_overlay",
    "subtitle_filter",
    "even_dimensions",
]


class ScaleMode(StrEnum):
    """How a resize should treat aspect ratio."""

    FIT = "fit"  # letterbox inside the target, no cropping
    FILL = "fill"  # cover the target, crop the overflow
    STRETCH = "stretch"  # ignore aspect ratio
    EXACT = "exact"  # alias of stretch, kept for readable call sites

    @property
    def label(self) -> str:
        """Radio label in the resize panel."""
        return {
            ScaleMode.FIT: "Fit (add bars)",
            ScaleMode.FILL: "Fill (crop edges)",
            ScaleMode.STRETCH: "Stretch",
            ScaleMode.EXACT: "Exact",
        }[self]


def even_dimensions(width: int, height: int) -> tuple[int, int]:
    """Round a size down to even numbers, which yuv420p requires."""
    return max(2, width - (width % 2)), max(2, height - (height % 2))


def scale_filter(
    width: int | None,
    height: int | None,
    *,
    mode: ScaleMode = ScaleMode.FIT,
    background: str = "black",
) -> list[str]:
    """Build the filter chain for a resize.

    Args:
        width: Target width, or ``None``/``-1`` to derive from height.
        height: Target height, or ``None``/``-1`` to derive from width.
        mode: Aspect-ratio behaviour.
        background: Bar colour used by :attr:`ScaleMode.FIT`.

    Returns:
        Zero or more filter strings, in application order.
    """
    if not width and not height:
        return []
    target_w = width if width and width > 0 else -2
    target_h = height if height and height > 0 else -2

    if target_w < 0 or target_h < 0 or mode in {ScaleMode.STRETCH, ScaleMode.EXACT}:
        return [f"scale={target_w}:{target_h}:flags=lanczos"]

    if mode is ScaleMode.FIT:
        return [
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color={background}",
        ]
    # FILL
    return [
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={target_w}:{target_h}",
    ]


def crop_filter(x: int, y: int, width: int, height: int) -> str:
    """Build a ``crop`` filter, clamping to even, positive dimensions."""
    width, height = even_dimensions(int(width), int(height))
    return f"crop={width}:{height}:{max(0, int(x))}:{max(0, int(y))}"


def rotate_filters(degrees: int, *, flip: str = "none") -> list[str]:
    """Rotation and mirroring as lossless transposes where possible.

    Args:
        degrees: 0, 90, 180 or 270 (clockwise).
        flip: ``none``, ``horizontal``, ``vertical`` or ``both``.
    """
    filters: list[str] = []
    normalised = int(degrees) % 360
    if normalised == 90:
        filters.append("transpose=1")
    elif normalised == 180:
        filters.extend(["transpose=1", "transpose=1"])
    elif normalised == 270:
        filters.append("transpose=2")
    if flip in {"horizontal", "both"}:
        filters.append("hflip")
    if flip in {"vertical", "both"}:
        filters.append("vflip")
    return filters


def fps_filter(fps: float, *, smooth: bool = False) -> list[str]:
    """Change frame rate, optionally with motion interpolation.

    Interpolation looks better on slow pans but is expensive; it stays opt-in so
    the default path remains fast on an M1 Air.
    """
    if fps <= 0:
        return []
    if smooth:
        return [f"minterpolate=fps={fps:g}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"]
    return [f"fps={fps:g}"]


def pad_to_aspect(aspect: str, *, background: str = "black") -> list[str]:
    """Letterbox the picture to a target aspect such as ``9:16`` or ``1:1``."""
    try:
        left, _, right = aspect.partition(":")
        ratio = float(left) / float(right)
    except (ValueError, ZeroDivisionError):
        return []
    return [
        "scale=iw:ih",
        f"pad=if(gt(a\\,{ratio})\\,iw\\,ih*{ratio}):if(gt(a\\,{ratio})\\,iw/{ratio}\\,ih)"
        f":(ow-iw)/2:(oh-ih)/2:color={background}",
    ]


def watermark_overlay(
    position: str = "bottom-right",
    *,
    margin: int = 24,
    opacity: float = 0.85,
    scale_width: int | None = None,
) -> tuple[list[str], str]:
    """Build the overlay pieces for an image watermark.

    Returns:
        ``(logo_filters, overlay_expression)`` - the first is applied to the logo
        input, the second is the ``overlay`` filter placing it on the video.
    """
    logo_filters = ["format=rgba", f"colorchannelmixer=aa={max(0.0, min(1.0, opacity)):.3f}"]
    if scale_width and scale_width > 0:
        logo_filters.insert(0, f"scale={int(scale_width)}:-1:flags=lanczos")
    coordinates = {
        "top-left": f"{margin}:{margin}",
        "top-right": f"W-w-{margin}:{margin}",
        "bottom-left": f"{margin}:H-h-{margin}",
        "bottom-right": f"W-w-{margin}:H-h-{margin}",
        "center": "(W-w)/2:(H-h)/2",
    }
    return logo_filters, f"overlay={coordinates.get(position, coordinates['bottom-right'])}"


def subtitle_filter(subtitle_path: str, *, force_style: str = "") -> str:
    """Build a ``subtitles`` filter, escaping the characters libav cares about."""
    escaped = (
        str(subtitle_path)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(",", "\\,")
    )
    if force_style:
        return f"subtitles=filename='{escaped}':force_style='{force_style}'"
    return f"subtitles=filename='{escaped}'"


@dataclass(slots=True)
class FilterGraph:
    """An ordered list of simple video filters, rendered to a ``-vf`` string."""

    filters: list[str] = field(default_factory=list)

    def add(self, *entries: str | None) -> FilterGraph:
        """Append one or more filter strings, ignoring empties. Returns self."""
        for entry in entries:
            if entry:
                self.filters.append(entry)
        return self

    def extend(self, entries: list[str]) -> FilterGraph:
        """Append a list of filter strings. Returns self."""
        return self.add(*entries)

    def ensure_even(self) -> FilterGraph:
        """Append a final rounding pass so odd sizes never reach the encoder."""
        return self.add("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    @property
    def empty(self) -> bool:
        """True when nothing has been added."""
        return not self.filters

    def render(self) -> str:
        """Comma-joined filter chain."""
        return ",".join(self.filters)

    def as_args(self) -> list[str]:
        """``["-vf", "..."]`` or ``[]`` when the graph is empty."""
        return ["-vf", self.render()] if self.filters else []
