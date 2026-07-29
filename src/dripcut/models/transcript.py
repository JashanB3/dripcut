"""Transcript model: words, segments and the operations captions rely on."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dripcut.utils.timecode import format_timecode

__all__ = ["Word", "TranscriptSegment", "Transcript"]


@dataclass(frozen=True, slots=True)
class Word:
    """A single word with timing, used for word-level caption highlighting."""

    text: str
    start: float
    end: float
    probability: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 3),
        }


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A Whisper segment: one utterance-sized chunk of speech."""

    index: int
    start: float
    end: float
    text: str
    words: tuple[Word, ...] = ()
    no_speech_prob: float = 0.0

    @property
    def duration(self) -> float:
        """Segment length in seconds."""
        return max(0.0, self.end - self.start)

    @property
    def wps(self) -> float:
        """Words per second - a cheap proxy for energy when ranking clips."""
        words = len(self.text.split())
        return words / self.duration if self.duration > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return {
            "index": self.index,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "no_speech_prob": round(self.no_speech_prob, 4),
            "words": [word.to_dict() for word in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptSegment:
        """Rebuild from cached JSON."""
        return cls(
            index=int(data.get("index", 0)),
            start=float(data["start"]),
            end=float(data["end"]),
            text=str(data.get("text", "")),
            words=tuple(
                Word(
                    text=str(w.get("text", "")),
                    start=float(w.get("start", data["start"])),
                    end=float(w.get("end", data["end"])),
                    probability=float(w.get("probability", 1.0)),
                )
                for w in data.get("words", [])
            ),
            no_speech_prob=float(data.get("no_speech_prob", 0.0)),
        )


@dataclass(slots=True)
class Transcript:
    """A full transcription, cached next to the project so it is computed once."""

    source: Path
    language: str
    duration: float
    segments: list[TranscriptSegment] = field(default_factory=list)
    model: str = ""
    created_at: float = 0.0

    @property
    def text(self) -> str:
        """Whole transcript as flowing prose."""
        return " ".join(segment.text.strip() for segment in self.segments).strip()

    @property
    def word_count(self) -> int:
        """Total words across every segment."""
        return sum(len(segment.text.split()) for segment in self.segments)

    @property
    def words(self) -> list[Word]:
        """Flattened word timings across every segment."""
        return [word for segment in self.segments for word in segment.words]

    @property
    def is_empty(self) -> bool:
        """True when nothing intelligible was found."""
        return not self.segments or not self.text

    def segment_at(self, seconds: float) -> TranscriptSegment | None:
        """Segment covering ``seconds``, if any."""
        for segment in self.segments:
            if segment.start <= seconds < segment.end:
                return segment
        return None

    def slice(self, start: float, end: float) -> list[TranscriptSegment]:
        """Segments overlapping the ``[start, end)`` window."""
        return [s for s in self.segments if s.end > start and s.start < end]

    def text_between(self, start: float, end: float) -> str:
        """Spoken text inside a window, used to caption and title a clip."""
        return " ".join(s.text.strip() for s in self.slice(start, end)).strip()

    def rebased(self, offset: float) -> Transcript:
        """Return a copy with all timings shifted by ``-offset`` (clip-relative)."""
        shifted: list[TranscriptSegment] = []
        for index, segment in enumerate(self.segments):
            shifted.append(
                TranscriptSegment(
                    index=index,
                    start=max(0.0, segment.start - offset),
                    end=max(0.0, segment.end - offset),
                    text=segment.text,
                    words=tuple(
                        Word(w.text, max(0.0, w.start - offset), max(0.0, w.end - offset), w.probability)
                        for w in segment.words
                    ),
                    no_speech_prob=segment.no_speech_prob,
                )
            )
        return Transcript(
            source=self.source,
            language=self.language,
            duration=self.duration,
            segments=shifted,
            model=self.model,
            created_at=self.created_at,
        )

    def numbered_lines(self, *, limit: int | None = None) -> str:
        """Timecoded plain-text view used by the transcript viewer and LLM prompts."""
        rows = self.segments if limit is None else self.segments[:limit]
        return "\n".join(
            f"[{segment.index:04d}] {format_timecode(segment.start, millis=False)} "
            f"-> {format_timecode(segment.end, millis=False)}  {segment.text.strip()}"
            for segment in rows
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation."""
        return {
            "source": str(self.source),
            "language": self.language,
            "duration": round(self.duration, 3),
            "model": self.model,
            "created_at": self.created_at,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        """Rebuild from cached JSON."""
        return cls(
            source=Path(data.get("source", "")),
            language=str(data.get("language", "")),
            duration=float(data.get("duration", 0.0)),
            segments=[TranscriptSegment.from_dict(item) for item in data.get("segments", [])],
            model=str(data.get("model", "")),
            created_at=float(data.get("created_at", 0.0)),
        )

    def save(self, path: Path) -> Path:
        """Write the transcript cache atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path: Path) -> Transcript:
        """Read a transcript cache written by :meth:`save`."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
