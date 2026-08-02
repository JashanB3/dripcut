"""Turn transcripts into subtitle files.

The interesting work is not writing SRT - it is deciding where lines break. Whisper
segments are often too long to read at speed, so segments are re-flowed into caption
cues of at most ``max_chars`` per line and ``max_lines`` lines, split on word
timings so the cue still lines up with the audio.
"""

from __future__ import annotations

from pathlib import Path

from dripcut.core.errors import ValidationError
from dripcut.core.logging import get_logger
from dripcut.engines.subtitle.styles import force_style_string, hex_to_ass_colour
from dripcut.models.subtitle import CaptionStyle, SubtitleFormat
from dripcut.models.transcript import Transcript, TranscriptSegment, Word
from dripcut.utils.fs import ensure_dir
from dripcut.utils.text import wrap_caption

__all__ = ["SubtitleEngine", "Cue"]

_log = get_logger("engines.subtitle")

_MIN_CUE = 0.7  # seconds; anything shorter flashes past unread
_MAX_CUE = 6.0


class Cue:
    """One subtitle event."""

    __slots__ = ("start", "end", "text", "words")

    def __init__(self, start: float, end: float, text: str, words: tuple[Word, ...] = ()) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.words = words

    @property
    def duration(self) -> float:
        """Cue length in seconds."""
        return max(0.0, self.end - self.start)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Cue({self.start:.2f}-{self.end:.2f}: {self.text[:32]!r})"


class SubtitleEngine:
    """Builds SRT, VTT, ASS and plain-text subtitles from a transcript."""

    def build_cues(self, transcript: Transcript, style: CaptionStyle) -> list[Cue]:
        """Re-flow transcript segments into readable cues."""
        cues: list[Cue] = []
        for segment in transcript.segments:
            cues.extend(self._split_segment(segment, style))
        return self._tidy(cues)

    def write(
        self,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        subtitle_format: SubtitleFormat | None = None,
        video_size: tuple[int, int] = (1920, 1080),
        offset: float = 0.0,
    ) -> Path:
        """Write a subtitle file and return its path.

        Args:
            transcript: Source transcript.
            destination: Output path; its suffix picks the format unless
                ``subtitle_format`` is given.
            style: Caption look (only ASS carries it).
            subtitle_format: Explicit format override.
            video_size: Used as the ASS ``PlayRes``, so font sizes scale correctly.
            offset: Seconds to subtract from every cue (for clip-relative subtitles).
        """
        if transcript.is_empty:
            raise ValidationError(
                "There is no transcript to write yet.", hint="Run Transcribe first."
            )
        chosen = subtitle_format or SubtitleFormat(destination.suffix.lstrip(".").lower() or "srt")
        caption_style = style or CaptionStyle()
        cues = self.build_cues(transcript, caption_style)
        if offset:
            cues = [
                Cue(max(0.0, c.start - offset), max(0.05, c.end - offset), c.text, c.words)
                for c in cues
                if c.end > offset
            ]
        ensure_dir(destination.parent)

        if chosen is SubtitleFormat.TXT:
            destination.write_text(
                "\n".join(cue.text.replace("\n", " ") for cue in cues), encoding="utf-8"
            )
            return destination
        if chosen is SubtitleFormat.ASS:
            destination.write_text(
                self._render_ass(cues, caption_style, video_size), encoding="utf-8"
            )
            return destination

        try:
            return self._write_with_pysubs2(cues, destination, chosen)
        except ImportError:
            _log.info("pysubs2 unavailable, writing %s directly", chosen.value)
            text = (
                self._render_srt(cues) if chosen is SubtitleFormat.SRT else self._render_vtt(cues)
            )
            destination.write_text(text, encoding="utf-8")
            return destination

    def force_style(self, style: CaptionStyle) -> str:
        """``force_style`` string for burning a non-ASS file."""
        return force_style_string(style)

    # ----------------------------------------------------------------- internals

    def _split_segment(self, segment: TranscriptSegment, style: CaptionStyle) -> list[Cue]:
        """Break one transcript segment into one or more cues."""
        text = " ".join(segment.text.split())
        if not text:
            return []
        if style.uppercase:
            text = text.upper()
        budget = max(8, style.max_chars * max(1, style.max_lines))
        if len(text) <= budget and segment.duration <= _MAX_CUE:
            return [Cue(segment.start, segment.end, wrap_caption(text, max_chars=style.max_chars,
                                                                 max_lines=style.max_lines),
                        segment.words)]

        words = list(segment.words)
        if not words:
            return self._split_evenly(segment, text, budget, style)

        cues: list[Cue] = []
        bucket: list[Word] = []
        for word in words:
            candidate = " ".join(w.text for w in [*bucket, word])
            too_long = len(candidate) > budget
            too_slow = bucket and (word.end - bucket[0].start) > _MAX_CUE
            if bucket and (too_long or too_slow):
                cues.append(self._cue_from_words(bucket, style))
                bucket = [word]
            else:
                bucket.append(word)
        if bucket:
            cues.append(self._cue_from_words(bucket, style))
        return cues

    def _cue_from_words(self, words: list[Word], style: CaptionStyle) -> Cue:
        """Build a cue from a run of words."""
        text = " ".join(word.text for word in words).strip()
        if style.uppercase:
            text = text.upper()
        return Cue(
            words[0].start,
            max(words[-1].end, words[0].start + _MIN_CUE),
            wrap_caption(text, max_chars=style.max_chars, max_lines=style.max_lines),
            tuple(words),
        )

    @staticmethod
    def _split_evenly(
        segment: TranscriptSegment, text: str, budget: int, style: CaptionStyle
    ) -> list[Cue]:
        """Fallback split when word timings are missing: divide time by characters."""
        chunks: list[str] = []
        current: list[str] = []
        for word in text.split():
            if current and len(" ".join([*current, word])) > budget:
                chunks.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            chunks.append(" ".join(current))
        if not chunks:
            return []
        span = segment.duration / len(chunks)
        return [
            Cue(
                segment.start + index * span,
                segment.start + (index + 1) * span,
                wrap_caption(chunk, max_chars=style.max_chars, max_lines=style.max_lines),
            )
            for index, chunk in enumerate(chunks)
        ]

    @staticmethod
    def _tidy(cues: list[Cue]) -> list[Cue]:
        """Enforce minimum duration and remove overlaps between neighbours."""
        cleaned: list[Cue] = []
        for cue in sorted(cues, key=lambda c: c.start):
            if not cue.text.strip():
                continue
            if cue.duration < _MIN_CUE:
                cue.end = cue.start + _MIN_CUE
            if cleaned and cue.start < cleaned[-1].end:
                previous = cleaned[-1]
                midpoint = max(previous.start + 0.2, (previous.end + cue.start) / 2)
                previous.end = midpoint
                cue.start = midpoint
                if cue.end - cue.start < 0.2:
                    cue.end = cue.start + 0.2
            cleaned.append(cue)
        return cleaned

    @staticmethod
    def _write_with_pysubs2(cues: list[Cue], destination: Path, fmt: SubtitleFormat) -> Path:
        """Write via pysubs2, which handles the format edge cases properly."""
        import pysubs2  # noqa: PLC0415

        subs = pysubs2.SSAFile()
        for cue in cues:
            subs.append(
                pysubs2.SSAEvent(
                    start=pysubs2.make_time(s=cue.start),
                    end=pysubs2.make_time(s=cue.end),
                    text=cue.text.replace("\n", r"\N"),
                )
            )
        subs.save(str(destination), format_=fmt.value)
        return destination

    @staticmethod
    def _render_srt(cues: list[Cue]) -> str:
        """Render SRT by hand (used when pysubs2 is absent)."""
        blocks = []
        for index, cue in enumerate(cues, start=1):
            blocks.append(
                f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}\n"
            )
        return "\n".join(blocks)

    @staticmethod
    def _render_vtt(cues: list[Cue]) -> str:
        """Render WebVTT by hand."""
        body = "\n".join(
            f"{_vtt_time(cue.start)} --> {_vtt_time(cue.end)}\n{cue.text}\n" for cue in cues
        )
        return f"WEBVTT\n\n{body}"

    @staticmethod
    def _render_ass(cues: list[Cue], style: CaptionStyle, video_size: tuple[int, int]) -> str:
        """Render a styled ASS file, optionally with word-level karaoke timing."""
        width, height = video_size
        scaled = style.fitted_to_video(width, height)
        border_style = 3 if scaled.box_opacity > 0 else 1
        header = f"""[Script Info]
; Generated by DripCut
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {width}
PlayResY: {height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: DripCut,{scaled.font_name},{scaled.font_size},{hex_to_ass_colour(scaled.primary_color)},{hex_to_ass_colour(scaled.primary_color, alpha=0.35)},{hex_to_ass_colour(scaled.outline_color)},{hex_to_ass_colour(scaled.back_color, alpha=scaled.box_opacity or 0.0)},{1 if scaled.bold else 0},{1 if scaled.italic else 0},0,0,100,100,{scaled.letter_spacing:g},0,{border_style},{scaled.outline_width:g},{scaled.shadow:g},{scaled.alignment},{scaled.margin_h},{scaled.margin_h},{scaled.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        for cue in cues:
            text = cue.text.replace("\n", r"\N")
            if style.karaoke and cue.words:
                pieces = []
                for word in cue.words:
                    centiseconds = max(1, int(round((word.end - word.start) * 100)))
                    label = word.text.upper() if style.uppercase else word.text
                    pieces.append(rf"{{\k{centiseconds}}}{label}")
                text = " ".join(pieces)
            lines.append(
                f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},DripCut,,0,0,0,,{text}"
            )
        return header + "\n".join(lines) + "\n"


def _srt_time(seconds: float) -> str:
    """``HH:MM:SS,mmm``."""
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}".replace(".", ",")


def _vtt_time(seconds: float) -> str:
    """``HH:MM:SS.mmm``."""
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def _ass_time(seconds: float) -> str:
    """``H:MM:SS.cc`` as ASS requires."""
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):d}:{int(minutes):02d}:{secs:05.2f}"
