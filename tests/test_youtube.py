from __future__ import annotations

import sys
import types

import pytest

from dripcut.core.errors import MediaDownloadError, ValidationError
from dripcut.services.youtube_service import YouTubeService, _download_error


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://m.youtube.com/watch?v=abc123",
    ],
)
def test_validate_url_accepts_youtube_hosts(url: str) -> None:
    assert YouTubeService.validate_url(url) == url


@pytest.mark.parametrize(
    "url",
    ["", "not a link", "https://example.com/video", "https://youtube.com.example.com/watch?v=x"],
)
def test_validate_url_rejects_other_inputs(url: str) -> None:
    with pytest.raises(ValidationError):
        YouTubeService.validate_url(url)


def test_download_returns_the_video_and_reports_progress(paths, monkeypatch) -> None:
    progress: list[tuple[float, str]] = []
    options_seen = {}

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            options_seen.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, _urls):
            output = self.options["outtmpl"].replace("%(title).150B", "demo").replace(
                "%(id)s", "abc"
            ).replace("%(ext)s", "mp4")
            path = __import__("pathlib").Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            hook = self.options["progress_hooks"][0]
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = FakeYoutubeDL
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = RuntimeError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)
    monkeypatch.setattr("dripcut.services.youtube_service.shutil.which", lambda _name: "/bin/node")

    result = YouTubeService(paths).download(
        "https://youtu.be/abc", on_progress=lambda fraction, stage: progress.append((fraction, stage))
    )

    assert result.name == "demo-abc.mp4"
    assert result.read_bytes() == b"video"
    assert progress[-1] == (1.0, "Video ready")
    assert options_seen["js_runtimes"] == {"node": {"path": "/bin/node"}}


def test_download_error_explains_sign_in_requirement() -> None:
    error = _download_error(RuntimeError("Sign in to confirm your age"))

    assert "sign-in" in str(error).lower()


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

        def download(self, _urls):
            raise ProviderError("blocked")

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = BrokenYoutubeDL
    utils = types.ModuleType("yt_dlp.utils")
    utils.DownloadError = ProviderError
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    monkeypatch.setitem(sys.modules, "yt_dlp.utils", utils)

    with pytest.raises(MediaDownloadError):
        YouTubeService(paths).download("https://youtu.be/abc")
