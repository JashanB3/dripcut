"""Transcript analysis: highlights, hooks, titles, chapters, summaries.

Every method here has two paths. The LLM path asks the local model for structured
JSON. The fallback path is a deterministic heuristic that runs in milliseconds with
no model at all. That is deliberate: DripCut must stay useful when Ollama is not
installed, when the model is mid-download, or when a 3B model has an off day.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from dripcut.core.errors import DripCutError
from dripcut.core.logging import get_logger
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.prompts import (
    CHAPTER_PROMPT,
    FOCUS_RUBRICS,
    HIGHLIGHT_PROMPT,
    HOOK_PROMPT,
    SUMMARY_PROMPT,
    SYSTEM_EDITOR,
    TITLE_PROMPT,
)
from dripcut.models.transcript import Transcript, TranscriptSegment
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.text import sentence_case, truncate
from dripcut.utils.timecode import parse_timecode

__all__ = ["Highlight", "Hook", "Chapter", "AnalysisEngine"]

_log = get_logger("engines.ai.analysis")

# Words that tend to open a strong claim, question or reveal.
_HOOK_MARKERS = (
    "here's why", "here is why", "the truth", "nobody tells you", "most people",
    "the mistake", "i was wrong", "what if", "the secret", "the problem",
    "listen", "imagine", "stop", "never", "always", "biggest", "worst", "best",
    "actually", "surprisingly", "the reason", "let me", "look",
)
_LAUGH_MARKERS = ("laugh", "haha", "lol", "hilarious", "joke", "funny", "ridiculous")
_TEACH_MARKERS = (
    "because", "means that", "for example", "the way it works", "step one",
    "first", "second", "third", "so basically", "in other words", "the point is",
    "rule of thumb", "the difference",
)
_SENTENCE_END = re.compile(r"[.!?\u2026]$")


@dataclass(slots=True)
class Highlight:
    """A ranked candidate clip."""

    start: float
    end: float
    title: str = ""
    score: float = 0.0
    reason: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Length in seconds."""
        return max(0.0, self.end - self.start)


@dataclass(slots=True)
class Hook:
    """A strong opening line found in the transcript."""

    time: float
    text: str
    strength: float = 0.0
    why: str = ""


@dataclass(slots=True)
class Chapter:
    """A suggested chapter marker."""

    time: float
    title: str


class AnalysisEngine:
    """Turns a transcript into editorial suggestions."""

    def __init__(self, llm: OllamaClient, *, enabled: bool = True) -> None:
        self.llm = llm
        self.enabled = enabled

    @property
    def model_ready(self) -> bool:
        """True when the configured model is installed and the server is up."""
        return self.enabled and self.llm.is_up() and self.llm.has_model()

    # ---------------------------------------------------------------- highlights

    def find_highlights(
        self,
        transcript: Transcript,
        *,
        target_length: float = 45.0,
        max_clips: int = 8,
        focus: str = "auto",
        min_score: float = 0.35,
        cancel_token: CancelToken | None = None,
    ) -> list[Highlight]:
        """Rank the strongest moments in a transcript.

        Falls back to the heuristic scorer when the model is unavailable or its
        answer cannot be used.
        """
        if transcript.is_empty:
            return []
        min_length = max(4.0, target_length * 0.4)
        max_length = max(min_length + 4.0, target_length * 1.8)

        if self.model_ready:
            try:
                payload = self.llm.generate_json(
                    HIGHLIGHT_PROMPT.format(
                        rubric=FOCUS_RUBRICS.get(focus, FOCUS_RUBRICS["auto"]),
                        max_clips=max_clips,
                        min_length=min_length,
                        max_length=max_length,
                        target_length=target_length,
                        transcript=self._transcript_window(transcript),
                    ),
                    system=SYSTEM_EDITOR,
                    cancel_token=cancel_token,
                )
                highlights = self._parse_highlights(payload, transcript.duration)
                highlights = [h for h in highlights if h.score >= min_score]
                highlights = self._resolve_overlaps(
                    self._clamp_lengths(highlights, min_length, max_length, transcript)
                )
                if highlights:
                    for highlight in highlights:
                        if not highlight.title:
                            highlight.title = self._auto_title(transcript, highlight)
                    return highlights[:max_clips]
                _log.info("model returned no usable highlights, using heuristics")
            except DripCutError as exc:
                _log.info("highlight ranking fell back to heuristics: %s", exc)

        return self.heuristic_highlights(
            transcript,
            target_length=target_length,
            max_clips=max_clips,
            focus=focus,
        )

    def heuristic_highlights(
        self,
        transcript: Transcript,
        *,
        target_length: float = 45.0,
        max_clips: int = 8,
        focus: str = "auto",
    ) -> list[Highlight]:
        """Model-free ranking.

        Builds sentence-aligned windows around the target length and scores each on
        speech density, marker phrases, position in the recording and how cleanly it
        starts and ends. Crude, but it reliably beats cutting every 45 seconds.
        """
        windows = self._build_windows(transcript, target_length)
        if not windows:
            return []
        scored: list[Highlight] = []
        for start, end, segments in windows:
            text = " ".join(s.text for s in segments).strip()
            if len(text.split()) < 8:
                continue
            score = self._score_text(text, focus=focus)
            score += min(0.12, sum(s.wps for s in segments) / max(1, len(segments)) / 40)
            if _SENTENCE_END.search(text):
                score += 0.06
            if start < transcript.duration * 0.08:
                score += 0.04  # openings are usually the pitch
            score = max(0.0, min(0.99, score))
            scored.append(
                Highlight(
                    start=start,
                    end=end,
                    title=sentence_case(truncate(text.split(".")[0], 60)),
                    score=round(score, 3),
                    reason="Ranked without a model: speech density and phrasing.",
                    tags=[focus] if focus != "auto" else [],
                )
            )
        scored.sort(key=lambda h: h.score, reverse=True)
        return self._resolve_overlaps(scored)[:max_clips]

    # --------------------------------------------------------------------- hooks

    def find_hooks(
        self, transcript: Transcript, *, max_hooks: int = 10, cancel_token: CancelToken | None = None
    ) -> list[Hook]:
        """Find scroll-stopping opening lines."""
        if transcript.is_empty:
            return []
        if self.model_ready:
            try:
                payload = self.llm.generate_json(
                    HOOK_PROMPT.format(
                        max_hooks=max_hooks, transcript=self._transcript_window(transcript)
                    ),
                    system=SYSTEM_EDITOR,
                    cancel_token=cancel_token,
                )
                hooks = [
                    Hook(
                        time=_safe_time(item.get("time"), transcript.duration),
                        text=truncate(str(item.get("text", "")).strip(), 160),
                        strength=_safe_score(item.get("strength")),
                        why=truncate(str(item.get("why", "")).strip(), 90),
                    )
                    for item in _as_list(payload, "hooks")
                    if str(item.get("text", "")).strip()
                ]
                if hooks:
                    hooks.sort(key=lambda h: h.strength, reverse=True)
                    return hooks[:max_hooks]
            except DripCutError as exc:
                _log.info("hook detection fell back to heuristics: %s", exc)

        hooks = []
        for segment in transcript.segments:
            lowered = segment.text.lower()
            hits = sum(1 for marker in _HOOK_MARKERS if marker in lowered)
            if segment.text.strip().endswith("?"):
                hits += 1
            if hits:
                hooks.append(
                    Hook(
                        time=segment.start,
                        text=truncate(segment.text.strip(), 160),
                        strength=min(0.95, 0.35 + hits * 0.18),
                        why="Contains a question or a strong claim.",
                    )
                )
        hooks.sort(key=lambda h: h.strength, reverse=True)
        return hooks[:max_hooks]

    # -------------------------------------------------------- titles and summary

    def suggest_titles(
        self, text: str, *, count: int = 5, cancel_token: CancelToken | None = None
    ) -> list[str]:
        """Propose short titles for a clip."""
        cleaned = truncate(" ".join((text or "").split()), 2400)
        if not cleaned:
            return []
        if self.model_ready:
            try:
                payload = self.llm.generate_json(
                    TITLE_PROMPT.format(count=count, text=cleaned),
                    system=SYSTEM_EDITOR,
                    temperature=0.45,
                    cancel_token=cancel_token,
                )
                titles = [
                    truncate(sentence_case(str(item).strip()), 70)
                    for item in _as_list(payload, "titles")
                    if str(item).strip()
                ]
                if titles:
                    return titles[:count]
            except DripCutError as exc:
                _log.info("title generation unavailable: %s", exc)
        first = cleaned.split(".")[0]
        return [sentence_case(truncate(first, 60))] if first else []

    def summarise(
        self, transcript: Transcript, *, cancel_token: CancelToken | None = None
    ) -> dict[str, Any]:
        """Return ``{"summary", "topics", "tone"}`` for the transcript."""
        if transcript.is_empty:
            return {"summary": "", "topics": [], "tone": ""}
        if self.model_ready:
            try:
                payload = self.llm.generate_json(
                    SUMMARY_PROMPT.format(transcript=self._transcript_window(transcript)),
                    system=SYSTEM_EDITOR,
                    cancel_token=cancel_token,
                )
                if isinstance(payload, dict):
                    return {
                        "summary": truncate(str(payload.get("summary", "")).strip(), 400),
                        "topics": [str(t).strip() for t in (payload.get("topics") or [])][:5],
                        "tone": str(payload.get("tone", "")).strip()[:24],
                    }
            except DripCutError as exc:
                _log.info("summary unavailable: %s", exc)
        words = transcript.text.split()
        return {
            "summary": truncate(" ".join(words[:60]), 300),
            "topics": [],
            "tone": "",
        }

    def suggest_chapters(
        self,
        transcript: Transcript,
        *,
        max_chapters: int = 8,
        cancel_token: CancelToken | None = None,
    ) -> list[Chapter]:
        """Propose chapter markers at topic changes."""
        if transcript.is_empty:
            return []
        if self.model_ready:
            try:
                payload = self.llm.generate_json(
                    CHAPTER_PROMPT.format(
                        max_chapters=max_chapters,
                        transcript=self._transcript_window(transcript),
                    ),
                    system=SYSTEM_EDITOR,
                    cancel_token=cancel_token,
                )
                chapters = [
                    Chapter(
                        time=_safe_time(item.get("time"), transcript.duration),
                        title=truncate(sentence_case(str(item.get("title", "")).strip()), 60),
                    )
                    for item in _as_list(payload, "chapters")
                    if str(item.get("title", "")).strip()
                ]
                if chapters:
                    chapters.sort(key=lambda c: c.time)
                    return chapters[:max_chapters]
            except DripCutError as exc:
                _log.info("chapter suggestion unavailable: %s", exc)
        step = max(60.0, transcript.duration / max(1, max_chapters))
        return [
            Chapter(time=index * step, title=f"Part {index + 1}")
            for index in range(min(max_chapters, max(1, int(transcript.duration // step))))
        ]

    # ----------------------------------------------------------------- internals

    @staticmethod
    def _transcript_window(transcript: Transcript, *, max_chars: int = 9000) -> str:
        """Timecoded transcript trimmed to fit a small context window."""
        text = transcript.numbered_lines()
        if len(text) <= max_chars:
            return text
        # Keep the opening and the middle: endings are usually sign-offs.
        head = text[: int(max_chars * 0.6)]
        middle_start = len(text) // 2
        middle = text[middle_start : middle_start + int(max_chars * 0.4)]
        return f"{head}\n[... transcript trimmed ...]\n{middle}"

    @staticmethod
    def _parse_highlights(payload: Any, duration: float) -> list[Highlight]:
        """Map model JSON onto :class:`Highlight` values, discarding junk."""
        highlights: list[Highlight] = []
        for item in _as_list(payload, "clips"):
            if not isinstance(item, dict):
                continue
            start = _safe_time(item.get("start"), duration)
            end = _safe_time(item.get("end"), duration)
            if end - start < 1.0:
                continue
            highlights.append(
                Highlight(
                    start=start,
                    end=end,
                    title=truncate(sentence_case(str(item.get("title", "")).strip()), 70),
                    score=_safe_score(item.get("score")),
                    reason=truncate(str(item.get("reason", "")).strip(), 100),
                    tags=[str(tag).strip()[:20] for tag in (item.get("tags") or [])][:4],
                )
            )
        return highlights

    @staticmethod
    def _clamp_lengths(
        highlights: Sequence[Highlight],
        min_length: float,
        max_length: float,
        transcript: Transcript,
    ) -> list[Highlight]:
        """Grow or trim clips to the allowed length, snapping to sentence ends."""
        result: list[Highlight] = []
        for highlight in highlights:
            start, end = highlight.start, highlight.end
            if end - start > max_length:
                end = start + max_length
                snapped = _snap_to_sentence_end(transcript, start, end)
                end = snapped if snapped > start + min_length else end
            if end - start < min_length:
                end = min(transcript.duration, start + min_length)
            if end - start < 1.0:
                continue
            highlight.start, highlight.end = start, end
            result.append(highlight)
        return result

    @staticmethod
    def _resolve_overlaps(highlights: Sequence[Highlight]) -> list[Highlight]:
        """Drop lower-scored clips that overlap a better one by more than 25%."""
        kept: list[Highlight] = []
        for highlight in sorted(highlights, key=lambda h: h.score, reverse=True):
            clash = False
            for existing in kept:
                overlap = min(existing.end, highlight.end) - max(existing.start, highlight.start)
                if overlap > 0.25 * min(existing.duration, highlight.duration):
                    clash = True
                    break
            if not clash:
                kept.append(highlight)
        kept.sort(key=lambda h: h.score, reverse=True)
        return kept

    @staticmethod
    def _build_windows(
        transcript: Transcript, target_length: float
    ) -> list[tuple[float, float, list[TranscriptSegment]]]:
        """Sentence-aligned candidate windows around the target length."""
        windows: list[tuple[float, float, list[TranscriptSegment]]] = []
        segments = transcript.segments
        for index, segment in enumerate(segments):
            bucket: list[TranscriptSegment] = []
            end = segment.start
            for candidate in segments[index:]:
                bucket.append(candidate)
                end = candidate.end
                if end - segment.start >= target_length:
                    break
            if end - segment.start >= max(4.0, target_length * 0.5):
                windows.append((segment.start, end, bucket))
        # Stride the windows so neighbours are not near-duplicates.
        stride = max(1, int(math.ceil(len(windows) / 60)))
        return windows[::stride]

    @staticmethod
    def _score_text(text: str, *, focus: str = "auto") -> float:
        """Heuristic clip-worthiness in ``[0, 1)``."""
        lowered = text.lower()
        score = 0.28
        marker_sets = {
            "funny": _LAUGH_MARKERS,
            "educational": _TEACH_MARKERS,
            "hooks": _HOOK_MARKERS,
            "quotes": _HOOK_MARKERS,
        }
        markers = marker_sets.get(focus, _HOOK_MARKERS + _TEACH_MARKERS)
        score += min(0.34, sum(0.07 for marker in markers if marker in lowered))
        if "?" in text:
            score += 0.05
        if any(char.isdigit() for char in text):
            score += 0.04
        words = text.split()
        if 25 <= len(words) <= 160:
            score += 0.08
        return score

    @staticmethod
    def _auto_title(transcript: Transcript, highlight: Highlight) -> str:
        """First sentence of the clip, used when the model omits a title."""
        text = transcript.text_between(highlight.start, highlight.end)
        return sentence_case(truncate(text.split(".")[0], 60)) if text else "Highlight"


def _as_list(payload: Any, key: str) -> list[Any]:
    """Pull a list out of a model response that may be wrapped or bare."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        for candidate in payload.values():
            if isinstance(candidate, list):
                return candidate
    return []


def _safe_time(value: Any, duration: float) -> float:
    """Parse a model-supplied timecode, clamped to the media."""
    try:
        seconds = parse_timecode(value if value is not None else 0)
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, min(seconds, duration if duration > 0 else seconds))


def _safe_score(value: Any) -> float:
    """Parse a confidence value, accepting 0-1 or 0-100."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    if score > 1.0:
        score /= 100.0
    return max(0.0, min(1.0, score))


def _snap_to_sentence_end(transcript: Transcript, start: float, end: float) -> float:
    """Move ``end`` back to the nearest sentence boundary inside the window."""
    best = end
    for segment in transcript.slice(start, end + 2.0):
        if segment.end <= end + 1.5 and _SENTENCE_END.search(segment.text.strip()):
            best = segment.end
    return best
