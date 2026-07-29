"""Platform-correct application directories.

DripCut keeps user data out of the source tree so ``pip install -e .`` and a
future signed ``.app`` bundle behave identically:

macOS
    ``~/Library/Application Support/DripCut`` for config, projects and models
    ``~/Library/Caches/DripCut`` for regenerable artefacts (proxies, waveforms)
Linux / other
    XDG base directories

Any location may be overridden with the ``DRIPCUT_HOME`` environment variable,
which is what the test-suite and portable installs use.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dripcut.utils.fs import ensure_dir

__all__ = ["AppPaths", "app_paths", "package_asset"]

_APP_DIR_NAME = "DripCut"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Resolved absolute locations for everything DripCut writes."""

    home: Path
    config_file: Path
    logs: Path
    projects: Path
    cache: Path
    models: Path
    plugins: Path
    output: Path
    temp: Path
    history_file: Path

    def create_all(self) -> AppPaths:
        """Create every directory this instance points at."""
        for directory in (
            self.home,
            self.logs,
            self.projects,
            self.cache,
            self.models,
            self.plugins,
            self.output,
            self.temp,
        ):
            ensure_dir(directory)
        return self

    def project_dir(self, project_id: str) -> Path:
        """Directory that holds a single project's manifest and artefacts."""
        return self.projects / project_id

    def describe(self) -> dict[str, str]:
        """Flat mapping used by the Settings page and ``dripcut doctor``."""
        return {
            "Home": str(self.home),
            "Config": str(self.config_file),
            "Projects": str(self.projects),
            "Cache": str(self.cache),
            "Models": str(self.models),
            "Plugins": str(self.plugins),
            "Output": str(self.output),
            "Logs": str(self.logs),
        }


def _default_home() -> Path:
    override = os.environ.get("DRIPCUT_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / _APP_DIR_NAME).resolve()


def _default_cache(home: Path) -> Path:
    if os.environ.get("DRIPCUT_HOME"):
        return home / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP_DIR_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return (base / _APP_DIR_NAME).resolve()


@lru_cache(maxsize=1)
def app_paths() -> AppPaths:
    """Return the process-wide :class:`AppPaths`, creating directories on first use."""
    home = _default_home()
    cache = _default_cache(home)
    default_output = Path.home() / "Movies" / "DripCut" if sys.platform == "darwin" else home / "output"
    return AppPaths(
        home=home,
        config_file=home / "settings.json",
        logs=home / "logs",
        projects=home / "projects",
        cache=cache,
        models=home / "models",
        plugins=home / "plugins",
        output=Path(os.environ.get("DRIPCUT_OUTPUT", default_output)).expanduser(),
        temp=cache / "tmp",
        history_file=home / "history.json",
    ).create_all()


def package_asset(*parts: str) -> Path:
    """Absolute path to a file shipped inside the installed package."""
    return Path(__file__).resolve().parent.parent.joinpath(*parts)
