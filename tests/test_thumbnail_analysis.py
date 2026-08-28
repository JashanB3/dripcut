"""Objective thumbnail frame quality tests."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from dripcut.engines.ai.thumbnail import inspect_frame, usable_frames


def test_frame_quality_rejects_flat_frame_when_sharp_option_exists(tmp_path: Path) -> None:
    flat_path = tmp_path / "flat.jpg"
    sharp_path = tmp_path / "sharp.jpg"
    flat = np.full((240, 320, 3), 128, dtype=np.uint8)
    sharp = np.zeros((240, 320, 3), dtype=np.uint8)
    sharp[:, ::8] = 255
    sharp[::8, :] = 255
    assert cv2.imwrite(str(flat_path), flat)
    assert cv2.imwrite(str(sharp_path), sharp)

    flat_quality = inspect_frame(flat_path, 1.0)
    sharp_quality = inspect_frame(sharp_path, 2.0)

    assert flat_quality is not None
    assert sharp_quality is not None
    assert sharp_quality.sharpness > flat_quality.sharpness
    assert usable_frames([flat_quality, sharp_quality], limit=1) == [sharp_quality]
