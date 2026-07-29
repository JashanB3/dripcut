"""Shared fixtures.

Every test runs against a throwaway application home so nothing touches the real
`~/Library/Application Support/DripCut`. `app_paths()` is `lru_cache`d, so the
cache is cleared after the environment is rewritten.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


@pytest.fixture
def app_home(tmp_path: Path) -> Path:
    """An isolated DripCut home per test.

    Function-scoped deliberately: projects, settings and the job history all live
    under here, and a shared home lets one test observe another's writes.
    """
    return tmp_path / "home"


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch: pytest.MonkeyPatch, app_home: Path, tmp_path: Path) -> None:
    """Point every path helper at temporary directories."""
    from dripcut.core.paths import app_paths

    monkeypatch.setenv("DRIPCUT_HOME", str(app_home))
    monkeypatch.setenv("DRIPCUT_OUTPUT", str(tmp_path / "out"))
    app_paths.cache_clear()
    yield
    app_paths.cache_clear()


@pytest.fixture
def paths(isolated_paths: None):
    """Freshly resolved application paths, with directories created."""
    from dripcut.core.paths import app_paths

    return app_paths().create_all()


@pytest.fixture
def settings(paths):
    """Default settings pointed at the temporary home."""
    from dripcut.core.config import Settings

    created = Settings()
    created.output_dir = str(paths.output)
    return created


@pytest.fixture
def container(settings, paths):
    """A wired service container with plugin discovery switched off."""
    from dripcut.core.bootstrap import build_container

    built = build_container(settings, paths=paths, load_plugins=False)
    yield built
    queue = built.try_resolve("queue")
    if queue is not None:
        queue.shutdown()


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A tiny six-second clip with tone and picture, generated once per session."""
    if FFMPEG is None:
        pytest.skip("ffmpeg is not installed")
    target = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=12:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", "-y", str(target),
        ],
        check=True,
        capture_output=True,
    )
    return target


@pytest.fixture
def media(container, sample_video: Path):
    """Probed media info for the sample clip."""
    return container.media.import_file(sample_video)
