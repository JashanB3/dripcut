"""AI layer: the transcript model, caching, prompts, and graceful degradation.

Whisper model weights cannot be downloaded in CI and no Ollama server runs here,
so the transcription and LLM round trips are *not* covered. What is covered is
everything that decides whether those round trips are attempted, and what happens
when they cannot be.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dripcut.engines.ai import prompts
from dripcut.engines.ai.analysis import AnalysisEngine, Chapter, Highlight, Hook
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.transcription_provider import _normalize_groq_response
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


def test_window_keeps_only_overlapping_content_and_rebases_it() -> None:
    transcript = Transcript(
        source="source.mp4",
        language="en",
        duration=90,
        segments=[
            TranscriptSegment(index=0, start=0, end=20, text="before"),
            TranscriptSegment(
                index=1,
                start=28,
                end=34,
                text="edge words after",
                words=(
                    Word("edge", 28, 29),
                    Word("words", 30, 31),
                    Word("after", 33, 34),
                ),
            ),
            TranscriptSegment(index=2, start=65, end=70, text="too late"),
        ],
    )

    clip = transcript.window(30, 60)

    assert clip.duration == 30
    assert len(clip.segments) == 1
    assert clip.segments[0].text == "words after"
    assert [(word.text, word.start, word.end) for word in clip.words] == [
        ("words", 0, 1),
        ("after", 3, 4),
    ]


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
    provider = container.ai.active_transcription_provider
    first = container.ai.cache_path(sample_video)
    assert first == container.ai.cache_path(sample_video)
    assert provider.name in first.name
    assert provider.model.replace(".", "_") in first.name


def test_cache_path_changes_with_the_model(container, sample_video) -> None:
    provider = container.ai.active_transcription_provider
    before = container.ai.cache_path(sample_video)
    if provider.name == "groq":
        provider.model = "whisper-large-v3"
    else:
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


def test_cache_identity_survives_a_file_rename(container, sample_video, tmp_path) -> None:
    renamed = tmp_path / "a-completely-different-name.mp4"
    shutil.copyfile(sample_video, renamed)

    assert container.ai.cache_path(sample_video) == container.ai.cache_path(renamed)


def test_cache_identity_includes_provider_model_and_language(container, sample_video) -> None:
    class Provider:
        name = "hosted"
        version = "1"
        remote = True

        def __init__(self, model: str) -> None:
            self.model = model

        def available(self) -> bool:
            return True

    first = container.ai.cache_path(sample_video, Provider("model-a"), language="en")
    other_model = container.ai.cache_path(sample_video, Provider("model-b"), language="en")
    other_language = container.ai.cache_path(sample_video, Provider("model-a"), language="hi")

    assert len({first, other_model, other_language}) == 3


def test_remote_transcription_is_normalized_and_cached(container, sample_video) -> None:
    class Provider:
        name = "groq"
        model = "test-whisper"
        version = "1"
        remote = True

        def __init__(self) -> None:
            self.calls = 0

        def available(self) -> bool:
            return True

        def transcribe(self, source: Path, **_kwargs) -> Transcript:
            self.calls += 1
            return Transcript(
                source=source,
                language="en",
                duration=2.0,
                segments=[TranscriptSegment(index=0, start=0, end=2, text="Ready to clip")],
            )

    provider = Provider()
    container.ai.groq_transcription = provider
    container.settings.ai.transcription_provider = "groq"

    first = container.ai.transcribe(sample_video, source_asset_id="asset-123")
    second = container.ai.transcribe(sample_video, source_asset_id="asset-123")

    assert provider.calls == 1
    assert first.provider == "groq"
    assert first.model == "test-whisper"
    assert first.source_asset_id == "asset-123"
    assert first.metadata["cache_hit"] is False
    assert second.metadata["cache_hit"] is True


def test_groq_payload_preserves_word_and_segment_timing(sample_video) -> None:
    transcript = _normalize_groq_response(
        sample_video,
        {
            "language": "en",
            "duration": 2.5,
            "text": "Ready to clip",
            "words": [
                {"word": "Ready", "start": 0.1, "end": 0.6},
                {"word": "to", "start": 0.65, "end": 0.8},
                {"word": "clip", "start": 0.85, "end": 1.2},
            ],
            "segments": [{"text": "Ready to clip", "start": 0.1, "end": 1.2}],
        },
        "whisper-large-v3-turbo",
    )

    assert transcript.duration == 2.5
    assert transcript.provider == "groq"
    assert transcript.model == "whisper-large-v3-turbo"
    assert [(word.text, word.start, word.end) for word in transcript.words] == [
        ("Ready", 0.1, 0.6),
        ("to", 0.65, 0.8),
        ("clip", 0.85, 1.2),
    ]


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
