"""Media import: probe files, build proxies and thumbnails, keep a recents list."""

from __future__ import annotations

import threading
from pathlib import Path

from dripcut.core.config import Settings
from dripcut.core.errors import MediaProbeError, ValidationError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.engines.ffmpeg.probe import MediaProbe
from dripcut.engines.video.engine import VideoEngine
from dripcut.models.media import MediaInfo
from dripcut.utils.fs import ensure_dir, is_media_file

__all__ = ["MediaService"]

_log = get_logger("services.media")


class MediaService:
    """Everything to do with getting a file into DripCut."""

    def __init__(
        self,
        probe: MediaProbe,
        video: VideoEngine,
        events: EventBus,
        settings: Settings,
        paths: AppPaths,
    ) -> None:
        self.probe = probe
        self.video = video
        self.events = events
        self.settings = settings
        self.paths = paths
        self._recent: list[Path] = []
        self._lock = threading.Lock()

    def import_file(self, path: str | Path) -> MediaInfo:
        """Probe a file and record it as recently used.

        Raises:
            ValidationError: If nothing was supplied.
            MediaProbeError: If the file cannot be read.
        """
        if not path:
            raise ValidationError("Choose a video file to get started.")
        media_path = Path(path).expanduser()
        try:
            info = self.probe.probe(media_path)
        except MediaProbeError:
            self.events.publish(EventName.MEDIA_PROBE_FAILED, path=str(media_path))
            raise
        with self._lock:
            self._recent = [media_path, *[p for p in self._recent if p != media_path]][:20]
        self.events.publish(
            EventName.MEDIA_IMPORTED,
            path=str(media_path),
            duration=info.duration,
            has_audio=info.has_audio,
        )
        _log.info("imported %s (%s)", info.name, info.duration_label)
        return info

    def import_folder(self, folder: str | Path, *, recursive: bool = False) -> list[MediaInfo]:
        """Probe every media file in a folder, skipping anything unreadable."""
        directory = Path(folder).expanduser()
        if not directory.is_dir():
            raise ValidationError(f"{directory} is not a folder.")
        pattern = "**/*" if recursive else "*"
        results: list[MediaInfo] = []
        for candidate in sorted(directory.glob(pattern)):
            if candidate.is_file() and is_media_file(candidate):
                try:
                    results.append(self.import_file(candidate))
                except MediaProbeError as exc:
                    _log.info("skipping %s: %s", candidate.name, exc)
        if not results:
            raise ValidationError(
                f"No readable media found in {directory.name}.",
                hint="DripCut looks for common video and audio files.",
            )
        return results

    def recent(self, limit: int = 12) -> list[Path]:
        """Recently imported files that still exist on disk."""
        with self._lock:
            return [path for path in self._recent if path.exists()][:limit]

    def thumbnail_for(self, info: MediaInfo, *, at: float | None = None, width: int = 640) -> Path | None:
        """Return a cached thumbnail, generating it on first request."""
        if not info.has_video:
            return None
        cache_dir = ensure_dir(self.paths.cache / "thumbs")
        stamp = f"{info.stem}-{int(info.duration * 1000)}-{int((at or -1) * 100)}-{width}.jpg"
        target = cache_dir / stamp
        if target.exists():
            return target
        try:
            position = at if at is not None else min(max(1.0, info.duration * 0.1), max(0.5, info.duration - 0.2))
            return self.video.thumbnail(info.path, target, at=position, width=width)
        except Exception:  # noqa: BLE001 - a missing thumbnail must not block import
            _log.debug("thumbnail failed for %s", info.name, exc_info=True)
            return None

    def proxy_for(self, info: MediaInfo, *, force: bool = False) -> Path:
        """Return a small preview copy, building it if needed.

        Anything already small enough is returned unchanged - there is no point
        transcoding a 720p clip to preview it.
        """
        height = info.video.display_resolution[1] if info.video else 0
        if not force and (height and height <= self.settings.video.proxy_height + 80):
            return info.path
        cache_dir = ensure_dir(self.paths.cache / "proxies")
        target = cache_dir / f"{info.stem}-{int(info.size_bytes)}-p{self.settings.video.proxy_height}.mp4"
        if target.exists() and not force:
            return target
        return self.video.make_proxy(info.path, target, height=self.settings.video.proxy_height)

    def waveform_for(self, info: MediaInfo, *, width: int = 1400, height: int = 160) -> Path | None:
        """Render a waveform PNG for the timeline strip."""
        if not info.has_audio:
            return None
        cache_dir = ensure_dir(self.paths.cache / "waveforms")
        target = cache_dir / f"{info.stem}-{int(info.duration * 100)}-{width}x{height}.png"
        if target.exists():
            return target
        try:
            self.video.runner.run(
                [
                    "-i", str(info.path),
                    "-filter_complex",
                    f"showwavespic=s={width}x{height}:colors=0x5B8CFF|0x7A5BFF:split_channels=0",
                    "-frames:v", "1", str(target),
                ],
                outputs=[target],
                stage="Waveform",
            )
            return target
        except Exception:  # noqa: BLE001 - decorative, never fatal
            _log.debug("waveform failed for %s", info.name, exc_info=True)
            return None
