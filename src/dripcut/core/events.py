"""A small synchronous event bus.

Engines publish; the UI, the notification centre and plugins subscribe. Keeping
this in the core layer is what lets an engine report progress without importing
Gradio, and what lets a plugin observe a render without patching internals.

Handlers run on the publishing thread and are individually guarded: a broken
subscriber logs a warning and never takes an export down with it.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dripcut.core.logging import get_logger

__all__ = ["EventName", "Event", "EventBus", "Subscription"]

_log = get_logger("core.events")


class EventName(StrEnum):
    """Every event DripCut publishes. Plugins may add their own namespaced names."""

    APP_READY = "app.ready"
    MEDIA_IMPORTED = "media.imported"
    MEDIA_PROBE_FAILED = "media.probe_failed"
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    JOB_QUEUED = "job.queued"
    JOB_STARTED = "job.started"
    JOB_PROGRESS = "job.progress"
    JOB_SUCCEEDED = "job.succeeded"
    JOB_FAILED = "job.failed"
    JOB_CANCELLED = "job.cancelled"
    SPLIT_PLANNED = "split.planned"
    TRANSCRIPT_READY = "transcript.ready"
    ANALYSIS_READY = "analysis.ready"
    NOTIFY = "notify"
    PLUGIN_LOADED = "plugin.loaded"
    SETTINGS_CHANGED = "settings.changed"


@dataclass(frozen=True, slots=True)
class Event:
    """An immutable notification carrying an arbitrary payload."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        """Convenience accessor for a payload key."""
        return self.payload.get(key, default)


@dataclass(frozen=True, slots=True)
class Subscription:
    """Handle returned by :meth:`EventBus.subscribe`; call :meth:`cancel` to detach."""

    bus: EventBus
    name: str
    handler: Callable[[Event], None]

    def cancel(self) -> None:
        """Remove the handler from the bus."""
        self.bus.unsubscribe(self.name, self.handler)


class EventBus:
    """Thread-safe fan-out of :class:`Event` values to registered handlers."""

    WILDCARD = "*"

    def __init__(self, *, history: int = 300) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._history: deque[Event] = deque(maxlen=history)

    def subscribe(self, name: str | EventName, handler: Callable[[Event], None]) -> Subscription:
        """Register ``handler`` for ``name`` (or ``"*"`` for every event)."""
        key = str(name)
        with self._lock:
            if handler not in self._handlers[key]:
                self._handlers[key].append(handler)
        return Subscription(self, key, handler)

    def subscribe_many(
        self, names: Iterable[str | EventName], handler: Callable[[Event], None]
    ) -> list[Subscription]:
        """Register one handler against several event names."""
        return [self.subscribe(name, handler) for name in names]

    def unsubscribe(self, name: str | EventName, handler: Callable[[Event], None]) -> None:
        """Detach a previously registered handler; unknown handlers are ignored."""
        key = str(name)
        with self._lock:
            if handler in self._handlers.get(key, []):
                self._handlers[key].remove(handler)

    def publish(self, name: str | EventName, /, **payload: Any) -> Event:
        """Publish an event and return it (handy for logging call sites)."""
        event = Event(name=str(name), payload=payload)
        with self._lock:
            self._history.append(event)
            handlers = list(self._handlers.get(event.name, ())) + list(
                self._handlers.get(self.WILDCARD, ())
            )
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001 - a bad subscriber must not break a render
                _log.warning("event handler failed for %s", event.name, exc_info=True)
        return event

    def recent(self, name: str | EventName | None = None, limit: int = 50) -> list[Event]:
        """Return recent events, newest last, optionally filtered by name."""
        with self._lock:
            events = list(self._history)
        if name is not None:
            key = str(name)
            events = [e for e in events if e.name == key]
        return events[-limit:]

    def clear(self) -> None:
        """Drop all handlers and history (used between tests)."""
        with self._lock:
            self._handlers.clear()
            self._history.clear()
