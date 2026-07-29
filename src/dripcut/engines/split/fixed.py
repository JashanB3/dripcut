"""Fixed-length split: cut every N seconds."""

from __future__ import annotations

from dripcut.core.errors import ValidationError
from dripcut.engines.split.base import SplitContext, SplitStrategy
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan

__all__ = ["FixedLengthSplit"]


class FixedLengthSplit(SplitStrategy):
    """Cut the source into equal chunks.

    Parameters
    ----------
    clip_length
        Chunk length in seconds (default 30).
    overlap
        Seconds of overlap between consecutive chunks, useful when a sentence
        should not be cut in half at the boundary.
    drop_last_shorter_than
        Discard a trailing chunk shorter than this many seconds.
    """

    mode = SplitMode.FIXED
    source = SegmentSource.FIXED

    def plan(self, context: SplitContext) -> SplitPlan:
        """Produce evenly spaced segments."""
        length = float(context.param("clip_length", 30.0))
        overlap = max(0.0, float(context.param("overlap", 0.0)))
        drop_below = float(context.param("drop_last_shorter_than", 1.0))
        duration = context.media.duration

        if length <= 0:
            raise ValidationError("Clip length must be greater than zero seconds.")
        if overlap >= length:
            raise ValidationError("Overlap must be shorter than the clip length.")
        if duration <= 0:
            raise ValidationError("This file reports no duration, so it cannot be split.")

        step = length - overlap
        segments: list[Segment] = []
        start = 0.0
        while start < duration - 0.05:
            end = min(start + length, duration)
            if end - start >= drop_below or not segments:
                segments.append(Segment(start=start, end=end, source=self.source))
            start += step

        notes = []
        if overlap:
            notes.append(f"Clips overlap by {overlap:g}s.")
        expected = len(segments)
        notes.append(f"{expected} clips of about {length:g}s.")
        return self._finish(context, segments, notes=notes)
