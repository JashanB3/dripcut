"""Resilient YouTube imports built on supported yt-dlp extraction strategies."""

from __future__ import annotations

import importlib.metadata
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
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
    "bv*[height<=720][vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/"
    "b[height<=720][vcodec^=avc1][ext=mp4]/"
    "bv*[height<=720][ext=mp4]+ba[ext=m4a]/"
    "b[height<=720][ext=mp4]/"
    "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best"
)
_HLS_FORMAT = (
    "b[protocol^=m3u8][height<=720]/b[height<=720]/best[height<=720]/best"
)
_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
_HTTP_STATUS_PATTERN = re.compile(r"(?:HTTP(?: Error)?|status(?: code)?)\D{0,12}(\d{3})", re.IGNORECASE)
_SENSITIVE_DETAIL_PATTERN = re.compile(
    r"\b(?:access[_-]?token|refresh[_-]?token|authorization|cookie|po[_-]?token|"
    r"token|secret|password)\b\s*(?:=|:)\s*(?:Bearer\s+)?[^\s,;|]+",
    re.IGNORECASE,
)
_STRATEGY_LABELS = {
    "browser_cookie": "fresh browser session",
    "generic": "site extractor",
    "web_embedded": "embedded web",
    "mweb_pot": "mweb + PoT",
    "web_safari_hls": "Safari HLS",
    "recommended": "recommended client",
    "authenticated_cookie": "cookies",
}
_BGUTIL_SCRIPT_HOME = Path("/opt/dripcut/bgutil/server")

YouTubeErrorCode = Literal[
    "PUBLIC_EXTRACTION_BLOCKED",
    "BOT_CHALLENGE",
    "PRIVATE_VIDEO",
    "LOGIN_REQUIRED",
    "AGE_RESTRICTED",
    "VIDEO_UNAVAILABLE",
    "GEO_RESTRICTED",
    "REGION_BLOCKED",
    "RATE_LIMITED",
    "FORMAT_UNAVAILABLE",
    "TIMEOUT",
    "DOWNLOAD_FAILED",
    "IMPORT_FAILED",
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
    node_available: bool
    ejs_version: str | None
    js_challenge_support_active: bool
    po_token_provider_available: bool
    po_token_provider_configured: bool
    po_token_provider_mode: str | None
    cookie_fallback_configured: bool
    proxy_configured: bool
    strategies: tuple[str, ...]
    last_successful_strategy: str | None
    last_failure_class: str | None
    last_http_status: int | None
    last_login_required: bool | None
    last_attempted_strategies: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _ExtractionStrategy:
    name: str
    player_client: str | None = None
    use_hls: bool = False
    use_pot_provider: bool = False
    pot_provider_mode: Literal["http", "script"] | None = None
    use_cookies: bool = False
    use_browser_cookies: bool = False


@dataclass(slots=True)
class _ImportRuntimeState:
    last_successful_strategy: str | None = None
    last_failure_class: str | None = None
    last_http_status: int | None = None
    last_login_required: bool | None = None
    last_attempted_strategies: tuple[str, ...] = ()


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


def _node_available() -> bool:
    return bool(
        shutil.which("node")
        or next(
            (
                path
                for path in ("/opt/homebrew/bin/node", "/usr/local/bin/node")
                if Path(path).is_file()
            ),
            None,
        )
    )


def _safe_detail(error: Exception | str) -> str:
    detail = str(error).strip()
    detail = _URL_PATTERN.sub("<redacted-url>", detail)
    detail = _SENSITIVE_DETAIL_PATTERN.sub("<redacted-secret>", detail)
    return detail[:1200]


def _strategy_label(strategy: str) -> str:
    return _STRATEGY_LABELS.get(strategy, strategy)


def _error_chain_detail(error: Exception | str) -> str:
    if isinstance(error, str):
        return error
    details: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(details) < 4:
        seen.add(id(current))
        details.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(details)


def _http_status(error: Exception | str) -> int | None:
    match = _HTTP_STATUS_PATTERN.search(_error_chain_detail(error))
    return int(match.group(1)) if match else None


def _login_required(error: Exception | str, normalized: YouTubeImportError) -> bool:
    lowered = _error_chain_detail(error).lower()
    return normalized.code == "LOGIN_REQUIRED" or "sign in" in lowered or "login required" in lowered


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
            "REGION_BLOCKED",
            "We couldn't import this video from the current processing region.",
            hint="Upload a copy you are allowed to use and continue with the same project.",
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
            "BOT_CHALLENGE",
            "YouTube asked the processing server for additional verification.",
            hint="Retry once, or upload a copy you are allowed to use and continue.",
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
            "requested format is not available",
            "no video formats found",
            "no suitable formats",
            "format is not available",
        )
    ):
        return YouTubeImportError(
            "FORMAT_UNAVAILABLE",
            "YouTube did not offer a compatible video format.",
            hint="Retry once, or upload a copy you are allowed to use and continue.",
            retryable=True,
        )
    if any(value in lowered for value in ("timed out", "timeout", "read operation timed out")):
        return YouTubeImportError(
            "TIMEOUT",
            "YouTube took too long to respond.",
            hint="Retry once. If it still times out, upload the video instead.",
            retryable=True,
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
        "IMPORT_FAILED",
        "The video was found but could not be downloaded.",
        hint="Retry once, or upload a copy you are allowed to use and continue.",
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
    """Validate, inspect, download and verify public video links with yt-dlp."""

    def __init__(self, paths: AppPaths, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.paths = paths
        self._sleep = sleep
        self._state = _ImportRuntimeState()
        self._state_lock = threading.Lock()
        diagnostics = self.diagnostics()
        _log.info(
            "YouTube importer ready: yt-dlp=%s js=%s ejs=%s pot_available=%s pot_configured=%s cookies=%s proxy=%s",
            diagnostics.yt_dlp_version,
            diagnostics.js_runtime or "unavailable",
            diagnostics.ejs_version or "unavailable",
            "available" if diagnostics.po_token_provider_available else "unavailable",
            "yes" if diagnostics.po_token_provider_configured else "no",
            "configured" if diagnostics.cookie_fallback_configured else "off",
            "configured" if diagnostics.proxy_configured else "off",
        )

    @staticmethod
    def validate_video_url(url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise ValidationError("Paste a public video link first.")
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or host == "localhost"
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValidationError(
                "That is not a supported public video link.",
                hint="Use a public http or https page that contains a video.",
            )
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            }
        except socket.gaierror as error:
            raise ValidationError(
                "That video website could not be reached.",
                hint="Check the link and try again.",
            ) from error
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValidationError("Private or local network video links are not supported.")
        if YouTubeImportService.is_youtube_url(value):
            video_id = YouTubeImportService.video_id(value)
            if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", video_id):
                raise ValidationError(
                    "That YouTube link does not identify a video.",
                    hint="Paste a watch, Shorts, embed, or youtu.be video URL.",
                )
        return value

    @staticmethod
    def validate_url(url: str) -> str:
        """Preserve the legacy YouTube-only validation contract."""
        value = (url or "").strip()
        if not value:
            raise ValidationError("Paste a YouTube video link first.")
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not YouTubeImportService.is_youtube_url(value)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ValidationError(
                "That is not a supported YouTube link.",
                hint="Use a youtube.com or youtu.be video URL.",
            )
        video_id = YouTubeImportService.video_id(value)
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", video_id):
            raise ValidationError(
                "That YouTube link does not identify a video.",
                hint="Paste a watch, Shorts, embed, or youtu.be video URL.",
            )
        return value

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")

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
        if YouTubeImportService.is_youtube_url(url):
            return ""
        fallback = re.sub(
            r"[^A-Za-z0-9_-]+", "-", f"{host}-{parsed.path.strip('/')}"
        ).strip("-")
        return fallback[:64] or host[:64]

    def diagnostics(self) -> YouTubeDiagnostics:
        runtimes = _javascript_runtimes()
        runtime, runtime_version = _runtime_version(runtimes)
        cookie_file = self._cookie_file()
        strategies = tuple(strategy.name for strategy in self.select_strategy())
        ejs_version = _distribution_version("yt-dlp-ejs")
        with self._state_lock:
            state = _ImportRuntimeState(**asdict(self._state))
        return YouTubeDiagnostics(
            yt_dlp_version=_distribution_version("yt-dlp") or "unavailable",
            ffmpeg_available=shutil.which("ffmpeg") is not None,
            ffprobe_available=shutil.which("ffprobe") is not None,
            js_runtime=runtime,
            js_runtime_version=runtime_version,
            node_available=_node_available(),
            ejs_version=ejs_version,
            js_challenge_support_active=bool(runtime and ejs_version),
            po_token_provider_available=_distribution_version("bgutil-ytdlp-pot-provider") is not None,
            po_token_provider_configured=self._pot_provider_mode() is not None,
            po_token_provider_mode=self._pot_provider_mode(),
            cookie_fallback_configured=cookie_file is not None or self._browser_cookies() is not None,
            proxy_configured=bool(os.environ.get("DRIPCUT_YOUTUBE_PROXY")),
            strategies=strategies,
            last_successful_strategy=state.last_successful_strategy,
            last_failure_class=state.last_failure_class,
            last_http_status=state.last_http_status,
            last_login_required=state.last_login_required,
            last_attempted_strategies=state.last_attempted_strategies,
        )

    def select_strategy(self, url: str | None = None) -> list[_ExtractionStrategy]:
        strategies: list[_ExtractionStrategy] = []
        if self._browser_cookies() is not None:
            strategies.append(_ExtractionStrategy("browser_cookie", use_browser_cookies=True))
        if url and not self.is_youtube_url(url):
            strategies.append(_ExtractionStrategy("generic"))
            return strategies
        # A configured operator cookie jar is the only strategy that consistently
        # works from the production GCE region.  Trying four known-blocked public
        # clients first added roughly a minute to every successful import.
        if self._cookie_file() is not None:
            strategies.append(_ExtractionStrategy("authenticated_cookie", use_cookies=True))
        provider_available = _distribution_version("bgutil-ytdlp-pot-provider") is not None
        provider_mode = self._pot_provider_mode()
        if provider_available and provider_mode:
            strategies.append(
                _ExtractionStrategy(
                    "mweb_pot",
                    player_client="mweb",
                    use_pot_provider=True,
                    pot_provider_mode=provider_mode,
                )
            )
        strategies.append(_ExtractionStrategy("web_embedded", player_client="web_embedded"))
        strategies.append(
            _ExtractionStrategy("web_safari_hls", player_client="web_safari", use_hls=True)
        )
        strategies.append(_ExtractionStrategy("recommended"))
        # Prefer the last successful path for subsequent imports in this process.
        with self._state_lock:
            preferred = self._state.last_successful_strategy
        if preferred:
            strategies.sort(key=lambda strategy: strategy.name != preferred)
        return strategies

    @staticmethod
    def _pot_provider_mode() -> Literal["http", "script"] | None:
        """Choose a local bgutil script before an explicitly configured HTTP provider."""
        enabled = os.environ.get("DRIPCUT_YOUTUBE_ENABLE_BGUTIL", "true").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return None
        if os.environ.get("DRIPCUT_YOUTUBE_POT_PROVIDER_URL"):
            return "http"
        script_home = Path(
            os.environ.get("DRIPCUT_YOUTUBE_BGUTIL_SCRIPT_HOME", str(_BGUTIL_SCRIPT_HOME))
        )
        return "script" if (script_home / "build" / "generate_once.js").is_file() else None

    @staticmethod
    def _bgutil_script_home() -> Path:
        return Path(os.environ.get("DRIPCUT_YOUTUBE_BGUTIL_SCRIPT_HOME", str(_BGUTIL_SCRIPT_HOME)))

    def _record_attempt(self, strategy: _ExtractionStrategy) -> None:
        with self._state_lock:
            attempts = self._state.last_attempted_strategies
            if strategy.name not in attempts:
                self._state.last_attempted_strategies = (*attempts, strategy.name)[-10:]

    def _record_failure(
        self,
        strategy: _ExtractionStrategy,
        error: Exception,
        normalized: YouTubeImportError,
    ) -> None:
        self._record_attempt(strategy)
        status = _http_status(error)
        login_required = _login_required(error, normalized)
        with self._state_lock:
            self._state.last_failure_class = normalized.code
            self._state.last_http_status = status
            self._state.last_login_required = login_required
        pot_configured = self._pot_provider_mode() is not None and (
            _distribution_version("bgutil-ytdlp-pot-provider") is not None
        )
        cookie_configured = self._cookie_file() is not None
        js_active = bool(_javascript_runtimes() and _distribution_version("yt-dlp-ejs"))
        _log.warning(
            "youtube strategy=%s client=%s http_status=%s normalized=%s login_required=%s pot=%s cookies=%s js=%s",
            strategy.name,
            strategy.player_client or "default",
            status if status is not None else "none",
            normalized.code,
            login_required,
            strategy.use_pot_provider and pot_configured,
            strategy.use_cookies and cookie_configured,
            js_active,
        )

    def _record_success(self, strategy: _ExtractionStrategy) -> None:
        self._record_attempt(strategy)
        with self._state_lock:
            self._state.last_successful_strategy = strategy.name

    def fetch_metadata(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        import_id: str | None = None,
    ) -> YouTubeMetadata:
        value = self.validate_video_url(url)
        resolved_import_id = import_id or uuid4().hex[:12]
        if on_progress:
            on_progress(0.02, "Fetching video information")
        last_error: YouTubeImportError | None = None
        last_detail = ""
        with self._state_lock:
            self._state.last_attempted_strategies = ()
        for strategy in self.select_strategy(value):
            try:
                info = self._extract(
                    value,
                    strategy,
                    resolved_import_id,
                    destination=None,
                    download=False,
                    on_progress=None,
                )
                self._record_attempt(strategy)
                return self._metadata(info, value)
            except Exception as error:  # noqa: BLE001 - normalize yt-dlp failures
                normalized = error if isinstance(error, YouTubeImportError) else _normalize_error(error)
                last_error = normalized
                last_detail = _error_chain_detail(error)
                self._record_failure(strategy, error, normalized)
                _log.warning(
                    "youtube import=%s video=%s metadata strategy=%s (%s) failed=%s detail=%s",
                    resolved_import_id,
                    self.video_id(value),
                    strategy.name,
                    _strategy_label(strategy.name),
                    normalized.code,
                    _safe_detail(_error_chain_detail(error)),
                )
                if normalized.code in {
                    "PRIVATE_VIDEO",
                    "AGE_RESTRICTED",
                    "VIDEO_UNAVAILABLE",
                    "GEO_RESTRICTED",
                }:
                    raise normalized from error
        self._log_exhausted_failure(
            import_id=resolved_import_id,
            video_id=self.video_id(value),
            phase="metadata",
            error=last_error,
            detail=last_detail,
        )
        if last_error and last_error.code in {"PUBLIC_EXTRACTION_BLOCKED", "BOT_CHALLENGE"}:
            raise self._regional_public_error()
        raise last_error or YouTubeImportError("IMPORT_FAILED", "YouTube metadata could not be retrieved.")

    def import_video(
        self,
        url: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> YouTubeImportResult:
        value = self.validate_video_url(url)
        import_id = uuid4().hex[:12]
        started = time.monotonic()
        metadata = self.fetch_metadata(value, on_progress=on_progress, import_id=import_id)
        metadata_seconds = time.monotonic() - started
        destination = ensure_dir(self.paths.temp / "youtube" / f"{int(time.time())}-{import_id}")
        strategies = self.select_strategy(value)
        last_error: YouTubeImportError | None = None
        last_detail = ""
        download_started = time.monotonic()

        for attempt, strategy in enumerate(strategies, start=1):
            attempt_dir = destination / f"attempt-{attempt}-{strategy.name}"
            shutil.rmtree(attempt_dir, ignore_errors=True)
            ensure_dir(attempt_dir)
            if on_progress:
                stage = "Connecting to the video source" if attempt == 1 else f"Retrying with {strategy.name}"
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
                self._record_success(strategy)
                _log.info(
                    "youtube import=%s video=%s strategy=%s (%s) format=%s yt-dlp=%s retries=%d elapsed=%.2fs success",
                    import_id,
                    metadata.video_id,
                    strategy.name,
                    _strategy_label(strategy.name),
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
                last_detail = _error_chain_detail(error)
                self._record_failure(strategy, error, normalized)
                _log.warning(
                    "youtube import=%s video=%s strategy=%s (%s) yt-dlp=%s retry=%d failed=%s detail=%s",
                    import_id,
                    metadata.video_id,
                    strategy.name,
                    _strategy_label(strategy.name),
                    _distribution_version("yt-dlp") or "unknown",
                    attempt - 1,
                    normalized.code,
                    _safe_detail(_error_chain_detail(error)),
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

        self._log_exhausted_failure(
            import_id=import_id,
            video_id=metadata.video_id,
            phase="download",
            error=last_error,
            detail=last_detail,
        )
        if last_error and last_error.code in {"PUBLIC_EXTRACTION_BLOCKED", "BOT_CHALLENGE"}:
            raise self._regional_public_error()
        raise last_error or YouTubeImportError("IMPORT_FAILED", "The YouTube import failed.")

    def _log_exhausted_failure(
        self,
        *,
        import_id: str,
        video_id: str,
        phase: str,
        error: YouTubeImportError | None,
        detail: str,
    ) -> None:
        """Record the final normalized extractor result without exposing credentials."""
        if error is None:
            return
        _log.error(
            "youtube import=%s video=%s phase=%s exhausted strategies=%s final_code=%s final_reason=%s",
            import_id,
            video_id,
            phase,
            ",".join(self._state.last_attempted_strategies) or "none",
            error.code,
            _safe_detail(detail or error),
        )

    @staticmethod
    def _regional_public_error() -> YouTubeImportError:
        return YouTubeImportError(
            "BOT_CHALLENGE",
            "We couldn't import this public video from YouTube from the current processing region.",
            hint="Retry once, or upload a copy you are allowed to use and continue with the same project.",
            retryable=True,
        )

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
                "Video-link import is not installed.",
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
            raise YouTubeImportError("DOWNLOAD_FAILED", "The link returned no usable video information.")
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
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "logger": _YtDlpLogger(import_id, strategy.name),
            "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        }
        # The upload cap is for user-provided files, not remote source
        # acquisition. Applying it to yt-dlp can filter out the MP4 video
        # stream before merging and leave no usable MP4 on disk. Operators
        # can still enforce a separate YouTube-only cap when needed.
        youtube_limit = os.environ.get("DRIPCUT_YOUTUBE_MAX_FILESIZE_MB")
        if youtube_limit:
            try:
                limit_mb = int(youtube_limit)
            except ValueError:
                limit_mb = 0
            if limit_mb > 0:
                options["max_filesize"] = limit_mb * 1024 * 1024
        if runtimes := _javascript_runtimes():
            options["js_runtimes"] = runtimes
        if proxy := os.environ.get("DRIPCUT_YOUTUBE_PROXY"):
            options["proxy"] = proxy

        extractor_args: dict[str, dict[str, list[str]]] = {}
        if strategy.player_client:
            extractor_args["youtube"] = {"player_client": [strategy.player_client]}
        if strategy.use_pot_provider and strategy.pot_provider_mode == "http":
            provider_url = os.environ.get("DRIPCUT_YOUTUBE_POT_PROVIDER_URL")
            if provider_url:
                extractor_args["youtubepot-bgutilhttp"] = {"base_url": [provider_url]}
        if strategy.use_pot_provider and strategy.pot_provider_mode == "script":
            extractor_args["youtubepot-bgutilscript"] = {
                "server_home": [str(self._bgutil_script_home())]
            }
        if extractor_args:
            options["extractor_args"] = extractor_args
        if strategy.use_cookies and (cookie_file := self._cookie_file()):
            options["cookiefile"] = str(cookie_file)
        if strategy.use_browser_cookies and (browser_cookies := self._browser_cookies()):
            options["cookiesfrombrowser"] = browser_cookies

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
            title=str(info.get("title") or f"Video {video_id}"),
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
        configured = os.environ.get("DRIPCUT_YOUTUBE_COOKIE_FILE") or os.environ.get(
            "YOUTUBE_COOKIE_FILE"
        )
        if not configured:
            return None
        path = Path(configured).expanduser()
        return path if path.is_file() else None

    @staticmethod
    def _browser_cookies() -> tuple[str, str | None, str | None, str | None] | None:
        """Read fresh cookies directly from an operator-controlled worker browser."""
        browser = os.environ.get("DRIPCUT_YOUTUBE_COOKIES_FROM_BROWSER", "").strip().lower()
        supported = {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}
        if browser not in supported:
            return None
        profile = os.environ.get("DRIPCUT_YOUTUBE_BROWSER_PROFILE", "").strip() or None
        return (browser, profile, None, None)


# Preserve the established container and desktop-page import name.
YouTubeService = YouTubeImportService
