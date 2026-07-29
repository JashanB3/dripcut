"""Silence-gap split, driven by FFmpeg's ``silencedetect`` filter."""

from __future__ import annotations

import re

from dripcut.core.errors import SplitPlanError
from dripcut.engines.split.base import SplitContext, SplitStrategy
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan

__all__ = ["SilenceSplit", "parse_silence_ranges", "silence_to_speech_ranges"]

_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


class SilenceSplit(SplitStrategy):
    """Cut in the pauses instead of mid-word.

    The filter reports silent *ranges*; DripCut inverts them into speech ranges and
    then pads each one slightly, because a clip that starts on the exact first
    phoneme sounds clipped.

    Parameters
    ----------
    threshold_db
        Level below which audio counts as silence (default -32 dBFS).
    min_silence
        Shortest pause that triggers a cut (default 0.6s).
    pad
        Seconds of headroom added to both sides of every kept range.
    keep_silence_as_clips
        Emit the silent stretches too, instead of only the speech.
    """

    mode = SplitMode.SILENCE
    source = SegmentSource.SILENCE
    requires_audio = True

    def plan(self, context: SplitContext) -> SplitPlan:
        """Run silencedetect and invert the result."""
        if not context.media.has_audio:
            raise SplitPlanError(
                f"{context.media.name} has no audio track.",
                hint="Silence detection needs sound. Try Scene changes.",
            )
        runner = context.services.get("runner")
        if runner is None:  # pragma: no cover - wired by the service layer
            raise SplitPlanError("Silence detection is unavailable in this install.")

        threshold = float(context.param("threshold_db", -32.0))
        min_silence = max(0.05, float(context.param("min_silence", 0.6)))
        pad = max(0.0, float(context.param("pad", 0.15)))
        keep_silence = bool(context.param("keep_silence_as_clips", False))

        context.report(0.05, "Listening for pauses")
        stderr = runner.probe_stderr(
            [
                "-i", str(context.media.path),
                "-af", f"silencedetect=noise={threshold:g}dB:d={min_silence:g}",
                "-vn", "-f", "null", "-",
            ]
        )
        context.check_cancelled()
        context.report(0.7, "Working out the cuts")

        silences = parse_silence_ranges(stderr, context.media.duration)
        if not silences:
            raise SplitPlanError(
                "No pauses long enough to cut on.",
                hint=f"Raise the threshold above {threshold:g} dB or shorten the minimum pause.",
            )

        if keep_silence:
            ranges = sorted(
                [*silence_to_speech_ranges(silences, context.media.duration), *silences]
            )
            reason = "silence + speech"
        else:
            ranges = silence_to_speech_ranges(silences, context.media.duration)
            reason = "speech between pauses"

        segments = [
            Segment(
                start=max(0.0, start - pad),
                end=min(context.media.duration, end + pad),
                source=self.source,
                reason=reason,
            )
            for start, end in ranges
            if end - start > 0.05
        ]
        if not segments:
            raise SplitPlanError("Everything in this file registered as silence.")
        return self._finish(
            context,
            segments,
            notes=[
                f"{len(silences)} pauses at {threshold:g} dB, "
                f"{len(segments)} clips with {pad:g}s padding."
            ],
        )


def parse_silence_ranges(stderr: str, duration: float) -> list[tuple[float, float]]:
    """Parse ``silencedetect`` output into ``(start, end)`` silent ranges.

    A trailing ``silence_start`` with no matching end means the file fades out into
    silence, so the range is closed at the media duration.
    """
    starts: list[float] = []
    ends: list[float] = []
    for line in stderr.splitlines():
        start_match = _START_RE.search(line)
        if start_match:
            starts.append(max(0.0, float(start_match.group(1))))
        end_match = _END_RE.search(line)
        if end_match:
            ends.append(min(duration, float(end_match.group(1))))

    ranges: list[tuple[float, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        if end > start:
            ranges.append((round(start, 3), round(end, 3)))
    return ranges


def silence_to_speech_ranges(
    silences: list[tuple[float, float]], duration: float
) -> list[tuple[float, float]]:
    """Invert silent ranges into the spoken ranges between them."""
    speech: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in sorted(silences):
        if start - cursor > 0.05:
            speech.append((round(cursor, 3), round(start, 3)))
        cursor = max(cursor, end)
    if duration - cursor > 0.05:
        speech.append((round(cursor, 3), round(duration, 3)))
    return speech
