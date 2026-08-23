"""Resilient YouTube imports built on supported yt-dlp extraction strategies."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from dripcut.core.errors import DependencyError, MediaDownloadError, ValidationError
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.utils.fs import ensure_dir

__all__ = [
    "YouTubeDiagnostics",
    "YouTubeImportError",
    "YouTubeImportResult",
    "YouTubeImportService",
    "YouTubeMetadata",
    "YouTubeService",
]

_log = get_logger("services.youtube")
_MP4_FORMAT = (
    "bv*[height<=1080][vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/"
    "b[height<=1080][vcodec^=avc1][ext=mp4]/"
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
    "b[height<=1080][ext=mp4]/"
    "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]/best"
)
_HLS_FORMAT = "b[protocol^=m3u8][height<=1080]/b[height<=1080]/best[height<=1080]/best"
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

YouTubeErrorCode = Literal[
    "PUBLIC_EXTRACTION_BLOCKED",
    "PRIVATE_VIDEO",
    "LOGIN_REQUIRED",
    "AGE_RESTRICTED",
    "VIDEO_UNAVAILABLE",
    "GEO_RESTRICTED",
    "RATE_LIMITED",
    "DOWNLOAD_FAILED",
]


@dataclass(frozen=True, slots=True)
class YouTubeMetadata:
    video_id: str
    title: str
    duration: float
    channel: str | None
    webpage_url: str


@dataclass(frozen=True, slots=True)
class YouTubeImportResult:
    path: Path
    metadata: YouTubeMetadata
    strategy: str
    format_id: str
    attempts: int
    elapsed: float
    metadata_seconds: float = 0.0
    download_seconds: float = 0.0
    prepare_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class YouTubeDiagnostics:
    yt_dlp_version: str
    ffmpeg_available: bool
    ffprobe_available: bool
    js_runtime: str | None
    js_runtime_version: str | None
    ejs_version: str | None
    po_token_provider_available: bool
    po_token_provider_configured: bool
    cookie_fallback_configured: bool
    proxy_configured: bool
    strategies: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _ExtractionStrategy:
    name: str
    player_client: str | None = None
    use_hls: bool = False
    use_pot_provider: bool = False
    use_cookies: bool = False


class YouTubeImportError(MediaDownloadError):
    """A normalized YouTube failure safe to return through product APIs."""

    def __init__(
        self,
        code: YouTubeErrorCode,
        message: str,
        *,
        hint: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, hint=hint)
        self.code = code
        self.retryable = retryable


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _javascript_runtimes() -> dict[str, dict[str, str]]:
    """Return the first supported yt-dlp runtime available on this host."""
    candidates = {
        "deno": ("deno", "/opt/homebrew/bin/deno", "/usr/local/bin/deno"),
        "node": ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"),
        "quickjs": ("qjs", "/opt/homebrew/bin/qjs", "/usr/local/bin/qjs"),
    }
    for name, paths in candidates.items():
        executable = shutil.which(paths[0])
        if executable is None:
            executable = next((path for path in paths[1:] if Path(path).is_file()), None)
        if executable:
            return {name: {"path": executable}}
    return {}


def _runtime_version(runtimes: dict[str, dict[str, str]]) -> tuple[str | None, str | None]:
    if not runtimes:
        return None, None
    name, config = next(iter(runtimes.items()))
    executable = config["path"]
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        version = (completed.stdout or completed.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        version = None
    return name, version


def _safe_detail(error: Exception | str) -> str:
    detail = str(error).strip()
    detail = _URL_PATTERN.sub("<redacted-url>", detail)
    return detail[:1200]


def _normalize_error(error: Exception) -> YouTubeImportError:
    detail = str(error).strip()
    lowered = detail.lower()
    if "private video" in lowered or "this video is private" in lowered:
        return YouTubeImportError("PRIVATE_VIDEO", "This video is private.")
    if "members-only" in lowered or "members only" in lowered or "paid content" in lowered:
        return YouTubeImportError(
            "LOGIN_REQUIRED",
            "This video requires an authorized YouTube session.",
            hint="Members-only and paid videos are not supported by the public importer.",
        )
    if "age-restricted" in lowered or "confirm your age" in lowered:
        return YouTubeImportError(
            "AGE_RESTRICTED",
            "This video has viewing restrictions.",
            hint="Use a public video without age restrictions.",
        )
    if any(value in lowered for value in ("not available in your country", "geo restricted", "geo-restricted")):
        return YouTubeImportError(
            "GEO_RESTRICTED",
            "This video isn't available from the current server region.",
        )
    if "http error 429" in lowered or "too many requests" in lowered or "rate limit" in lowered:
        return YouTubeImportError(
            "RATE_LIMITED",
            "YouTube temporarily limited requests. Please try again shortly.",
            retryable=True,
        )
    if any(
        value in lowered
        for value in (
            "confirm you're not a bot",
            "confirm you’re not a bot",
            "http error 403",
            "missing a po token",
            "po token",
        )
    ):
        return YouTubeImportError(
            "PUBLIC_EXTRACTION_BLOCKED",
            "We couldn't retrieve this public video from YouTube right now.",
            hint="DripCut will retry supported YouTube playback strategies automatically.",
            retryable=True,
        )
    if "sign in" in lowered or "login required" in lowered:
        return YouTubeImportError(
            "LOGIN_REQUIRED",
            "This video requires an authorized YouTube session.",
            hint="If this is an ordinary public video, retry once before using an operator cookie fallback.",
        )
    if any(
        value in lowered
        for value in (
            "video unavailable",
            "this video is unavailable",
            "has been removed",
            "copyright claim",
            "drm protected",
        )
    ):
        return YouTubeImportError("VIDEO_UNAVAILABLE", "This video is unavailable.")
    return YouTubeImportError(
        "DOWNLOAD_FAILED",
        "The video was found but could not be downloaded.",
        hint="Please retry. If the problem continues, use a local video file.",
        retryable=True,
    )


def _download_error(error: Exception) -> MediaDownloadError:
    """Compatibility wrapper retained for existing callers and tests."""
    return _normalize_error(error)


class _YtDlpLogger:
    """Keep verbose extractor diagnostics server-side without leaking signed URLs."""

    def __init__(self, import_id: str, strategy: str) -> None:
        self.import_id = import_id
        self.strategy = strategy

    def debug(self, message: str) -> None:
        if os.environ.get("DRIPCUT_YOUTUBE_VERBOSE") == "1":
            _log.debug("youtube import=%s strategy=%s %s", self.import_id, self.strategy, _safe_detail(message))

    def warning(self, message: str) -> None:
        _log.debug("youtube import=%s strategy=%s warning=%s", self.import_id, self.strategy, _safe_detail(message))

    def error(self, message: str) -> None:
        _log.debug("youtube import=%s strategy=%s error=%s", self.import_id, self.strategy, _safe_detail(message))


class YouTubeImportService:
    """Validate, inspect, download and verify ordinary public YouTube videos."""

    def __init__(self, paths: AppPaths, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.paths = paths
        self._sleep = sleep
        self._preferred_strategy_name: str | None = None
        self._metadata_strategy_name: str | None = None
        diagnostics = self.diagnostics()
        _log.info(
            "YouTube importer ready: yt-dlp=%s js=%s ejs=%s pot=%s cookies=%s proxy=%s",
            diagnostics.yt_dlp_version,
            diagnostics.js_runtime or "unavailable",
            diagnostics.ejs_version or "unavailable",
            "available" if diagnostics.po_token_provider_available else "unavailable",
            "configured" if diagnostics.cookie_fallback_configured else "off",
            "configured" if diagnostics.proxy_configured else "off",
        )

    @staticmethod
    def validate_url(url: str) -> str:
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
        video_id = YouTubeImportService.video_id(value)
        if not video_id:
            raise ValidationError(
                "That YouTube link does not identify a video.",
                hint="Paste a watch, Shorts, embed, or youtu.be video URL.",
            )
        return value

    @staticmethod
    def video_id(url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host == "youtu.be":
            return parsed.path.strip("/").split("/")[0]
        query_id = parse_qs(parsed.query).get("v", [""])[0]
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
        return ""

    def diagnostics(self) -> YouTubeDiagnostics:
        runtimes = _javascript_runtimes()
        runtime, runtime_version = _runtime_version(runtimes)
        cookie_file = self._cookie_file()
        strategies = tuple(strategy.name for strategy in self.select_strategy())
        return YouTubeDiagnostics(
            yt_dlp_version=_distribution_version("yt-dlp") or "unavailable",
            ffmpeg_available=shutil.which("ffmpeg") is not None,
            ffprobe_available=shutil.which("ffprobe") is not None,
            js_runtime=runtime,
            js_runtime_version=runtime_version,
            ejs_version=_distribution_version("yt-dlp-ejs"),
            po_token_provider_available=_distribution_version("bgutil-ytdlp-pot-provider") is not None,
            po_token_provider_configured=bool(os.environ.get("DRIPCUT_YOUTUBE_POT_PROVIDER_URL")),
            cookie_fallback_configured=cookie_file is not None,
            proxy_configured=bool(os.environ.get("DRIPCUT_YOUTUBE_PROXY")),
            strategies=strategies,
        )

    def select_strategy(self) -> list[_ExtractionStrategy]:
        strategies = [_ExtractionStrategy("recommended")]
        provider_url = os.environ.get("DRIPCUT_YOUTUBE_POT_PROVIDER_URL")
        provider_available = _distribution_version("bgutil-ytdlp-pot-provider") is not None
        if provider_url and provider_available:
            strategies.append(
                _ExtractionStrategy("mweb_pot", player_client="mweb", use_pot_provider=True)
            )
        strategies.append(_ExtractionStrategy("web_embedded", player_client="web_embedded"))
        strategies.append(
            _ExtractionStrategy("web_safari_hls", player_client="web_safari", use_hls=True)
        )
        if self._cookie_file() is not None:
            strategies.append(_ExtractionStrategy("authenticated_cookie", use_cookies=True))
        if self._preferred_strategy_name:
            strategies.sort(
                key=lambda strategy: strategy.name != self._preferred_strategy_name
            )
        return strategies

    def fetch_metadata(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        import_id: str | None = None,
    ) -> YouTubeMetadata:
        value = self.validate_url(url)
        resolved_import_id = import_id or uuid4().hex[:12]
        if on_progress:
            on_progress(0.02, "Fetching video information")
        last_error: YouTubeImportError | None = None
        for strategy in self.select_strategy():
            try:
                info = self._extract(
                    value,
                    strategy,
                    resolved_import_id,
                    destination=None,
                    download=False,
                    on_progress=None,
                )
                self._metadata_strategy_name = strategy.name
                return self._metadata(info, value)
            except Exception as error:  # noqa: BLE001 - normalize yt-dlp failures
                normalized = error if isinstance(error, YouTubeImportError) else _normalize_error(error)
                last_error = normalized
                _log.warning(
                    "youtube import=%s video=%s metadata strategy=%s failed=%s detail=%s",
                    resolved_import_id,
                    self.video_id(value),
                    strategy.name,
                    normalized.code,
                    _safe_detail(error),
                )
                if normalized.code in {
                    "PRIVATE_VIDEO",
                    "AGE_RESTRICTED",
                    "VIDEO_UNAVAILABLE",
                    "GEO_RESTRICTED",
                }:
                    raise normalized from error
        raise last_error or YouTubeImportError("DOWNLOAD_FAILED", "YouTube metadata could not be retrieved.")

    def import_video(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> YouTubeImportResult:
        value = self.validate_url(url)
        import_id = uuid4().hex[:12]
        started = time.monotonic()
        metadata = self.fetch_metadata(value, on_progress=on_progress, import_id=import_id)
        metadata_seconds = time.monotonic() - started
        destination = ensure_dir(self.paths.temp / "youtube" / f"{int(time.time())}-{import_id}")
        strategies = self.select_strategy()
        if self._metadata_strategy_name:
            strategies.sort(
                key=lambda strategy: strategy.name != self._metadata_strategy_name
            )
        last_error: YouTubeImportError | None = None
        download_started = time.monotonic()

        for attempt, strategy in enumerate(strategies, start=1):
            attempt_dir = destination / f"attempt-{attempt}-{strategy.name}"
            shutil.rmtree(attempt_dir, ignore_errors=True)
            ensure_dir(attempt_dir)
            if on_progress:
                stage = "Connecting to YouTube" if attempt == 1 else f"Retrying with {strategy.name}"
                on_progress(0.08, stage)
            try:
                info = self._extract(
                    value,
                    strategy,
                    import_id,
                    destination=attempt_dir,
                    download=True,
                    on_progress=on_progress,
                )
                path = self._find_output(attempt_dir)
                download_seconds = time.monotonic() - download_started
                if on_progress:
                    on_progress(0.96, "Preparing video")
                    on_progress(0.98, "Checking downloaded video")
                prepare_started = time.monotonic()
                self._validate_media(path)
                prepare_seconds = time.monotonic() - prepare_started
                format_id = self._format_id(info)
                elapsed = time.monotonic() - started
                self._preferred_strategy_name = strategy.name
                _log.info(
                    "youtube import=%s video=%s strategy=%s format=%s yt-dlp=%s retries=%d elapsed=%.2fs success",
                    import_id,
                    metadata.video_id,
                    strategy.name,
                    format_id,
                    _distribution_version("yt-dlp") or "unknown",
                    attempt - 1,
                    elapsed,
                )
                if on_progress:
                    on_progress(1.0, "Ready")
                return YouTubeImportResult(
                    path=path,
                    metadata=metadata,
                    strategy=strategy.name,
                    format_id=format_id,
                    attempts=attempt,
                    elapsed=elapsed,
                    metadata_seconds=metadata_seconds,
                    download_seconds=download_seconds,
                    prepare_seconds=prepare_seconds,
                )
            except Exception as error:  # noqa: BLE001 - normalize yt-dlp failures
                normalized = error if isinstance(error, YouTubeImportError) else _normalize_error(error)
                last_error = normalized
                _log.warning(
                    "youtube import=%s video=%s strategy=%s yt-dlp=%s retry=%d failed=%s detail=%s",
                    import_id,
                    metadata.video_id,
                    strategy.name,
                    _distribution_version("yt-dlp") or "unknown",
                    attempt - 1,
                    normalized.code,
                    _safe_detail(error),
                )
                if normalized.code in {
                    "PRIVATE_VIDEO",
                    "AGE_RESTRICTED",
                    "VIDEO_UNAVAILABLE",
                    "GEO_RESTRICTED",
                }:
                    raise normalized from error
                if attempt < len(strategies):
                    self._sleep(min(0.75 * attempt, 2.0))

        if last_error and last_error.code == "PUBLIC_EXTRACTION_BLOCKED":
            hint = "A PO-token provider may be required on this server, especially from AWS or other datacenter IPs."
            raise YouTubeImportError(
                last_error.code,
                last_error.message,
                hint=hint,
                retryable=True,
            )
        raise last_error or YouTubeImportError("DOWNLOAD_FAILED", "The YouTube import failed.")

    def download(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> Path:
        """Compatibility entry point used by the desktop pages."""
        return self.import_video(url, on_progress=on_progress).path

    def _extract(
        self,
        url: str,
        strategy: _ExtractionStrategy,
        import_id: str,
        *,
        destination: Path | None,
        download: bool,
        on_progress: Callable[[float, str], None] | None,
    ) -> dict[str, Any]:
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError as error:
            raise DependencyError(
                "YouTube import is not installed.",
                hint="Install DripCut again so the yt-dlp dependency is available.",
            ) from error

        options = self._options(strategy, import_id, destination, on_progress)
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=download)
        except DownloadError as error:
            raise _normalize_error(error) from error
        except YouTubeImportError:
            raise
        except Exception as error:  # noqa: BLE001 - normalize third-party errors
            raise _normalize_error(error) from error
        if not isinstance(info, dict):
            raise YouTubeImportError("DOWNLOAD_FAILED", "YouTube returned no usable video information.")
        return info

    def _options(
        self,
        strategy: _ExtractionStrategy,
        import_id: str,
        destination: Path | None,
        on_progress: Callable[[float, str], None] | None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "noplaylist": True,
            "socket_timeout": self._socket_timeout(),
            "retries": 1,
            "fragment_retries": 2,
            "extractor_retries": 1,
            "concurrent_fragment_downloads": 4,
            "max_filesize": 2 * 1024 * 1024 * 1024,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "logger": _YtDlpLogger(import_id, strategy.name),
            "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        }
        if runtimes := _javascript_runtimes():
            options["js_runtimes"] = runtimes
        if proxy := os.environ.get("DRIPCUT_YOUTUBE_PROXY"):
            options["proxy"] = proxy

        extractor_args: dict[str, dict[str, list[str]]] = {}
        if strategy.player_client:
            extractor_args["youtube"] = {"player_client": [strategy.player_client]}
        if strategy.use_pot_provider:
            provider_url = os.environ.get("DRIPCUT_YOUTUBE_POT_PROVIDER_URL")
            if provider_url:
                extractor_args["youtubepot-bgutilhttp"] = {"base_url": [provider_url]}
        if extractor_args:
            options["extractor_args"] = extractor_args
        if strategy.use_cookies and (cookie_file := self._cookie_file()):
            options["cookiefile"] = str(cookie_file)

        if destination is None:
            options["skip_download"] = True
            return options

        options.update(
            {
                "format": _HLS_FORMAT if strategy.use_hls else _MP4_FORMAT,
                "merge_output_format": "mp4",
                "final_ext": "mp4",
                "outtmpl": str(destination / "%(title).150B-%(id)s.%(ext)s"),
                "writeinfojson": True,
                "postprocessors": [
                    {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                    {"key": "FFmpegMetadata", "add_metadata": True},
                ],
                "progress_hooks": [self._progress_hook(on_progress)],
            }
        )
        return options

    @staticmethod
    def _progress_hook(
        callback: Callable[[float, str], None] | None,
    ) -> Callable[[dict[str, Any]], None]:
        def hook(payload: dict[str, Any]) -> None:
            if callback is None:
                return
            status = str(payload.get("status", ""))
            if status == "finished":
                callback(0.92, "Preparing video")
                return
            if status != "downloading":
                return
            downloaded = float(payload.get("downloaded_bytes") or 0)
            total = float(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
            fraction = downloaded / total if total > 0 else 0.05
            info = payload.get("info_dict") or {}
            vcodec = str(info.get("vcodec") or "none")
            acodec = str(info.get("acodec") or "none")
            stage = "Downloading audio" if vcodec == "none" and acodec != "none" else "Downloading video"
            callback(0.12 + min(max(fraction, 0.0), 1.0) * 0.78, stage)

        return hook

    @staticmethod
    def _metadata(info: dict[str, Any], fallback_url: str) -> YouTubeMetadata:
        video_id = str(info.get("id") or YouTubeImportService.video_id(fallback_url))
        return YouTubeMetadata(
            video_id=video_id,
            title=str(info.get("title") or f"YouTube video {video_id}"),
            duration=float(info.get("duration") or 0),
            channel=str(info.get("channel") or info.get("uploader") or "") or None,
            webpage_url=str(info.get("webpage_url") or fallback_url),
        )

    @staticmethod
    def _format_id(info: dict[str, Any]) -> str:
        requested = info.get("requested_formats") or []
        if requested:
            return "+".join(str(item.get("format_id") or "unknown") for item in requested)
        return str(info.get("format_id") or "unknown")

    @staticmethod
    def _find_output(destination: Path) -> Path:
        candidates = sorted(
            (
                path
                for path in destination.iterdir()
                if path.is_file() and path.suffix.lower() == ".mp4"
            ),
            key=lambda path: path.stat().st_size,
            reverse=True,
        )
        if not candidates or candidates[0].stat().st_size == 0:
            raise YouTubeImportError(
                "DOWNLOAD_FAILED",
                "The download finished without a usable MP4 video.",
                retryable=True,
            )
        return candidates[0]

    @staticmethod
    def _validate_media(path: Path) -> None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise DependencyError(
                "FFprobe is required to verify YouTube imports.",
                hint="Install FFmpeg before importing YouTube videos.",
            )
        try:
            completed = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height:format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise YouTubeImportError("DOWNLOAD_FAILED", "The downloaded video could not be verified.") from error
        try:
            payload = json.loads(completed.stdout or "{}")
            duration = float((payload.get("format") or {}).get("duration") or 0)
            streams = payload.get("streams") or []
        except (TypeError, ValueError, json.JSONDecodeError):
            duration, streams = 0.0, []
        if completed.returncode != 0 or duration <= 0 or not streams:
            _log.warning("downloaded YouTube media failed ffprobe: %s", _safe_detail(completed.stderr))
            raise YouTubeImportError(
                "DOWNLOAD_FAILED",
                "The downloaded video was incomplete or unplayable.",
                hint="DripCut rejected the file before adding it to the project.",
                retryable=True,
            )

    @staticmethod
    def _socket_timeout() -> float:
        try:
            return min(max(float(os.environ.get("DRIPCUT_YOUTUBE_SOCKET_TIMEOUT", "30")), 5), 120)
        except ValueError:
            return 30.0

    @staticmethod
    def _cookie_file() -> Path | None:
        configured = os.environ.get("DRIPCUT_YOUTUBE_COOKIE_FILE")
        if not configured:
            return None
        path = Path(configured).expanduser()
        return path if path.is_file() else None


# Preserve the established container and desktop-page import name.
YouTubeService = YouTubeImportService
