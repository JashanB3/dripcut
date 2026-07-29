"""AI highlight split: transcribe, rank, keep the strongest moments.

Pipeline
--------
1. Whisper produces a timed transcript (cached per file).
2. The transcript is chunked into candidate windows on sentence boundaries.
3. A local LLM scores each candidate for hook strength, payoff and standalone
   clarity, returning strict JSON.
4. If the model is unavailable or replies with nonsense, a deterministic heuristic
   scorer takes over so the feature never hard-fails offline.
"""

from __future__ import annotations

from dripcut.core.errors import SplitPlanError
from dripcut.core.logging import get_logger
from dripcut.engines.split.base import SplitContext, SplitStrategy
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.utils.text import truncate

__all__ = ["AIHighlightSplit"]

_log = get_logger("engines.split.ai")


class AIHighlightSplit(SplitStrategy):
    """Keep only the moments worth posting.

    Parameters
    ----------
    target_length
        Preferred clip length in seconds (default 45).
    max_clips
        How many highlights to keep (default 8).
    focus
        ``auto``, ``hooks``, ``funny``, ``educational``, ``story`` or ``quotes``.
    min_score
        Discard candidates the model scored below this (0-1).
    pad_before / pad_after
        Extra seconds kept around each highlight.
    """

    mode = SplitMode.AI_HIGHLIGHT
    source = SegmentSource.AI
    requires_audio = True
    requires_ai = True

    def plan(self, context: SplitContext) -> SplitPlan:
        """Transcribe, rank and return the winning segments."""
        ai_service = context.services.get("ai")
        if ai_service is None:
            raise SplitPlanError(
                "AI features are switched off.",
                hint="Enable them in Settings, then check `dripcut doctor`.",
            )
        if not context.media.has_audio:
            raise SplitPlanError(
                "AI highlights need spoken audio.",
                hint="For silent footage use Scene changes.",
            )

        target_length = float(context.param("target_length", 45.0))
        max_clips = int(context.param("max_clips", 8))
        focus = str(context.param("focus", "auto"))
        min_score = float(context.param("min_score", 0.35))
        pad_before = float(context.param("pad_before", 0.35))
        pad_after = float(context.param("pad_after", 0.6))

        transcript = context.transcript
        if transcript is None:
            context.report(0.05, "Transcribing")
            transcript = ai_service.transcribe(
                context.media.path,
                on_progress=lambda f, s="Transcribing": context.report(0.05 + f * 0.55, s),
                cancel_token=context.cancel_token,
            )
        if transcript is None or transcript.is_empty:
            raise SplitPlanError(
                "No speech was found in this file.",
                hint="Try Silence gaps or Scene changes instead.",
            )

        context.check_cancelled()
        context.report(0.65, "Ranking moments")
        highlights = ai_service.find_highlights(
            transcript,
            target_length=target_length,
            max_clips=max_clips,
            focus=focus,
            min_score=min_score,
            cancel_token=context.cancel_token,
        )
        if not highlights:
            raise SplitPlanError(
                "The model did not find a strong moment.",
                hint="Lower the minimum score or raise the clip count.",
            )

        context.report(0.95, "Building the plan")
        segments = [
            Segment(
                start=max(0.0, highlight.start - pad_before),
                end=min(context.media.duration, highlight.end + pad_after),
                title=truncate(highlight.title, 70),
                source=self.source,
                score=highlight.score,
                reason=truncate(highlight.reason, 90),
                tags=tuple(highlight.tags),
            )
            for highlight in highlights
        ]
        # Highlights are ranked, not chronological: order by score for review,
        # then the plan renumbers so file names follow the ranking.
        segments.sort(key=lambda s: s.score, reverse=True)
        return self._finish(
            context,
            segments,
            notes=[
                f"{len(segments)} highlights from {transcript.word_count} words "
                f"({focus} focus, model {transcript.model or 'whisper'})."
            ],
        )
