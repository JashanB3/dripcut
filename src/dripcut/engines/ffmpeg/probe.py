"""ffprobe wrapper that turns a file into a :class:`MediaInfo`."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dripcut.core.errors import DependencyError, MediaProbeError
from dripcut.core.logging import get_logger
from dripcut.models.media import AudioStream, Chapter, MediaInfo, VideoStream

__all__ = ["MediaProbe"]

_log = get_logger("engines.ffmpeg.probe")


class MediaProbe:
    """Reads technical metadata with ``ffprobe``.

    Results are cached per ``(path, mtime, size)`` so opening the same file from
    the dashboard, the split page and the export queue costs one subprocess.
    """

    def __init__(self, ffprobe_path: str = "ffprobe") -> None:
        self.ffprobe_path = ffprobe_path
        self._cache: dict[tuple[str, int, int], MediaInfo] = {}

    def resolve_binary(self) -> str:
        """Absolute ffprobe path.

        Raises:
            DependencyError: If ffprobe is missing.
        """
        found = shutil.which(self.ffprobe_path)
        if not found:
            raise DependencyError(
                "ffprobe was not found.",
                hint="It ships with FFmpeg. Install with `brew install ffmpeg`.",
            )
        return found

    def available(self) -> bool:
        """True when ffprobe can be executed."""
        return shutil.which(self.ffprobe_path) is not None

    def probe(self, path: str | Path, *, use_cache: bool = True) -> MediaInfo:
        """Describe a media file.

        Args:
            path: File to inspect.
            use_cache: Reuse a previous probe when the file has not changed.

        Returns:
            A fully populated :class:`MediaInfo`.

        Raises:
            MediaProbeError: If the file is missing or not decodable.
        """
        media_path = Path(path).expanduser()
        if not media_path.exists():
            raise MediaProbeError(
                f"{media_path.name} could not be found.",
                hint="Re-import the file - it may have been moved.",
            )
        if not media_path.is_file():
            raise MediaProbeError(f"{media_path.name} is a folder, not a media file.")

        stat = media_path.stat()
        key = (str(media_path.resolve()), int(stat.st_mtime), stat.st_size)
        if use_cache and key in self._cache:
            return self._cache[key]

        payload = self._run(media_path)
        info = self._build(media_path, stat.st_size, payload)
        self._cache[key] = info
        return info

    def clear_cache(self) -> None:
        """Forget every cached probe (used after a destructive in-place edit)."""
        self._cache.clear()

    def keyframe_times(self, path: str | Path) -> tuple[float, ...]:
        """Return video keyframe timestamps used to decide whether fast cuts are safe."""
        media_path = Path(path).expanduser()
        command = [
            self.resolve_binary(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(media_path),
        ]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command, capture_output=True, text=True, timeout=120, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            _log.debug("could not inspect keyframes for %s", media_path.name, exc_info=True)
            return ()
        if proc.returncode != 0:
            return ()
        values: list[float] = []
        for line in proc.stdout.splitlines():
            value = _to_float(line.strip().split(",", maxsplit=1)[0])
            if value >= 0:
                values.append(value)
        return tuple(values)

    # ----------------------------------------------------------------- internals

    def _run(self, path: Path) -> dict[str, Any]:
        """Invoke ffprobe and parse its JSON output."""
        command = [
            self.resolve_binary(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command, capture_output=True, text=True, timeout=60, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaProbeError(
                f"Reading {path.name} timed out.", hint="The file may be on a slow or offline volume."
            ) from exc
        except OSError as exc:  # pragma: no cover - depends on the host
            raise MediaProbeError(
                "DripCut could not inspect this media file.",
                hint="Check that FFprobe is installed and try the file again.",
            ) from exc

        if proc.returncode != 0 or not proc.stdout.strip():
            detail = (proc.stderr or "").strip().splitlines()
            raise MediaProbeError(
                f"{path.name} is not a media file DripCut can read.",
                hint=detail[-1] if detail else "Try converting it to MP4 first.",
            )
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise MediaProbeError(f"ffprobe returned unreadable data for {path.name}.") from exc

    def _build(self, path: Path, size_bytes: int, payload: dict[str, Any]) -> MediaInfo:
        """Map raw ffprobe JSON onto the domain model."""
        fmt = payload.get("format", {})
        streams = payload.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        duration = _to_float(fmt.get("duration"))
        if duration <= 0:
            for stream in streams:
                duration = max(duration, _to_float(stream.get("duration")))
        if duration <= 0:
            for stream in video_streams:
                frames = _to_float(stream.get("nb_frames"))
                fps = _parse_fraction(stream.get("avg_frame_rate", "0/0"))
                if frames and fps:
                    duration = frames / fps
                    break

        video = self._video_stream(video_streams[0]) if video_streams else None
        audio = self._audio_stream(audio_streams[0]) if audio_streams else None

        if video is None and audio is None:
            raise MediaProbeError(
                f"{path.name} has no audio or video track.",
                hint="DripCut needs at least one playable track.",
            )

        chapters = tuple(
            Chapter(
                index=index,
                start=_to_float(chapter.get("start_time")),
                end=_to_float(chapter.get("end_time")),
                title=str((chapter.get("tags") or {}).get("title", "")),
            )
            for index, chapter in enumerate(payload.get("chapters", []))
        )

        return MediaInfo(
            path=path,
            duration=round(duration, 3),
            size_bytes=size_bytes,
            container=(fmt.get("format_name") or path.suffix.lstrip(".")).split(",")[0],
            video=video,
            audio=audio,
            chapters=chapters,
            extra_streams=max(0, len(streams) - len(video_streams) - len(audio_streams)),
            raw=payload,
        )

    @staticmethod
    def _video_stream(stream: dict[str, Any]) -> VideoStream:
        """Build a :class:`VideoStream`, resolving fps and rotation metadata."""
        fps = _parse_fraction(stream.get("avg_frame_rate", "0/0")) or _parse_fraction(
            stream.get("r_frame_rate", "0/0")
        )
        rotation = 0
        for side_data in stream.get("side_data_list", []) or []:
            if "rotation" in side_data:
                rotation = int(_to_float(side_data.get("rotation")))
        tag_rotate = (stream.get("tags") or {}).get("rotate")
        if tag_rotate and not rotation:
            rotation = int(_to_float(tag_rotate))
        return VideoStream(
            index=int(stream.get("index", 0)),
            codec=str(stream.get("codec_name", "unknown")),
            width=int(stream.get("width") or 0),
            height=int(stream.get("height") or 0),
            fps=round(fps or 30.0, 4),
            bit_rate=int(_to_float(stream.get("bit_rate"))) or None,
            pix_fmt=str(stream.get("pix_fmt", "")),
            rotation=rotation,
        )

    @staticmethod
    def _audio_stream(stream: dict[str, Any]) -> AudioStream:
        """Build an :class:`AudioStream`."""
        return AudioStream(
            index=int(stream.get("index", 0)),
            codec=str(stream.get("codec_name", "unknown")),
            channels=int(stream.get("channels") or 0),
            sample_rate=int(_to_float(stream.get("sample_rate"))),
            bit_rate=int(_to_float(stream.get("bit_rate"))) or None,
            language=str((stream.get("tags") or {}).get("language", "")),
        )


def _to_float(value: Any) -> float:
    """Parse a possibly missing ffprobe numeric field."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if result != result else result  # drop NaN


def _parse_fraction(value: Any) -> float:
    """Parse ffprobe's ``30000/1001`` rational strings."""
    text = str(value or "")
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        num, den = _to_float(numerator), _to_float(denominator)
        return num / den if den else 0.0
    return _to_float(text)
