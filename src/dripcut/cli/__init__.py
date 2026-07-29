"""Command-line layer.

The outermost layer of the application. It owns argument parsing, terminal
rendering and process exit codes, and nothing else -- every operation it performs
goes through the service container built by :mod:`dripcut.core.bootstrap`.

Importing this package must stay cheap: ``dripcut --version`` should not pull in
Gradio or Whisper, so heavy imports live inside the functions that need them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["build_parser", "main", "run"]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dripcut.cli.main import build_parser, main, run

_LAZY = frozenset(__all__)


def __getattr__(name: str) -> Any:
    """Resolve entry points from :mod:`dripcut.cli.main` on first access."""
    if name in _LAZY:
        from dripcut.cli import main as _main

        return getattr(_main, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
