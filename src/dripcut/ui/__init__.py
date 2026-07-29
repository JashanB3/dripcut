"""Gradio presentation layer. Thin by design: no business logic lives here.

``build_app`` and ``launch`` live in :mod:`dripcut.ui.app` and are re-exported
lazily via :pep:`562` module ``__getattr__``. The indirection keeps
``import dripcut.ui`` (and therefore ``dripcut.ui.theme``) usable while the page
composition module is still pending -- see PROJECT_STATE.md.
"""

from __future__ import annotations

from typing import Any

from dripcut.ui.theme import build_theme, css_variables, load_css, load_js

__all__ = ["build_app", "build_theme", "css_variables", "launch", "load_css", "load_js"]

_LAZY = {"build_app", "launch"}


def __getattr__(name: str) -> Any:
    """Resolve the Blocks factory on first use."""
    if name in _LAZY:
        from dripcut.ui import app as _app

        return getattr(_app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
