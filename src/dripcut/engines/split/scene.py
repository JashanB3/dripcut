"""Scene-change split, backed by PySceneDetect with an FFmpeg fallback."""

from __future__ import annotations

from dripcut.core.errors import SplitPlanError
from dripcut.core.logging import get_logger
from dripcut.engines.split.base import SplitContext, SplitStrategy, cut_points_to_segments
from dripcut.models.clip import Segment, SegmentSource, SplitMode, SplitPlan

__all__ = ["SceneSplit", "detect_scenes_pyscenedetect", "parse_showinfo_scores"]

_log = get_logger("engines.split.scene")


class SceneSplit(SplitStrategy):
    """Cut where the picture changes.

    Detection runs on a downscaled copy of the frames rather than full resolution:
    on an M1 Air that is roughly four times faster and the cut positions are
    identical to within a frame.

    Parameters
    ----------
    threshold
        Content-detector sensitivity. Lower finds more cuts (default 27).
    min_scene_seconds
        Shortest scene to report (default 1.0).
    downscale
        Analysis downscale factor; 0 lets PySceneDetect choose.
    """

    mode = SplitMode.SCENE
    source = SegmentSource.SCENE

    def plan(self, context: SplitContext) -> SplitPlan:
        """Detect scene boundaries and turn them into segments."""
        if not context.media.has_video:
            raise SplitPlanError("Scene detection needs a video track.")
        threshold = float(context.param("threshold", 27.0))
        min_scene = float(context.param("min_scene_seconds", 1.0))
        downscale = int(context.param("downscale", 0))
        context.report(0.05, "Scanning for scene changes")

        try:
            ranges = detect_scenes_pyscenedetect(
                str(context.media.path),
                threshold=threshold,
                min_scene_seconds=min_scene,
                fps=context.media.fps,
                downscale=downscale,
                cancel_token=context.cancel_token,
                on_progress=context.on_progress,
            )
            detector = "PySceneDetect"
        except ImportError:
            _log.info("PySceneDetect unavailable, falling back to FFmpeg scene scores")
            ranges = self._ffmpeg_fallback(context, threshold)
            detector = "FFmpeg"

        context.check_cancelled()
        if not ranges:
            raise SplitPlanError(
                "No scene changes were found.",
                hint=f"Lower the threshold below {threshold:g} or use Fixed length.",
            )
        segments = [
            Segment(start=start, end=end, source=self.source, reason="scene change")
            for start, end in ranges
            if end > start
        ]
        return self._finish(
            context,
            segments,
            notes=[f"{len(segments)} scenes detected with {detector} at threshold {threshold:g}."],
        )

    def _ffmpeg_fallback(self, context: SplitContext, threshold: float) -> list[tuple[float, float]]:
        """Use FFmpeg's ``select=gt(scene,...)`` when PySceneDetect is missing."""
        runner = context.services.get("runner")
        if runner is None:
            raise SplitPlanError("Scene detection is unavailable in this install.")
        # FFmpeg scene scores are 0-1; PySceneDetect thresholds are 0-100.
        scene_score = max(0.05, min(0.95, threshold / 100.0))
        stderr = runner.probe_stderr(
            [
                "-i", str(context.media.path),
                "-vf", f"select='gt(scene,{scene_score:.3f})',showinfo",
                "-an", "-f", "null", "-",
            ]
        )
        points = parse_showinfo_scores(stderr)
        segments = cut_points_to_segments(points, context.media.duration, source=self.source)
        return [(s.start, s.end) for s in segments]


def detect_scenes_pyscenedetect(
    path: str,
    *,
    threshold: float = 27.0,
    min_scene_seconds: float = 1.0,
    fps: float = 30.0,
    downscale: int = 0,
    cancel_token: object | None = None,
    on_progress: object | None = None,
) -> list[tuple[float, float]]:
    """Detect scenes and return ``(start, end)`` pairs in seconds.

    Raises:
        ImportError: When PySceneDetect is not installed.
    """
    from scenedetect import ContentDetector, SceneManager, open_video  # noqa: PLC0415

    video = open_video(path)
    if downscale > 0:
        video.set_downscale_factor(downscale)
    else:
        video.set_downscale_factor()  # PySceneDetect picks a sane factor
    manager = SceneManager()
    manager.add_detector(
        ContentDetector(
            threshold=threshold,
            min_scene_len=max(1, int(round(min_scene_seconds * max(fps, 1.0)))),
        )
    )

    def _callback(_frame: object, frame_num: int) -> None:
        """Report progress and honour cancellation during the scan."""
        if cancel_token is not None and getattr(cancel_token, "cancelled", False):
            raise KeyboardInterrupt
        if callable(on_progress) and frame_num % 120 == 0:
            total = max(1.0, video.duration.get_frames() if video.duration else 1.0)
            on_progress(min(0.9, frame_num / total), "Scanning for scene changes")

    try:
        manager.detect_scenes(video=video, callback=_callback, show_progress=False)
    except KeyboardInterrupt:
        return []
    return [(start.get_seconds(), end.get_seconds()) for start, end in manager.get_scene_list()]


def parse_showinfo_scores(stderr: str) -> list[float]:
    """Extract ``pts_time`` values from FFmpeg ``showinfo`` output."""
    points: list[float] = []
    for line in stderr.splitlines():
        marker = "pts_time:"
        if marker not in line:
            continue
        tail = line.split(marker, 1)[1]
        token = tail.split()[0] if tail.split() else ""
        try:
            value = float(token)
        except ValueError:
            continue
        if value > 0.2:
            points.append(round(value, 3))
    return sorted(set(points))
