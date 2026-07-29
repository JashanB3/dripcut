"""Timecode parsing and formatting.

Timecodes are DripCut's primary unit of interface: they appear in the transcript
viewer, the split planner, the export queue and every log line. All conversions
funnel through this module so a value rendered in the UI always matches the value
handed to FFmpeg.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "parse_timecode",
    "format_timecode",
    "format_clock",
    "format_duration",
    "parse_timecode_list",
    "frames_to_seconds",
    "seconds_to_frames",
]

_TIMECODE_RE: Final = re.compile(
    r"^\s*(?:(?P<h>\d+):)?(?:(?P<m>[0-5]?\d):)?(?P<s>\d+(?:[.,]\d+)?)\s*$"
)
_UNIT_RE: Final = re.compile(r"^\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s|sec|m|min|h|hr)\s*$", re.I)
_UNIT_FACTORS: Final = {
    "ms": 0.001,
    "s": 1.0,
    "sec": 1.0,
    "m": 60.0,
    "min": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
}


def parse_timecode(value: str | float | int) -> float:
    """Parse a human timecode into seconds.

    Accepted forms: ``12``, ``12.5``, ``1:23``, ``01:02:03.400``, ``90s``,
    ``2min``, ``500ms``.

    Args:
        value: Timecode string, or a number already expressed in seconds.

    Returns:
        Offset in seconds as a float.

    Raises:
        ValueError: If the string cannot be interpreted as a timecode.
    """
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds < 0:
            raise ValueError("timecode cannot be negative")
        return seconds

    text = str(value).strip()
    if not text:
        raise ValueError("timecode is empty")

    unit_match = _UNIT_RE.match(text)
    if unit_match:
        factor = _UNIT_FACTORS[unit_match.group("unit").lower()]
        return float(unit_match.group("value")) * factor

    match = _TIMECODE_RE.match(text)
    if not match:
        raise ValueError(f"cannot parse timecode: {value!r}")

    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = float(match.group("s").replace(",", "."))
    if match.group("h") is None and match.group("m") is None and seconds >= 60:
        # Bare "150" means 150 seconds, which is intentional.
        pass
    return hours * 3600 + minutes * 60 + seconds


def parse_timecode_list(raw: str) -> list[float]:
    """Parse a comma / newline / space separated list of timecodes.

    Args:
        raw: Free-form user input, e.g. ``"0:30, 1:15\\n2:00"``.

    Returns:
        Sorted, de-duplicated list of offsets in seconds.
    """
    tokens = [tok for tok in re.split(r"[,\n;]+|\s{2,}", raw or "") if tok.strip()]
    if len(tokens) == 1:
        tokens = [tok for tok in re.split(r"\s+", tokens[0]) if tok]
    seconds = {round(parse_timecode(tok), 3) for tok in tokens}
    return sorted(seconds)


def format_timecode(seconds: float, *, millis: bool = True) -> str:
    """Format seconds as ``HH:MM:SS.mmm`` (the canonical DripCut display form)."""
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if millis:
        return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d}"


def format_clock(seconds: float) -> str:
    """Format seconds compactly for chips and labels: ``1:23`` or ``1:02:03``."""
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_duration(seconds: float) -> str:
    """Format a span in prose, e.g. ``"3m 12s"`` - used in summaries and logs."""
    seconds = max(0.0, float(seconds))
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def frames_to_seconds(frames: int, fps: float) -> float:
    """Convert a frame index to seconds for a given frame rate."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return frames / fps


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert seconds to the nearest frame index for a given frame rate."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return int(round(seconds * fps))
