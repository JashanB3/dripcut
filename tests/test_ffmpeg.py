"""FFmpeg layer: filter construction, encoder choice, and probing."""

from __future__ import annotations

import io

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


def test_nvenc_uses_constant_quality_not_software_crf() -> None:
    args = EncodeSettings(quality=Quality.BALANCED).build_args(
        video_encoder="h264_nvenc", has_audio=False
    )
    assert "-cq:v" in args
    assert "-crf" not in args
    assert args[args.index("-preset") + 1] == "p4"


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


def test_runner_picks_nvenc_when_videotoolbox_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        FFmpegRunner,
        "available_encoders",
        lambda self: frozenset({"h264_nvenc", "libx264", "aac"}),
    )
    runner = FFmpegRunner("ffmpeg", hardware_accel=True)
    assert runner.pick_video_encoder("h264") == "h264_nvenc"


def test_runner_respects_hardware_disabled_with_nvenc(monkeypatch) -> None:
    monkeypatch.setattr(
        FFmpegRunner,
        "available_encoders",
        lambda self: frozenset({"h264_nvenc", "libx264", "aac"}),
    )
    runner = FFmpegRunner("ffmpeg", hardware_accel=False)
    assert runner.pick_video_encoder("h264") == "libx264"


def test_runner_retries_with_software_encoder(monkeypatch) -> None:
    from dripcut.engines.ffmpeg import runner as runner_mod

    calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("Unknown encoder 'h264_videotoolbox'\n")

        def poll(self) -> int:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        return FakeProcess(1 if len(calls) == 1 else 0)

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(FFmpegRunner, "resolve_binary", lambda self: "ffmpeg")
    monkeypatch.setattr(FFmpegRunner, "_pump_progress", lambda *args, **kwargs: False)

    runner = FFmpegRunner("ffmpeg", hardware_accel=True)
    result = runner.run(
        [
            "-i",
            "input.mp4",
            "-c:v",
            "h264_videotoolbox",
            "-q:v",
            "62",
            "-allow_sw",
            "1",
            "-c:a",
            "aac",
            "output.mp4",
        ]
    )

    assert result.returncode == 0
    assert len(calls) == 2
    assert "h264_videotoolbox" in calls[0]
    assert "libx264" in calls[1]
    assert "-q:v" not in calls[1]
    assert "-allow_sw" not in calls[1]


def test_runner_retries_nvenc_with_software_encoder(monkeypatch) -> None:
    from dripcut.engines.ffmpeg import runner as runner_mod

    calls: list[list[str]] = []

    class FakeProcess:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("Error initializing output stream with h264_nvenc\n")

        def poll(self) -> int:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            return self.returncode

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            return None

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        return FakeProcess(1 if len(calls) == 1 else 0)

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(FFmpegRunner, "resolve_binary", lambda self: "ffmpeg")
    monkeypatch.setattr(FFmpegRunner, "_pump_progress", lambda *args, **kwargs: False)

    runner = FFmpegRunner("ffmpeg", hardware_accel=True)
    result = runner.run(
        [
            "-i",
            "input.mp4",
            "-c:v",
            "h264_nvenc",
            "-cq:v",
            "23",
            "-preset",
            "p4",
            "-c:a",
            "aac",
            "output.mp4",
        ]
    )

    assert result.returncode == 0
    assert len(calls) == 2
    assert "h264_nvenc" in calls[0]
    assert "libx264" in calls[1]
    assert "-cq:v" not in calls[1]
    assert "p4" not in calls[1]


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
