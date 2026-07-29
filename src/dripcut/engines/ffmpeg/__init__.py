"""Thin, typed wrapper around the FFmpeg command-line tools.

DripCut shells out to ``ffmpeg``/``ffprobe`` rather than binding libav because
the CLI is the most stable interface FFmpeg offers, it streams machine-readable
progress, and it keeps heavy work in a separate process that can be killed
instantly when the user cancels - which matters a great deal on 8 GB of RAM.
"""

from __future__ import annotations

from dripcut.engines.ffmpeg.filters import FilterGraph, ScaleMode
from dripcut.engines.ffmpeg.probe import MediaProbe
from dripcut.engines.ffmpeg.runner import FFmpegRunner, ProgressCallback

__all__ = ["FFmpegRunner", "FilterGraph", "MediaProbe", "ProgressCallback", "ScaleMode"]
