"""Filesystem helpers: safe names, unique paths, sizes, disk space."""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

__all__ = [
    "slugify",
    "safe_filename",
    "unique_path",
    "ensure_dir",
    "human_size",
    "free_space_gb",
    "dir_size",
    "VIDEO_SUFFIXES",
    "AUDIO_SUFFIXES",
    "is_media_file",
]

VIDEO_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".ts"}
)
AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"})

_UNSAFE = re.compile(r"[^\w\-. ]+", re.UNICODE)
_DASHES = re.compile(r"[-\s]+")


def slugify(text: str, *, max_length: int = 60) -> str:
    """Return a lowercase, dash-separated, filesystem-safe slug."""
    normalised = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub(" ", ascii_text).strip().lower()
    slug = _DASHES.sub("-", cleaned).strip("-.")
    return (slug[:max_length].rstrip("-") or "untitled")


def safe_filename(name: str, *, fallback: str = "output") -> str:
    """Strip path separators and control characters from a user-supplied name."""
    candidate = _UNSAFE.sub("_", (name or "").strip()).strip("._ ")
    return candidate or fallback


def unique_path(path: Path) -> Path:
    """Return ``path`` or the first free ``name (2).ext`` style variant."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for index in range(2, 10_000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"could not find a free filename near {path}")


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def human_size(num_bytes: float) -> str:
    """Format a byte count as ``1.4 GB``."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def free_space_gb(path: Path) -> float:
    """Free space in gibibytes on the volume that holds ``path``."""
    target = path
    while not target.exists() and target.parent != target:
        target = target.parent
    return shutil.disk_usage(target).free / (1024**3)


def dir_size(path: Path) -> int:
    """Total size in bytes of every file under ``path``."""
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def is_media_file(path: Path) -> bool:
    """True when the suffix looks like audio or video DripCut can open."""
    suffix = path.suffix.lower()
    return suffix in VIDEO_SUFFIXES or suffix in AUDIO_SUFFIXES
