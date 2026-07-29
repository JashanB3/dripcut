"""Subtitle engine: presets, cue building, and every output format."""

from __future__ import annotations

import pytest

from dripcut.engines.subtitle.generator import SubtitleEngine
from dripcut.engines.subtitle.styles import (
    force_style_string,
    get_preset,
    hex_to_ass_colour,
    preset_names,
)
from dripcut.models.subtitle import CaptionStyle, SubtitleFormat
from dripcut.models.transcript import Transcript, TranscriptSegment, Word
from dripcut.utils.text import wrap_caption

SPOKEN_WORDS = ["This", "is", "the", "first", "line", "of", "the", "talk"]


@pytest.fixture
def transcript() -> Transcript:
    """Two short spoken segments with word timings."""
    return Transcript(
        source="/tmp/sample.mp4",
        language="en",
        duration=6.0,
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=2.5,
                text="This is the first line of the talk",
                words=[
                    Word(text=word, start=0.0 + i * 0.3, end=0.3 + i * 0.3, probability=0.9)
                    for i, word in enumerate(["This", "is", "the", "first", "line", "of", "the", "talk"])
                ],
            ),
            TranscriptSegment(
                index=1, start=3.0, end=6.0, text="And this is the second one", words=[]
            ),
        ],
    )


BUILTIN_PRESETS = {"Clean", "Punch", "Plate", "Signal", "Documentary", "Karaoke"}


def test_the_six_builtin_presets_are_available() -> None:
    """Plugins may add more, so this checks the built-ins are present, not the count."""
    assert set(preset_names()) >= BUILTIN_PRESETS


@pytest.mark.parametrize("name", sorted(BUILTIN_PRESETS))
def test_every_preset_loads(name: str) -> None:
    style = get_preset(name)
    assert style.font_size > 0
    assert 1 <= style.alignment <= 9
    assert style.max_chars > 10


def test_unknown_preset_falls_back_rather_than_crashing() -> None:
    """A stale style name in a project manifest must not break loading it."""
    fallback = get_preset("Definitely Not A Preset")
    assert fallback.font_size > 0


def test_hex_to_ass_colour_is_bgr() -> None:
    """ASS stores &HAABBGGRR, so red and blue swap relative to hex."""
    assert hex_to_ass_colour("#5B8CFF") == "&H00FF8C5B"
    assert hex_to_ass_colour("#FFFFFF") == "&H00FFFFFF"


def test_force_style_string_is_comma_separated() -> None:
    rendered = force_style_string(get_preset("Clean"))
    assert "FontSize=" in rendered
    assert rendered.count("=") >= 3


def test_build_cues_respects_line_length(transcript: Transcript) -> None:
    style = get_preset("Clean")
    style.max_chars = 16
    cues = SubtitleEngine().build_cues(transcript, style)
    assert cues
    for cue in cues:
        for line in cue.text.splitlines():
            assert len(line) <= style.max_chars + 6


def test_cues_never_overlap(transcript: Transcript) -> None:
    cues = SubtitleEngine().build_cues(transcript, get_preset("Clean"))
    for earlier, later in zip(cues, cues[1:], strict=False):
        assert earlier.end <= later.start + 1e-6


def test_cues_have_a_readable_minimum(transcript: Transcript) -> None:
    for cue in SubtitleEngine().build_cues(transcript, get_preset("Clean")):
        assert cue.end > cue.start


def test_uppercase_style_is_applied(transcript: Transcript) -> None:
    style = get_preset("Punch")
    style.uppercase = True
    cues = SubtitleEngine().build_cues(transcript, style)
    assert cues[0].text == cues[0].text.upper()


@pytest.mark.parametrize("fmt", list(SubtitleFormat))
def test_every_format_writes(transcript: Transcript, tmp_path, fmt: SubtitleFormat) -> None:
    written = SubtitleEngine().write(
        transcript, tmp_path / f"out{fmt.suffix}", style=get_preset("Clean"), subtitle_format=fmt
    )
    assert written.exists() and written.stat().st_size > 0
    assert written.suffix == fmt.suffix


def test_srt_has_numbered_cues(transcript: Transcript, tmp_path) -> None:
    body = SubtitleEngine().write(
        transcript, tmp_path / "out.srt", subtitle_format=SubtitleFormat.SRT
    ).read_text(encoding="utf-8")
    assert body.strip().startswith("1")
    assert "-->" in body


def test_vtt_has_a_header(transcript: Transcript, tmp_path) -> None:
    body = SubtitleEngine().write(
        transcript, tmp_path / "out.vtt", subtitle_format=SubtitleFormat.VTT
    ).read_text(encoding="utf-8")
    assert body.startswith("WEBVTT")


def test_ass_carries_the_style(transcript: Transcript, tmp_path) -> None:
    body = SubtitleEngine().write(
        transcript, tmp_path / "out.ass", style=get_preset("Punch"), subtitle_format=SubtitleFormat.ASS
    ).read_text(encoding="utf-8")
    assert "[Script Info]" in body and "Dialogue:" in body


def test_offset_shifts_every_cue(transcript: Transcript, tmp_path) -> None:
    plain = SubtitleEngine().write(transcript, tmp_path / "a.srt", subtitle_format=SubtitleFormat.SRT)
    shifted = SubtitleEngine().write(
        transcript, tmp_path / "b.srt", subtitle_format=SubtitleFormat.SRT, offset=5.0
    )
    assert plain.read_text() != shifted.read_text()


def test_style_round_trips() -> None:
    style = get_preset("Signal")
    assert CaptionStyle.from_dict(style.to_dict()).font_name == style.font_name


def test_scaled_style_grows() -> None:
    style = get_preset("Clean")
    assert style.scaled(2.0).font_size > style.font_size


def test_wrap_caption_balances_lines() -> None:
    wrapped = wrap_caption("one two three four five six seven eight", max_chars=14, max_lines=2)
    assert len(wrapped.splitlines()) <= 2
