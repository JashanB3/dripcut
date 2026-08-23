from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from dripcut.core.errors import MediaDownloadError, ValidationError
from dripcut.services.youtube_service import (
    YouTubeImportError,
    YouTubeImportService,
    YouTubeService,
    _download_error,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123?si=share",
        "https://m.youtube.com/watch?v=abc123&t=4",
        "https://www.youtube.com/shorts/abc123",
        "https://www.youtube.com/embed/abc123",
    ],
)
def test_validate_url_accepts_youtube_video_urls(url: str) -> None:
    assert YouTubeService.validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a link",
        "https://example.com/video",
        "https://youtube.com.example.com/watch?v=x",
        "https://www.youtube.com/@creator",
    ],
)
def test_validate_url_rejects_other_inputs(url: str) -> None:
    with pytest.raises(ValidationError):
        YouTubeService.validate_url(url)


def _install_fake_ytdlp(monkeypatch, youtube_dl: type, download_error: type[Exception] = RuntimeError) -> None:
    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = youtube_dl
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = download_error
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)


def _metadata() -> dict[str, object]:
    return {
        "id": "abc123",
        "title": "Demo video",
        "duration": 12.0,
        "channel": "Demo channel",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "format_id": "18",
    }


def _write_fake_output(options: dict[str, object]) -> Path:
    template = str(options["outtmpl"])
    output = template.replace("%(title).150B", "demo").replace("%(id)s", "abc123").replace(
        "%(ext)s", "mp4"
    )
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video")
    return path


def test_import_returns_verified_video_metadata_and_progress(paths, monkeypatch) -> None:
    progress: list[tuple[float, str]] = []
    options_seen: list[dict[str, object]] = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            if download:
                _write_fake_output(self.options)
                hook = self.options["progress_hooks"][0]
                hook(
                    {
                        "status": "downloading",
                        "downloaded_bytes": 50,
                        "total_bytes": 100,
                        "info_dict": {"vcodec": "avc1", "acodec": "none"},
                    }
                )
                hook({"status": "finished"})
            return _metadata()

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))
    monkeypatch.setattr(
        "dripcut.services.youtube_service._javascript_runtimes",
        lambda: {"node": {"path": "/bin/node"}},
    )

    result = YouTubeService(paths, sleep=lambda _seconds: None).import_video(
        "https://youtu.be/abc123",
        on_progress=lambda fraction, stage: progress.append((fraction, stage)),
    )

    assert result.path.name == "demo-abc123.mp4"
    assert result.metadata.title == "Demo video"
    assert result.strategy == "recommended"
    assert result.attempts == 1
    assert progress[-1] == (1.0, "Ready")
    assert any(stage == "Downloading video" for _, stage in progress)
    assert options_seen[-1]["js_runtimes"] == {"node": {"path": "/bin/node"}}
    assert "height<=1080" in str(options_seen[-1]["format"])


def test_http_403_retries_with_web_embedded(paths, monkeypatch) -> None:
    strategies: list[str] = []

    class ProviderError(RuntimeError):
        pass

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            extractor = self.options.get("extractor_args", {})
            strategy = extractor.get("youtube", {}).get("player_client", ["recommended"])[0]
            if download:
                strategies.append(strategy)
                if strategy == "recommended":
                    raise ProviderError("unable to download video data: HTTP Error 403")
                _write_fake_output(self.options)
            return {**_metadata(), "format_id": "18"}

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))

    result = YouTubeService(paths, sleep=lambda _seconds: None).import_video(
        "https://www.youtube.com/watch?v=abc123"
    )

    assert strategies == ["recommended", "web_embedded"]
    assert result.strategy == "web_embedded"
    assert result.attempts == 2
    assert result.format_id == "18"


def test_successful_strategy_is_tried_first_on_the_next_import(paths, monkeypatch) -> None:
    attempted: list[str] = []

    class ProviderError(RuntimeError):
        pass

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            extractor = self.options.get("extractor_args", {})
            strategy = extractor.get("youtube", {}).get("player_client", ["recommended"])[0]
            if download:
                attempted.append(strategy)
                if strategy == "recommended":
                    raise ProviderError("HTTP Error 403")
                _write_fake_output(self.options)
            return {**_metadata(), "format_id": "18"}

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))
    service = YouTubeService(paths, sleep=lambda _seconds: None)

    service.import_video("https://youtu.be/abc123")
    first_import_attempts = len(attempted)
    service.import_video("https://youtu.be/def456")

    assert attempted[:first_import_attempts] == ["recommended", "web_embedded"]
    assert attempted[first_import_attempts:] == ["web_embedded"]


def test_web_safari_hls_is_used_after_direct_clients_fail(paths, monkeypatch) -> None:
    class ProviderError(RuntimeError):
        pass

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            extractor = self.options.get("extractor_args", {})
            strategy = extractor.get("youtube", {}).get("player_client", ["recommended"])[0]
            if download and strategy != "web_safari":
                raise ProviderError("unable to download video data: HTTP Error 403")
            if download:
                _write_fake_output(self.options)
            return {**_metadata(), "format_id": "96" if strategy == "web_safari" else "18"}

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))

    result = YouTubeService(paths, sleep=lambda _seconds: None).import_video(
        "https://www.youtube.com/watch?v=abc123"
    )

    assert result.strategy == "web_safari_hls"
    assert result.attempts == 3
    assert result.format_id == "96"


@pytest.mark.parametrize(
    ("detail", "code"),
    [
        ("This video is private", "PRIVATE_VIDEO"),
        ("Sign in to confirm your age", "AGE_RESTRICTED"),
        ("Sign in to confirm you're not a bot", "PUBLIC_EXTRACTION_BLOCKED"),
        ("HTTP Error 429: Too Many Requests", "RATE_LIMITED"),
        ("Video unavailable", "VIDEO_UNAVAILABLE"),
        ("not available in your country", "GEO_RESTRICTED"),
        ("Sign in to view this video", "LOGIN_REQUIRED"),
    ],
)
def test_errors_are_normalized(detail: str, code: str) -> None:
    error = _download_error(RuntimeError(detail))

    assert isinstance(error, YouTubeImportError)
    assert error.code == code


def test_download_wraps_provider_errors(paths, monkeypatch) -> None:
    class ProviderError(RuntimeError):
        pass

    class BrokenYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            raise ProviderError("video unavailable")

    _install_fake_ytdlp(monkeypatch, BrokenYoutubeDL, ProviderError)

    with pytest.raises(MediaDownloadError) as captured:
        YouTubeService(paths, sleep=lambda _seconds: None).download("https://youtu.be/abc123")

    assert captured.value.code == "VIDEO_UNAVAILABLE"


def test_strategy_order_includes_configured_pot_and_cookie_fallback(paths, monkeypatch) -> None:
    cookie_file = paths.temp / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_POT_PROVIDER_URL", "http://127.0.0.1:4416")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_COOKIE_FILE", str(cookie_file))
    monkeypatch.setattr(
        "dripcut.services.youtube_service._distribution_version",
        lambda name: "1.3.2" if name == "bgutil-ytdlp-pot-provider" else "test",
    )

    service = YouTubeService(paths, sleep=lambda _seconds: None)
    strategies = service.select_strategy()

    assert [strategy.name for strategy in strategies] == [
        "recommended",
        "mweb_pot",
        "web_embedded",
        "web_safari_hls",
        "authenticated_cookie",
    ]
    pot_options = service._options(strategies[1], "job", paths.temp / "pot", None)
    cookie_options = service._options(strategies[-1], "job", paths.temp / "cookie", None)
    assert pot_options["extractor_args"] == {
        "youtube": {"player_client": ["mweb"]},
        "youtubepot-bgutilhttp": {"base_url": ["http://127.0.0.1:4416"]},
    }
    assert cookie_options["cookiefile"] == str(cookie_file)


def test_diagnostics_report_capabilities_without_secret_paths(paths, monkeypatch) -> None:
    cookie_file = paths.temp / "secret-cookies.txt"
    cookie_file.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("DRIPCUT_YOUTUBE_COOKIE_FILE", str(cookie_file))
    monkeypatch.setenv("DRIPCUT_YOUTUBE_PROXY", "http://secret-proxy.example")
    monkeypatch.setattr(
        "dripcut.services.youtube_service._runtime_version", lambda _runtimes: ("node", "v24")
    )

    payload = YouTubeService(paths).diagnostics().to_dict()

    assert payload["cookie_fallback_configured"] is True
    assert payload["proxy_configured"] is True
    assert str(cookie_file) not in str(payload)
    assert "secret-proxy" not in str(payload)
