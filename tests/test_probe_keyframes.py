"""Keyframe discovery used by the safe stream-copy planner."""

from __future__ import annotations

from pathlib import Path


def test_probe_reports_first_video_keyframe(container, sample_video: Path) -> None:
    keyframes = container.resolve("probe").keyframe_times(sample_video)
    assert keyframes
    assert abs(keyframes[0]) < 0.01
