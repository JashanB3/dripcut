"""Chapter split: use the markers already embedded in the container."""

from __future__ import annotations

from dripcut.core.errors import SplitPlanError
from dripcut.engines.split.base import SplitContext, SplitStrategy
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from dripcut.utils.text import truncate

__all__ = ["ChapterSplit"]


class ChapterSplit(SplitStrategy):
    """One clip per chapter marker.

    Parameters
    ----------
    use_titles
        Name each clip after its chapter title (default true).
    """

    mode = SplitMode.CHAPTERS
    source = SegmentSource.CHAPTER

    def plan(self, context: SplitContext) -> SplitPlan:
        """Read chapters from the probe result."""
        chapters = context.media.chapters
        if not chapters:
            raise SplitPlanError(
                f"{context.media.name} has no chapter markers.",
                hint="Try Scene changes or Fixed length instead.",
            )
        use_titles = bool(context.param("use_titles", True))
        segments = [
            Segment(
                start=chapter.start,
                end=chapter.end if chapter.end > chapter.start else context.media.duration,
                title=truncate(chapter.title, 60) if use_titles else "",
                source=self.source,
                reason="chapter marker",
            )
            for chapter in chapters
            if (chapter.end or context.media.duration) > chapter.start
        ]
        return self._finish(
            context, segments, notes=[f"{len(segments)} chapters found in the file."]
        )
