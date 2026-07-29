"""The split strategy contract plus shared segment post-processing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dripcut.core.errors import SplitPlanError
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.models.media import MediaInfo
from dripcut.models.transcript import Transcript
from dripcut.utils.concurrency import CancelToken

__all__ = ["SplitContext", "SplitStrategy", "cut_points_to_segments", "enforce_bounds"]


@dataclass(slots=True)
class SplitContext:
    """Everything a strategy may need, injected rather than imported.

    ``transcript`` and ``analyse`` are optional so a strategy can ask for AI help
    if it is available without any strategy depending on the AI engine directly.
    """

    media: MediaInfo
    parameters: dict[str, Any] = field(default_factory=dict)
    transcript: Transcript | None = None
    cancel_token: CancelToken | None = None
    on_progress: Any = None
    services: dict[str, Any] = field(default_factory=dict)

    def param(self, key: str, default: Any = None) -> Any:
        """Read a parameter with a fallback."""
        value = self.parameters.get(key, default)
        return default if value is None else value

    def report(self, fraction: float, stage: str) -> None:
        """Forward progress if a callback was supplied."""
        if callable(self.on_progress):
            self.on_progress(fraction, stage)

    def check_cancelled(self) -> None:
        """Raise if the caller asked to stop."""
        if self.cancel_token is not None:
            self.cancel_token.raise_if_cancelled()


class SplitStrategy(ABC):
    """Base class for every split mode."""

    mode: SplitMode
    source: SegmentSource = SegmentSource.MANUAL
    requires_audio: bool = False
    requires_ai: bool = False

    @abstractmethod
    def plan(self, context: SplitContext) -> SplitPlan:
        """Compute the segments this mode would render.

        Implementations must not encode anything - planning is expected to be fast
        enough to run while the user is still choosing options.
        """

    # ------------------------------------------------------------------ helpers

    def _finish(
        self,
        context: SplitContext,
        segments: Sequence[Segment],
        *,
        notes: Sequence[str] = (),
    ) -> SplitPlan:
        """Validate, renumber and wrap segments into a plan."""
        cleaned = enforce_bounds(
            segments,
            duration=context.media.duration,
            min_duration=float(context.param("min_duration", 0.4)),
            merge_short=bool(context.param("merge_short", True)),
        )
        if not cleaned:
            raise SplitPlanError(
                "This mode found nothing to cut.",
                hint="Loosen the settings or try a different split mode.",
            )
        limit = int(context.param("max_clips", 0) or 0)
        if limit and len(cleaned) > limit:
            cleaned = cleaned[:limit]
            notes = [*notes, f"Trimmed to the first {limit} clips."]
        renumbered = tuple(
            Segment(
                start=segment.start,
                end=segment.end,
                index=index,
                title=segment.title,
                source=segment.source,
                score=segment.score,
                reason=segment.reason,
                tags=segment.tags,
                id=segment.id,
            )
            for index, segment in enumerate(cleaned, start=1)
        )
        return SplitPlan(
            source=context.media.path,
            mode=self.mode,
            segments=renumbered,
            parameters=dict(context.parameters),
            notes=tuple(notes),
        )


def cut_points_to_segments(
    points: Sequence[float],
    duration: float,
    *,
    source: SegmentSource,
    include_head: bool = True,
) -> list[Segment]:
    """Turn a list of cut positions into contiguous segments.

    Args:
        points: Positions in seconds where a cut should happen.
        duration: Total media duration.
        source: Provenance recorded on each produced segment.
        include_head: Emit the region before the first cut point.
    """
    ordered = sorted({round(max(0.0, min(p, duration)), 3) for p in points})
    boundaries = [0.0, *ordered, duration] if include_head else [*ordered, duration]
    segments: list[Segment] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        if end - start > 0.01:
            segments.append(Segment(start=start, end=end, source=source))
    return segments


def enforce_bounds(
    segments: Sequence[Segment],
    *,
    duration: float,
    min_duration: float = 0.4,
    merge_short: bool = True,
) -> list[Segment]:
    """Clamp segments to the media and deal with slivers.

    Slivers are the single biggest source of "why did I get 400 clips" surprise, so
    by default a too-short segment is merged into its neighbour rather than dropped
    - the footage stays, the clip count stays sane.
    """
    clamped: list[Segment] = []
    for segment in segments:
        start = max(0.0, min(segment.start, duration))
        end = max(start + 0.01, min(segment.end, duration))
        if end - start < 0.01:
            continue
        clamped.append(
            Segment(
                start=start,
                end=end,
                index=segment.index,
                title=segment.title,
                source=segment.source,
                score=segment.score,
                reason=segment.reason,
                tags=segment.tags,
                id=segment.id,
            )
        )
    if not clamped:
        return []

    clamped.sort(key=lambda s: s.start)
    result: list[Segment] = []
    for segment in clamped:
        if segment.duration >= min_duration or not result:
            result.append(segment)
            continue
        if merge_short:
            previous = result[-1]
            result[-1] = Segment(
                start=previous.start,
                end=max(previous.end, segment.end),
                index=previous.index,
                title=previous.title,
                source=previous.source,
                score=max(previous.score, segment.score),
                reason=previous.reason,
                tags=previous.tags,
                id=previous.id,
            )
    return [s for s in result if s.duration >= min(min_duration, 0.05)]
