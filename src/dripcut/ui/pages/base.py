"""Page abstraction.

A page owns one destination in the sidebar. It builds its own controls inside a
``gr.Column`` and returns that column so the router can toggle visibility -- there
is no client-side routing and no hidden state machine, just one visible column.

Pages never import engines. Everything they need arrives through
:class:`PageContext`, which is a thin, typed view onto the service container.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import gradio as gr

from dripcut.core.errors import DripCutError
from dripcut.core.logging import get_logger
from dripcut.ui.components.widgets import banner

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

    from dripcut.core.container import ServiceContainer

__all__ = ["Page", "PageContext", "safe_call"]

_log = get_logger("ui.pages")


@dataclass(frozen=True, slots=True)
class PageContext:
    """Everything a page is allowed to reach.

    Wrapping the container rather than passing it around raw keeps the surface
    small and makes it obvious in review when a page starts reaching for
    something it should not.
    """

    container: ServiceContainer

    @property
    def settings(self) -> Any:
        """Live application settings."""
        return self.container.settings

    @property
    def paths(self) -> Any:
        """Resolved application paths."""
        return self.container.paths

    @property
    def events(self) -> Any:
        """The application event bus."""
        return self.container.events

    @property
    def media(self) -> Any:
        """Media import, probing, thumbnails and proxies."""
        return self.container.media

    @property
    def youtube(self) -> Any:
        """YouTube video importer."""
        return self.container.youtube

    @property
    def split(self) -> Any:
        """Split planning and rendering."""
        return self.container.split

    @property
    def ai(self) -> Any:
        """Transcription and analysis."""
        return self.container.ai

    @property
    def subtitles(self) -> Any:
        """Caption generation and burn-in."""
        return self.container.subtitles

    @property
    def export(self) -> Any:
        """Job creation for every tool."""
        return self.container.export

    @property
    def projects(self) -> Any:
        """Project persistence."""
        return self.container.projects

    @property
    def notifications(self) -> Any:
        """The notification centre."""
        return self.container.notifications

    @property
    def plugins(self) -> Any:
        """The plugin registry."""
        return self.container.plugins

    @property
    def queue(self) -> Any:
        """The background job queue."""
        return self.container.resolve("queue")

    @property
    def output_dir(self) -> Path:
        """Where renders are written by default."""
        return self.settings.output_path


class Page(ABC):
    """One sidebar destination.

    Subclasses set the class attributes and implement :meth:`build`. The router
    reads ``key`` to decide which column to show, and the sidebar reads ``label``,
    ``icon`` and ``group`` to draw the navigation.
    """

    key: str = ""
    label: str = ""
    icon: str = "\u25a0"
    group: str = "Workspace"
    title: str = ""
    subtitle: str = ""

    @abstractmethod
    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Create this page's controls and return its root column."""
        raise NotImplementedError

    def commands(self) -> list[dict[str, str]]:
        """Command-palette entries contributed by this page.

        The default is a single 'go to this page' entry, which is what most pages
        want. Pages with in-page actions override and extend the list.
        """
        return [
            {
                "label": self.label,
                "group": "Go to",
                "target": f"dc-nav-{self.key}",
                "keywords": f"{self.key} {self.group}",
            }
        ]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} key={self.key!r}>"


def safe_call(fn: Any, *args: Any, fallback: Any = None, **kwargs: Any) -> Any:
    """Run a service call, converting expected failures into a banner.

    Event handlers must not raise: Gradio would show a stack trace, which is
    exactly the thing the error hierarchy exists to avoid. Anything unexpected is
    re-raised so it reaches the logs rather than being silently swallowed.

    Returns:
        The call's result, or ``(fallback, banner_html)`` shaped by the caller.
    """
    try:
        return fn(*args, **kwargs), ""
    except DripCutError as error:
        message = getattr(error, "message", None) or str(error)
        hint = getattr(error, "hint", "") or ""
        level = "warning" if type(error).__name__ in {"ValidationError", "SplitPlanError"} else "error"
        return fallback, banner(f"{message} {hint}".strip(), level=level, title=_title_for(error))
    except Exception as error:  # noqa: BLE001 - event handlers should not show raw Gradio errors
        _log.exception("unexpected UI action failure")
        return fallback, banner(
            f"{type(error).__name__}: {str(error)[:220]}",
            level="error",
            title="Something went wrong",
        )


def _title_for(error: Exception) -> str:
    """Turn ``SplitPlanError`` into ``Split plan``, for the banner heading."""
    name = type(error).__name__.removesuffix("Error")
    spaced = "".join(f" {ch.lower()}" if ch.isupper() else ch for ch in name).strip()
    return spaced[:1].upper() + spaced[1:] if spaced else "Problem"
