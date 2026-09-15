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
    _safe_detail,
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
        "http://www.youtube.com/watch?v=abc123",
        "https://attacker@example.com@youtube.com/watch?v=abc123",
        "https://www.youtube.com:8443/watch?v=abc123",
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
    assert result.strategy == "web_embedded"
    assert result.attempts == 1
    assert progress[-1] == (1.0, "Ready")
    assert any(stage == "Downloading video" for _, stage in progress)
    assert options_seen[-1]["js_runtimes"] == {"node": {"path": "/bin/node"}}
    assert "height<=1080" in str(options_seen[-1]["format"])


def test_http_403_retries_from_web_embedded_to_hls(paths, monkeypatch) -> None:
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
                if strategy == "web_embedded":
                    raise ProviderError("unable to download video data: HTTP Error 403")
                _write_fake_output(self.options)
            return {**_metadata(), "format_id": "18"}

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))

    result = YouTubeService(paths, sleep=lambda _seconds: None).import_video(
        "https://www.youtube.com/watch?v=abc123"
    )

    assert strategies == ["web_embedded", "web_safari"]
    assert result.strategy == "web_safari_hls"
    assert result.attempts == 2
    assert result.format_id == "18"


def test_strategy_order_remains_bounded_after_a_success(paths, monkeypatch) -> None:
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
                if strategy == "web_embedded":
                    raise ProviderError("HTTP Error 403")
                _write_fake_output(self.options)
            return {**_metadata(), "format_id": "18"}

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))
    service = YouTubeService(paths, sleep=lambda _seconds: None)

    service.import_video("https://youtu.be/abc123")
    first_import_attempts = len(attempted)
    service.import_video("https://youtu.be/def456")

    assert attempted[:first_import_attempts] == ["web_embedded", "web_safari"]
    assert attempted[first_import_attempts:] == ["web_embedded", "web_safari"]


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
    assert result.attempts == 2
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
        lambda name: "2.0.0" if name == "bgutil-ytdlp-pot-provider" else "test",
    )

    service = YouTubeService(paths, sleep=lambda _seconds: None)
    strategies = service.select_strategy()

    assert [strategy.name for strategy in strategies] == [
        "web_embedded",
        "mweb_pot",
        "web_safari_hls",
        "recommended",
        "authenticated_cookie",
    ]
    pot_options = service._options(strategies[1], "job", paths.temp / "pot", None)
    cookie_options = service._options(strategies[-1], "job", paths.temp / "cookie", None)
    assert pot_options["extractor_args"] == {
        "youtube": {"player_client": ["mweb"]},
        "youtubepot-bgutilhttp": {"base_url": ["http://127.0.0.1:4416"]},
    }
    assert cookie_options["cookiefile"] == str(cookie_file)


def test_import_uses_mweb_pot_when_provider_is_configured(paths, monkeypatch) -> None:
    options_seen: list[dict[str, object]] = []

    class ProviderError(RuntimeError):
        pass

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            options_seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            client = self.options.get("extractor_args", {}).get("youtube", {}).get(
                "player_client", ["recommended"]
            )[0]
            if download and client == "web_embedded":
                raise ProviderError("HTTP Error 403: confirm you're not a bot")
            if download:
                _write_fake_output(self.options)
            return _metadata()

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setenv("DRIPCUT_YOUTUBE_POT_PROVIDER_URL", "http://pot.internal:4416")
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))
    monkeypatch.setattr(
        "dripcut.services.youtube_service._distribution_version",
        lambda name: "2.0.0" if name == "bgutil-ytdlp-pot-provider" else "test",
    )

    result = YouTubeService(paths, sleep=lambda _seconds: None).import_video("https://youtu.be/abc123")

    assert result.strategy == "mweb_pot"
    pot_options = next(
        options
        for options in options_seen
        if options.get("extractor_args", {}).get("youtube", {}).get("player_client") == ["mweb"]
    )
    assert pot_options["extractor_args"] == {
        "youtube": {"player_client": ["mweb"]},
        "youtubepot-bgutilhttp": {"base_url": ["http://pot.internal:4416"]},
    }


def test_safe_detail_redacts_urls_and_secret_values() -> None:
    detail = _safe_detail(
        "HTTP Error 403 for https://example.test/watch?token=visible "
        "po_token=also-visible authorization: Bearer third-visible"
    )

    assert "example.test" not in detail
    assert "visible" not in detail
    assert "<redacted-url>" in detail
    assert detail.count("<redacted-secret>") == 2


def test_render_secret_cookie_alias_is_supported(paths, monkeypatch) -> None:
    cookie_file = paths.temp / "youtube-cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.delenv("DRIPCUT_YOUTUBE_COOKIE_FILE", raising=False)
    monkeypatch.setenv("YOUTUBE_COOKIE_FILE", str(cookie_file))

    service = YouTubeService(paths, sleep=lambda _seconds: None)

    assert service.diagnostics().cookie_fallback_configured is True
    assert service.select_strategy()[-1].name == "authenticated_cookie"


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
    assert payload["node_available"] is True
    assert "js_challenge_support_active" in payload
    assert payload["last_successful_strategy"] is None
    assert payload["last_failure_class"] is None
    assert str(cookie_file) not in str(payload)
    assert "secret-proxy" not in str(payload)


def test_diagnostics_record_normalized_fallback_without_raw_secrets(paths, monkeypatch) -> None:
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
            if download and strategy == "web_embedded":
                raise ProviderError("HTTP Error 403 for https://secret.example/signed?token=nope")
            if download:
                _write_fake_output(self.options)
            return _metadata()

    _install_fake_ytdlp(monkeypatch, FakeYoutubeDL, ProviderError)
    monkeypatch.setattr(YouTubeImportService, "_validate_media", staticmethod(lambda _path: None))
    service = YouTubeService(paths, sleep=lambda _seconds: None)

    result = service.import_video("https://youtu.be/abc123")
    diagnostics = service.diagnostics().to_dict()

    assert result.strategy == "web_safari_hls"
    assert diagnostics["last_successful_strategy"] == "web_safari_hls"
    assert diagnostics["last_failure_class"] == "PUBLIC_EXTRACTION_BLOCKED"
    assert diagnostics["last_http_status"] == 403
    assert diagnostics["last_login_required"] is False
    assert "secret.example" not in str(diagnostics)


def test_all_public_strategies_fail_with_region_aware_upload_fallback(paths, monkeypatch) -> None:
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
            raise ProviderError("Sign in to confirm you're not a bot: HTTP Error 403")

    _install_fake_ytdlp(monkeypatch, BrokenYoutubeDL, ProviderError)
    service = YouTubeService(paths, sleep=lambda _seconds: None)

    with pytest.raises(YouTubeImportError) as captured:
        service.import_video("https://youtu.be/abc123")

    assert captured.value.code == "PUBLIC_EXTRACTION_BLOCKED"
    assert "current processing region" in str(captured.value)
    assert "upload the video directly" in str(captured.value)
    diagnostics = service.diagnostics()
    assert diagnostics.last_http_status == 403
    assert diagnostics.last_login_required is True
    assert diagnostics.last_attempted_strategies == (
        "web_embedded",
        "web_safari_hls",
        "recommended",
    )
