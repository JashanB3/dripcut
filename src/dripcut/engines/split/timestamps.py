"""Manual timestamp split: cut exactly where the user says."""

from __future__ import annotations

from dripcut.core.errors import ValidationError
from dripcut.engines.split.base import SplitContext, SplitStrategy, cut_points_to_segments
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.utils.timecode import parse_timecode, parse_timecode_list

__all__ = ["TimestampSplit"]


class TimestampSplit(SplitStrategy):
    """Split at typed timecodes, or keep explicit in/out ranges.

    Parameters
    ----------
    timestamps
        Free-form list, e.g. ``"0:30, 1:15, 4:02"``. Interpreted as cut points.
    ranges
        Optional list of ``"start-end"`` pairs, e.g. ``"0:10-0:25, 1:00-1:30"``.
        When present, only those ranges are kept and ``timestamps`` is ignored.
    titles
        Optional newline-separated titles applied to the produced segments in order.
    """

    mode = SplitMode.TIMESTAMPS
    source = SegmentSource.MANUAL

    def plan(self, context: SplitContext) -> SplitPlan:
        """Parse user input into segments."""
        duration = context.media.duration
        raw_ranges = str(context.param("ranges", "") or "").strip()
        titles = [line.strip() for line in str(context.param("titles", "") or "").splitlines() if line.strip()]

        if raw_ranges:
            segments = self._parse_ranges(raw_ranges, duration)
            notes = [f"{len(segments)} clips from typed ranges."]
        else:
            raw_points = str(context.param("timestamps", "") or "").strip()
            if not raw_points:
                raise ValidationError(
                    "No timecodes yet.",
                    hint="Type cut points like 0:30, 1:15 - or ranges like 0:10-0:25.",
                )
            points = [p for p in parse_timecode_list(raw_points) if 0 < p < duration]
            if not points:
                raise ValidationError("None of those timecodes fall inside this file.")
            segments = cut_points_to_segments(points, duration, source=self.source)
            notes = [f"{len(points)} cut points, {len(segments)} clips."]

        for index, title in enumerate(titles):
            if index < len(segments):
                segment = segments[index]
                segments[index] = Segment(
                    start=segment.start,
                    end=segment.end,
                    title=title,
                    source=segment.source,
                )
        return self._finish(context, segments, notes=notes)

    @staticmethod
    def _parse_ranges(raw: str, duration: float) -> list[Segment]:
        """Parse ``start-end`` pairs separated by commas or newlines."""
        segments: list[Segment] = []
        for chunk in (part.strip() for part in raw.replace("\n", ",").split(",")):
            if not chunk:
                continue
            separator = "-" if "-" in chunk else ("\u2192" if "\u2192" in chunk else None)
            if separator is None:
                raise ValidationError(f"'{chunk}' is not a range. Use start-end, e.g. 0:10-0:25.")
            left, _, right = chunk.partition(separator)
            try:
                start = parse_timecode(left)
                end = parse_timecode(right)
            except ValueError as exc:
                raise ValidationError(f"'{chunk}' is not a valid range.") from exc
            start, end = max(0.0, start), min(end, duration)
            if end - start <= 0.05:
                continue
            segments.append(Segment(start=start, end=end, source=SegmentSource.MANUAL))
        if not segments:
            raise ValidationError("No usable ranges were found in that list.")
        return segments
