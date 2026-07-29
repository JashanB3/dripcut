"""AI layer: the transcript model, caching, prompts, and graceful degradation.

Whisper model weights cannot be downloaded in CI and no Ollama server runs here,
so the transcription and LLM round trips are *not* covered. What is covered is
everything that decides whether those round trips are attempted, and what happens
when they cannot be.
"""

from __future__ import annotations

import json

import pytest

from dripcut.engines.ai import prompts
from dripcut.engines.ai.analysis import AnalysisEngine, Chapter, Highlight, Hook
from dripcut.engines.ai.llm import OllamaClient
from dripcut.models.transcript import Transcript, TranscriptSegment, Word

DEAD_HOST = "http://127.0.0.1:9"  # discard port: never listening


@pytest.fixture
def transcript() -> Transcript:
    """A short transcript with word timings."""
    return Transcript(
        source="/tmp/talk.mp4",
        language="en",
        duration=12.0,
        segments=[
            TranscriptSegment(
                index=0, start=0.0, end=4.0,
                text="Here is the single most important thing about editing video",
                words=[Word(text="Here", start=0.0, end=0.4, probability=0.99)],
            ),
            TranscriptSegment(index=1, start=4.0, end=8.0, text="The secret is to cut earlier"),
            TranscriptSegment(index=2, start=8.0, end=12.0, text="And that is the whole trick"),
        ],
    )


# ------------------------------------------------------------------- transcript


def test_text_joins_every_segment(transcript: Transcript) -> None:
    assert "single most important" in transcript.text
    assert "whole trick" in transcript.text


def test_word_count_is_positive(transcript: Transcript) -> None:
    assert transcript.word_count > 10


def test_empty_transcript_is_flagged() -> None:
    assert Transcript(source="x", language="", duration=0.0, segments=[]).is_empty


def test_segment_at_finds_the_right_one(transcript: Transcript) -> None:
    assert transcript.segment_at(5.0).index == 1


def test_slice_returns_only_the_window(transcript: Transcript) -> None:
    """slice() returns the overlapping segments, not a new Transcript."""
    segments = transcript.slice(4.0, 8.0)
    assert segments
    assert all(segment.end > 4.0 and segment.start < 8.0 for segment in segments)


def test_text_between_is_narrower_than_the_whole(transcript: Transcript) -> None:
    assert len(transcript.text_between(0.0, 4.0)) < len(transcript.text)


def test_rebased_makes_timings_clip_relative(transcript: Transcript) -> None:
    """Timings shift by -offset and clamp at zero, so a clip starts at 00:00."""
    rebased = transcript.rebased(4.0)
    assert rebased.segments[0].start == pytest.approx(0.0)
    assert rebased.segments[1].start == pytest.approx(0.0)
    assert rebased.segments[2].start == pytest.approx(4.0)


def test_numbered_lines_carry_an_index_and_timecode(transcript: Transcript) -> None:
    """numbered_lines() returns one printable block for prompting and review."""
    rendered = transcript.numbered_lines()
    lines = rendered.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("[0000]") and "00:00:00" in lines[0]


def test_save_and_load_round_trip(transcript: Transcript, tmp_path) -> None:
    target = tmp_path / "t.json"
    transcript.save(target)
    assert json.loads(target.read_text(encoding="utf-8"))["language"] == "en"
    assert Transcript.load(target).word_count == transcript.word_count


# ---------------------------------------------------------------------- service


def test_status_reports_every_flag(container) -> None:
    status = container.ai.status()
    assert {
        "enabled", "whisper_installed", "whisper_model",
        "ollama_up", "ollama_model", "ollama_model_installed",
    } <= set(status)


def test_disabling_ai_is_respected(container) -> None:
    container.settings.ai.enable_ai = False
    assert container.ai.enabled is False
    assert container.ai.prepare() is False


def test_cache_path_is_stable(container, sample_video) -> None:
    first = container.ai.cache_path(sample_video)
    assert first == container.ai.cache_path(sample_video)
    assert container.settings.ai.whisper_model.replace(".", "_") in first.name


def test_cache_path_changes_with_the_model(container, sample_video) -> None:
    before = container.ai.cache_path(sample_video)
    container.settings.ai.whisper_model = "medium"
    assert container.ai.cache_path(sample_video) != before


def test_missing_cache_returns_none(container, sample_video) -> None:
    assert container.ai.cached_transcript(sample_video) is None


def test_cached_transcript_is_reused(container, sample_video, transcript) -> None:
    transcript.save(container.ai.cache_path(sample_video))
    loaded = container.ai.cached_transcript(sample_video)
    assert loaded is not None and loaded.word_count == transcript.word_count


def test_unreadable_cache_is_ignored(container, sample_video) -> None:
    container.ai.cache_path(sample_video).write_text("{broken", encoding="utf-8")
    assert container.ai.cached_transcript(sample_video) is None


# ---------------------------------------------------------------------- prompts


@pytest.mark.parametrize(
    "name",
    ["HIGHLIGHT_PROMPT", "HOOK_PROMPT", "TITLE_PROMPT", "SUMMARY_PROMPT", "CHAPTER_PROMPT"],
)
def test_prompts_demand_json(name: str) -> None:
    body = getattr(prompts, name)
    assert body.strip()
    assert "json" in body.lower(), "every prompt must pin the model to JSON output"


def test_focus_rubrics_cover_the_ui_choices() -> None:
    assert {"auto", "hooks", "funny", "educational", "story", "quotes"} <= set(
        prompts.FOCUS_RUBRICS
    )


# ------------------------------------------------------------- degradation path


def test_client_reports_a_dead_server() -> None:
    assert OllamaClient(DEAD_HOST, model="nothing", timeout=2).is_up() is False


def test_analysis_knows_it_is_not_ready() -> None:
    engine = AnalysisEngine(OllamaClient(DEAD_HOST, model="nothing", timeout=2), enabled=True)
    assert engine.model_ready is False


def test_highlights_fall_back_to_heuristics(transcript: Transcript) -> None:
    """With no model reachable, analysis must still return usable spans."""
    engine = AnalysisEngine(OllamaClient(DEAD_HOST, model="nothing", timeout=2), enabled=True)
    found = engine.find_highlights(transcript, target_length=4.0, max_clips=2)
    assert isinstance(found, list)
    for item in found:
        assert isinstance(item, Highlight)
        assert 0.0 <= item.start < item.end <= transcript.duration + 0.01


def test_disabled_analysis_returns_nothing(transcript: Transcript) -> None:
    engine = AnalysisEngine(OllamaClient(DEAD_HOST, model="nothing", timeout=2), enabled=False)
    assert engine.find_highlights(transcript) == []


def test_dataclasses_are_shaped_as_the_ui_expects() -> None:
    highlight = Highlight(start=0.0, end=1.0, title="t", score=0.5, reason="r")
    assert highlight.score == 0.5
    assert Hook(time=1.0, text="t", strength=0.4, why="w").why == "w"
    assert Chapter(time=0.0, title="Intro").title == "Intro"
