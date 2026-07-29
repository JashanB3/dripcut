"""The plugin API - the only surface plugin authors need to learn.

A plugin is a class with metadata and an optional :meth:`Plugin.register` hook. It
receives a :class:`PluginContext` giving it the same services the UI uses, and it
extends the app by returning things:

* :meth:`Plugin.tools` - actions that appear in the Workspace and command palette,
* :meth:`Plugin.split_strategies` - new split modes,
* :meth:`Plugin.caption_styles` - new caption presets,
* :meth:`Plugin.on_event` - reactions to anything on the event bus.

Nothing in this module imports Gradio, so a plugin never depends on the front-end.

Example
-------
::

    class HelloPlugin(Plugin):
        meta = PluginMeta(id="hello", name="Hello", version="1.0.0",
                          description="Adds a greeting action.")

        def tools(self, ctx):
            return [ToolAction(id="hello.say", label="Say hello",
                               description="Log a greeting.",
                               run=lambda media, **kw: "hello")]
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from dripcut.core.config import Settings
    from dripcut.core.container import ServiceContainer
    from dripcut.core.events import Event, EventBus
    from dripcut.engines.split.base import SplitStrategy
    from dripcut.models.media import MediaInfo
    from dripcut.models.subtitle import CaptionStyle

__all__ = ["PluginMeta", "PluginContext", "ToolAction", "Plugin", "PLUGIN_API_VERSION"]

PLUGIN_API_VERSION = 1


@dataclass(frozen=True, slots=True)
class PluginMeta:
    """Identity and compatibility information for a plugin."""

    id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    api_version: int = PLUGIN_API_VERSION
    tags: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        """True when this plugin targets the API version DripCut provides."""
        return self.api_version == PLUGIN_API_VERSION


@dataclass(slots=True)
class PluginContext:
    """Services handed to a plugin at registration time."""

    container: ServiceContainer
    settings: Settings
    events: EventBus
    output_dir: Path
    data_dir: Path

    def service(self, key: str, default: Any = None) -> Any:
        """Resolve a service by key without raising."""
        return self.container.try_resolve(key, default)

    @property
    def video(self) -> Any:
        """Video engine service."""
        return self.service("video")

    @property
    def ai(self) -> Any:
        """AI service (may be disabled)."""
        return self.service("ai")

    @property
    def queue(self) -> Any:
        """Export queue."""
        return self.service("queue")

    def notify(self, message: str, level: str = "info", *, detail: str = "") -> None:
        """Post a message to the notification centre."""
        self.events.publish("notify", message=message, level=level, detail=detail)


@dataclass(slots=True)
class ToolAction:
    """A plugin-provided action shown in the UI.

    ``run`` receives the current :class:`MediaInfo` (or ``None``) plus keyword
    arguments, and returns a human-readable result string or a path.
    """

    id: str
    label: str
    description: str = ""
    run: Callable[..., Any] | None = None
    icon: str = "\u25c8"
    group: str = "Plugins"
    needs_media: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def invoke(self, media: MediaInfo | None = None, **kwargs: Any) -> Any:
        """Execute the action."""
        if self.run is None:
            raise NotImplementedError(f"Tool {self.id!r} has no implementation.")
        return self.run(media, **kwargs)


class Plugin:
    """Base class for plugins. Override only what you need."""

    meta: PluginMeta = PluginMeta(id="plugin", name="Unnamed plugin")

    def register(self, context: PluginContext) -> None:
        """Called once at startup. Use it to store the context or warm caches."""

    def tools(self, context: PluginContext) -> Sequence[ToolAction]:
        """Return actions to add to the Workspace and command palette."""
        return ()

    def split_strategies(self, context: PluginContext) -> Sequence[SplitStrategy]:
        """Return additional split strategies."""
        return ()

    def caption_styles(self, context: PluginContext) -> dict[str, CaptionStyle]:
        """Return additional caption presets, keyed by display name."""
        return {}

    def on_event(self, event: Event) -> None:
        """Called for every event on the bus when the plugin is enabled."""

    def shutdown(self) -> None:
        """Called when DripCut exits. Release anything you hold open."""
