"""FFmpeg layer: filter construction, encoder choice, and probing."""

from __future__ import annotations

import pytest

from dripcut.engines.ffmpeg.filters import (
    FilterGraph,
    ScaleMode,
    crop_filter,
    even_dimensions,
    fps_filter,
    pad_to_aspect,
    rotate_filters,
    scale_filter,
    subtitle_filter,
    watermark_overlay,
)
from dripcut.engines.ffmpeg.probe import MediaProbe
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.engines.video.encode import AudioMode, EncodeSettings, Quality
from tests.conftest import needs_ffmpeg


@pytest.mark.parametrize(
    ("size", "expected"),
    [((101, 57), (100, 56)), ((100, 56), (100, 56)), ((7, 3), (6, 2))],
)
def test_even_dimensions(size: tuple[int, int], expected: tuple[int, int]) -> None:
    """Encoders reject odd dimensions in yuv420p, so both axes are rounded down."""
    assert even_dimensions(*size) == expected


def test_scale_filter_modes_differ() -> None:
    fit = scale_filter(1080, 1920, mode=ScaleMode.FIT)
    fill = scale_filter(1080, 1920, mode=ScaleMode.FILL)
    assert any("1080" in part and "1920" in part for part in fit)
    assert fit != fill
    assert any("pad=" in part for part in fit), "fit letterboxes to the exact frame"


def test_crop_and_rotate() -> None:
    assert crop_filter(10, 20, 100, 200).startswith("crop=")
    assert rotate_filters(90) and rotate_filters(0) == []
    assert rotate_filters(180) != rotate_filters(270)


def test_fps_filter_smooth_uses_interpolation() -> None:
    assert fps_filter(30) == ["fps=30"]
    assert "minterpolate" in " ".join(fps_filter(60, smooth=True))


def test_pad_to_aspect_escapes_commas() -> None:
    """Commas inside an expression must be escaped or FFmpeg reads them as separators."""
    parts = pad_to_aspect("9:16")
    padding = next(part for part in parts if part.startswith("pad="))
    assert "\\," in padding


def test_watermark_overlay_positions() -> None:
    filters, overlay = watermark_overlay("top-left", opacity=0.5)
    assert "colorchannelmixer=aa=0.500" in " ".join(filters)
    assert overlay.startswith("overlay=")
    assert watermark_overlay("bottom-right")[1] != overlay


def test_subtitle_filter_escapes_paths() -> None:
    rendered = subtitle_filter("/tmp/my subs: odd.ass")
    assert rendered.startswith("subtitles=")
    assert "\\:" in rendered or "'" in rendered


def test_filter_graph_renders_and_dedupes() -> None:
    graph = FilterGraph()
    assert graph.as_args() == []
    graph.add("scale=100:-2")
    graph.extend(["fps=30"])
    assert graph.as_args() == ["-vf", "scale=100:-2,fps=30"]


def test_encode_settings_stream_copy() -> None:
    args = EncodeSettings(audio_mode=AudioMode.COPY, stream_copy=True).build_args(
        video_encoder="libx264", has_audio=True
    )
    assert "copy" in args


@pytest.mark.parametrize("quality", list(Quality))
def test_encode_settings_every_quality(quality: Quality) -> None:
    args = EncodeSettings(quality=quality).build_args(video_encoder="libx264", has_audio=True)
    assert "-c:v" in args and "libx264" in args
    assert isinstance(quality.crf, int)


def test_videotoolbox_uses_quality_not_crf() -> None:
    args = EncodeSettings().build_args(video_encoder="h264_videotoolbox", has_audio=False)
    assert "-crf" not in args, "VideoToolbox takes -q:v, not -crf"


def test_muted_output_has_no_audio_codec() -> None:
    args = EncodeSettings(audio_mode=AudioMode.MUTE).build_args(
        video_encoder="libx264", has_audio=True
    )
    assert "-an" in args


@needs_ffmpeg
def test_runner_reports_a_version() -> None:
    assert "ffmpeg" in FFmpegRunner("ffmpeg").version().lower()


@needs_ffmpeg
def test_runner_picks_a_usable_encoder() -> None:
    runner = FFmpegRunner("ffmpeg")
    chosen = runner.pick_video_encoder("h264")
    assert chosen in runner.available_encoders()


@needs_ffmpeg
def test_probe_reads_the_sample(sample_video) -> None:
    info = MediaProbe("ffprobe").probe(sample_video)
    assert info.has_video and info.has_audio
    assert 5.5 < info.duration < 6.5
    assert info.video.width == 160


@needs_ffmpeg
def test_probe_caches_by_path(sample_video) -> None:
    probe = MediaProbe("ffprobe")
    assert probe.probe(sample_video) is probe.probe(sample_video)


@needs_ffmpeg
def test_probe_rejects_a_missing_file(tmp_path) -> None:
    from dripcut.core.errors import MediaProbeError

    with pytest.raises(MediaProbeError):
        MediaProbe("ffprobe").probe(tmp_path / "nope.mp4")
