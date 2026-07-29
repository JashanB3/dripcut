"""Split engine: planning maths, parsing, and rendering through the service."""

from __future__ import annotations

from pathlib import Path

import pytest

from dripcut.core.errors import SplitPlanError, ValidationError
from dripcut.engines.split.base import SplitContext, enforce_bounds
from dripcut.engines.split.registry import build_default_registry
from dripcut.engines.split.silence import parse_silence_ranges, silence_to_speech_ranges
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan
from tests.conftest import needs_ffmpeg


def _plan(media, mode, **parameters) -> SplitPlan:
    registry = build_default_registry()
    return registry.get(mode).plan(SplitContext(media=media, parameters=parameters))


def test_registry_exposes_every_mode() -> None:
    modes = build_default_registry().modes()
    assert set(modes) == set(SplitMode)


@needs_ffmpeg
def test_fixed_split_divides_evenly(media) -> None:
    plan = _plan(media, SplitMode.FIXED, clip_length=2.0)
    assert plan.count == 3
    assert plan.segments[0].start == pytest.approx(0.0)
    assert plan.segments[-1].end == pytest.approx(media.duration, abs=0.05)


@needs_ffmpeg
def test_fixed_split_clamps_the_tail(media) -> None:
    plan = _plan(media, SplitMode.FIXED, clip_length=2.5)
    assert plan.segments[-1].end <= media.duration + 0.01


@needs_ffmpeg
def test_segments_are_numbered_from_one(media) -> None:
    plan = _plan(media, SplitMode.FIXED, clip_length=0.5)
    assert [segment.index for segment in plan.segments] == list(range(1, plan.count + 1))


@needs_ffmpeg
def test_timestamp_split_cuts_where_asked(media) -> None:
    plan = _plan(media, SplitMode.TIMESTAMPS, timestamps="0:01")
    assert plan.count == 2
    assert plan.segments[0].end == pytest.approx(1.0, abs=0.01)


@needs_ffmpeg
def test_timestamp_ranges_are_honoured(media) -> None:
    plan = _plan(media, SplitMode.TIMESTAMPS, ranges="0:00.5-0:01.5")
    assert plan.count == 1
    assert plan.segments[0].duration == pytest.approx(1.0, abs=0.05)


@needs_ffmpeg
def test_chapterless_file_raises(media) -> None:
    with pytest.raises(SplitPlanError):
        _plan(media, SplitMode.CHAPTERS)


@needs_ffmpeg
def test_continuous_tone_has_no_silence(media) -> None:
    """A pure sine never dips below the threshold, so there is nothing to cut on."""
    with pytest.raises(SplitPlanError):
        _plan(media, SplitMode.SILENCE, threshold_db=-32.0, min_silence=0.3)


def test_ai_mode_requires_ai(container, media) -> None:
    container.settings.ai.enable_ai = False
    with pytest.raises(ValidationError):
        container.split.plan(media, SplitMode.AI_HIGHLIGHT)


def test_parse_silence_ranges() -> None:
    stderr = (
        "[silencedetect @ 0x1] silence_start: 10.5\n"
        "[silencedetect @ 0x1] silence_end: 12.0 | silence_duration: 1.5\n"
    )
    assert parse_silence_ranges(stderr, 30.0) == [(10.5, 12.0)]


def test_unterminated_silence_runs_to_the_end() -> None:
    stderr = "[silencedetect @ 0x1] silence_start: 25.0\n"
    ranges = parse_silence_ranges(stderr, 30.0)
    assert ranges and ranges[-1][1] == pytest.approx(30.0)


def test_silence_inverts_to_speech() -> None:
    speech = silence_to_speech_ranges([(10.0, 12.0)], 30.0)
    assert speech == [(0.0, 10.0), (12.0, 30.0)]


def test_silence_at_the_start_is_dropped() -> None:
    assert silence_to_speech_ranges([(0.0, 5.0)], 10.0) == [(5.0, 10.0)]


def test_enforce_bounds_merges_slivers() -> None:
    segments = [
        Segment(start=0.0, end=5.0, index=1),
        Segment(start=5.0, end=5.1, index=2),
        Segment(start=5.1, end=10.0, index=3),
    ]
    kept = enforce_bounds(segments, duration=10.0, min_duration=0.5)
    assert len(kept) < len(segments)
    assert all(segment.duration >= 0.5 for segment in kept)


def test_enforce_bounds_clamps_to_duration() -> None:
    kept = enforce_bounds([Segment(start=0.0, end=99.0, index=1)], duration=10.0)
    assert kept[0].end <= 10.0


def test_output_name_pattern() -> None:
    segment = Segment(start=0.0, end=1.0, index=7)
    assert segment.output_name("clip", ".mp4") == "clip-007.mp4"
    assert segment.output_name("clip", ".mov", pattern="{stem}_{index}") == "clip_7.mov"


def test_display_title_falls_back() -> None:
    assert Segment(start=0, end=1, index=3).display_title("show") == "show-03"
    assert Segment(start=0, end=1, index=3, title="Best bit").display_title("show") == "Best bit"


def test_plan_round_trips_through_json() -> None:
    plan = SplitPlan(
        source=Path("/tmp/x.mp4"),
        mode=SplitMode.FIXED,
        segments=[Segment(start=0.0, end=2.0, index=1, source=SegmentSource.FIXED)],
    )
    restored = SplitPlan.from_dict(plan.to_dict())
    assert restored.count == 1
    assert restored.mode is SplitMode.FIXED
    assert restored.segments[0].duration == pytest.approx(2.0)


@needs_ffmpeg
def test_service_renders_real_clips(container, media, tmp_path) -> None:
    plan = container.split.plan(media, SplitMode.FIXED, {"clip_length": 2.0})
    outputs = container.split.render(plan, tmp_path / "clips", accurate=True)
    assert outputs and all(path.exists() and path.stat().st_size > 0 for path in outputs)
    assert len(outputs) == plan.count


@needs_ffmpeg
def test_render_reports_progress(container, media, tmp_path) -> None:
    seen: list[float] = []
    plan = container.split.plan(media, SplitMode.FIXED, {"clip_length": 2.0})
    container.split.render(
        plan, tmp_path / "clips", on_progress=lambda fraction, _stage: seen.append(fraction)
    )
    assert seen and max(seen) > 0.5


def test_render_rejects_an_empty_plan(container, tmp_path) -> None:
    empty = SplitPlan(source=Path("/tmp/x.mp4"), mode=SplitMode.FIXED, segments=[])
    with pytest.raises(ValidationError):
        container.split.render(empty, tmp_path)
