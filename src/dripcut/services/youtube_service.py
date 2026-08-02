"""Download a single YouTube video into DripCut's temporary workspace."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from dripcut.core.errors import DependencyError, MediaDownloadError, ValidationError
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.utils.fs import ensure_dir

__all__ = ["YouTubeService"]

_log = get_logger("services.youtube")
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


def _javascript_runtimes() -> dict[str, dict[str, str]]:
    """Return a yt-dlp runtime config that also works from a macOS app bundle."""
    candidates = {
        "node": ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"),
        "deno": ("deno", "/opt/homebrew/bin/deno", "/usr/local/bin/deno"),
        "bun": ("bun", "/opt/homebrew/bin/bun", "/usr/local/bin/bun"),
    }
    for name, paths in candidates.items():
        executable = shutil.which(paths[0])
        if executable is None:
            executable = next((path for path in paths[1:] if Path(path).is_file()), None)
        if executable:
            return {name: {"path": executable}}
    return {}


def _download_error(error: Exception) -> MediaDownloadError:
    """Translate common provider failures without hiding the useful reason."""
    detail = str(error).strip()
    lowered = detail.lower()
    if "sign in" in lowered or "age-restricted" in lowered or "confirm your age" in lowered:
        hint = "This video requires a YouTube sign-in. Try a public, unrestricted video."
    elif "private video" in lowered:
        hint = "Private videos cannot be imported. Use a public or unlisted video you can access."
    elif "copyright" in lowered or "not available in your country" in lowered:
        hint = "The video is unavailable in this region. Try another permitted video."
    elif "requested format is not available" in lowered:
        hint = "YouTube did not offer a compatible format. Try again or choose another video."
    else:
        hint = "Check that the link is public, available in your region, and not age-restricted."
    return MediaDownloadError("YouTube could not provide this video.", hint=hint)


class YouTubeService:
    """Fetch one user-authorised YouTube video for the normal media pipeline."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @staticmethod
    def validate_url(url: str) -> str:
        """Return a normalized YouTube URL or raise a readable validation error."""
        value = (url or "").strip()
        if not value:
            raise ValidationError("Paste a YouTube video link first.")
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
        if parsed.scheme not in {"http", "https"} or not allowed:
            raise ValidationError(
                "That is not a supported YouTube link.",
                hint="Use a youtube.com or youtu.be video URL.",
            )
        return value

    def download(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> Path:
        """Download one video and return its final local path."""
        value = self.validate_url(url)
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError as error:
            raise DependencyError(
                "YouTube import is not installed.",
                hint="Install DripCut again so the yt-dlp dependency is available.",
            ) from error

        destination = ensure_dir(
            self.paths.temp / "youtube" / f"{int(time.time())}-{uuid4().hex[:8]}"
        )

        def progress_hook(payload: dict[str, Any]) -> None:
            if on_progress is None:
                return
            status = str(payload.get("status", ""))
            if status == "finished":
                on_progress(0.98, "Preparing video")
                return
            if status != "downloading":
                return
            downloaded = float(payload.get("downloaded_bytes") or 0)
            total = float(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
            fraction = downloaded / total if total > 0 else 0.05
            on_progress(min(max(fraction, 0.01), 0.95), "Downloading from YouTube")

        options: dict[str, Any] = {
            "format": (
                "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
                "b[height<=1080][ext=mp4]/"
                "bv*[height<=1080]+ba/b[height<=1080]/best"
            ),
            "merge_output_format": "mp4",
            "outtmpl": str(destination / "%(title).150B-%(id)s.%(ext)s"),
            "noplaylist": True,
            "max_filesize": 2 * 1024 * 1024 * 1024,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
            "concurrent_fragment_downloads": 4,
            "extractor_retries": 3,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [progress_hook],
        }
        if runtimes := _javascript_runtimes():
            options["js_runtimes"] = runtimes
        try:
            if on_progress is not None:
                on_progress(0.01, "Reading YouTube video")
            with YoutubeDL(options) as downloader:
                downloader.download([value])
        except DownloadError as error:
            _log.warning("YouTube download failed: %s", error)
            raise _download_error(error) from error
        except Exception as error:  # noqa: BLE001 - normalize third-party errors
            _log.exception("unexpected YouTube download failure")
            raise MediaDownloadError(
                "The YouTube download stopped unexpectedly.",
                hint="Check your connection and try again.",
            ) from error

        candidates = sorted(
            (
                path
                for path in destination.iterdir()
                if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES
            ),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not candidates:
            raise MediaDownloadError(
                "The download finished without a usable video file.",
                hint="Try another public YouTube video.",
            )
        if on_progress is not None:
            on_progress(1.0, "Video ready")
        return candidates[0]
