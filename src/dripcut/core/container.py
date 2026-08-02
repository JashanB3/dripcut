"""A tiny dependency-injection container.

DripCut avoids module-level singletons: every service takes its collaborators as
constructor arguments and the container wires them together once, at startup, in
:mod:`dripcut.core.bootstrap`. That is what makes the engines unit-testable with
fakes and what will let a future Qt or CLI-only front-end reuse the same objects.

The container is deliberately minimal - registration by key, lazy singletons and
factories - because a full IoC framework would be more machinery than a desktop
app of this size needs.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from dripcut.core.errors import DripCutError

__all__ = ["Container", "ServiceContainer", "ServiceNotRegistered"]

T = TypeVar("T")


class ServiceNotRegistered(DripCutError):
    """Raised when an unknown service key is resolved."""


class Container:
    """Registry of lazily constructed singletons and per-call factories."""

    def __init__(self) -> None:
        self._singleton_factories: dict[str, Callable[[Container], Any]] = {}
        self._factories: dict[str, Callable[[Container], Any]] = {}
        self._instances: dict[str, Any] = {}
        self._lock = threading.RLock()

    def register_instance(self, key: str, instance: Any) -> None:
        """Register an already-constructed object."""
        with self._lock:
            self._instances[key] = instance

    def register_singleton(self, key: str, factory: Callable[[Container], T]) -> None:
        """Register a factory whose result is cached after first resolution."""
        with self._lock:
            self._singleton_factories[key] = factory
            self._instances.pop(key, None)

    def register_factory(self, key: str, factory: Callable[[Container], T]) -> None:
        """Register a factory invoked on every :meth:`resolve`."""
        with self._lock:
            self._factories[key] = factory

    def resolve(self, key: str) -> Any:
        """Return the service registered under ``key``.

        Raises:
            ServiceNotRegistered: If nothing is registered for ``key``.
        """
        with self._lock:
            if key in self._instances:
                return self._instances[key]
            if key in self._singleton_factories:
                instance = self._singleton_factories[key](self)
                self._instances[key] = instance
                return instance
            factory = self._factories.get(key)
        if factory is not None:
            return factory(self)
        raise ServiceNotRegistered(
            f"No service registered as {key!r}.",
            hint="Register it during bootstrap before the UI is built.",
        )

    def try_resolve(self, key: str, default: Any = None) -> Any:
        """Like :meth:`resolve` but returns ``default`` instead of raising."""
        try:
            return self.resolve(key)
        except ServiceNotRegistered:
            return default

    def has(self, key: str) -> bool:
        """True when ``key`` can be resolved."""
        with self._lock:
            return (
                key in self._instances
                or key in self._singleton_factories
                or key in self._factories
            )

    def keys(self) -> list[str]:
        """Sorted list of every registered key (used by ``dripcut doctor``)."""
        with self._lock:
            return sorted({*self._instances, *self._singleton_factories, *self._factories})

    def __contains__(self, key: object) -> bool:  # noqa: D105 - trivial
        return isinstance(key, str) and self.has(key)


class ServiceContainer(Container):
    """Container with typed accessors for DripCut's well-known services.

    Front-end code reads ``ctx.video`` rather than ``ctx.resolve("video")`` so
    renaming a service is a compile-time-ish concern instead of a string hunt.
    """

    KEY_SETTINGS = "settings"
    KEY_EVENTS = "events"
    KEY_PATHS = "paths"
    KEY_PROBE = "probe"
    KEY_FFMPEG = "ffmpeg"
    KEY_VIDEO = "video"
    KEY_SPLIT = "split"
    KEY_AI = "ai"
    KEY_SUBTITLES = "subtitles"
    KEY_EXPORT = "export"
    KEY_PROJECTS = "projects"
    KEY_MEDIA = "media"
    KEY_YOUTUBE = "youtube"
    KEY_NOTIFICATIONS = "notifications"
    KEY_PLUGINS = "plugins"

    @property
    def settings(self) -> Any:
        """The live :class:`dripcut.core.config.Settings`."""
        return self.resolve(self.KEY_SETTINGS)

    @property
    def events(self) -> Any:
        """The process-wide :class:`dripcut.core.events.EventBus`."""
        return self.resolve(self.KEY_EVENTS)

    @property
    def paths(self) -> Any:
        """Resolved :class:`dripcut.core.paths.AppPaths`."""
        return self.resolve(self.KEY_PATHS)

    @property
    def media(self) -> Any:
        """Media import / probing service."""
        return self.resolve(self.KEY_MEDIA)

    @property
    def youtube(self) -> Any:
        """YouTube import service."""
        return self.resolve(self.KEY_YOUTUBE)

    @property
    def video(self) -> Any:
        """Video tool service (trim, crop, convert, ...)."""
        return self.resolve(self.KEY_VIDEO)

    @property
    def split(self) -> Any:
        """Split planning and rendering service."""
        return self.resolve(self.KEY_SPLIT)

    @property
    def ai(self) -> Any:
        """Transcription and analysis service."""
        return self.resolve(self.KEY_AI)

    @property
    def subtitles(self) -> Any:
        """Subtitle generation, styling and burn-in service."""
        return self.resolve(self.KEY_SUBTITLES)

    @property
    def export(self) -> Any:
        """Export queue service."""
        return self.resolve(self.KEY_EXPORT)

    @property
    def projects(self) -> Any:
        """Project store."""
        return self.resolve(self.KEY_PROJECTS)

    @property
    def notifications(self) -> Any:
        """Notification centre."""
        return self.resolve(self.KEY_NOTIFICATIONS)

    @property
    def plugins(self) -> Any:
        """Plugin registry."""
        return self.resolve(self.KEY_PLUGINS)
