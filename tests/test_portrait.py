"""Portrait reframing fallbacks."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from dripcut.engines.video.portrait import build_tracked_crop


def test_tracking_falls_back_when_cv2_is_incomplete(monkeypatch, tmp_path) -> None:
    """A partial OpenCV install should not stop portrait exports."""
    monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace())

    analysis = build_tracked_crop(tmp_path / "clip.mp4", 30.0)

    assert analysis.has_tracking is False
    assert analysis.crop.width
