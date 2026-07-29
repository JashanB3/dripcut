"""Notification centre.

Every user-visible message goes through here: engine failures, finished exports,
plugin warnings. Keeping one list means the bell icon, the toast and the status bar
can never disagree, and the UI polls a single source.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from dripcut.core.events import Event, EventBus, EventName

__all__ = ["Notification", "NotificationService"]

Level = Literal["info", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Notification:
    """One entry in the notification centre."""

    message: str
    level: Level = "info"
    detail: str = ""
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def icon(self) -> str:
        """Glyph shown in the list."""
        return {"info": "\u2022", "success": "\u2713", "warning": "\u26a0", "error": "\u2715"}[
            self.level
        ]

    @property
    def age_label(self) -> str:
        """Relative time, e.g. ``2m ago``."""
        delta = max(0.0, time.time() - self.created_at)
        if delta < 45:
            return "just now"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        return f"{int(delta // 3600)}h ago"


class NotificationService:
    """Bounded, thread-safe notification log wired to the event bus."""

    def __init__(self, events: EventBus, *, limit: int = 60) -> None:
        self.events = events
        self._items: deque[Notification] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._seen = 0
        events.subscribe_many(
            [
                EventName.JOB_SUCCEEDED,
                EventName.JOB_FAILED,
                EventName.JOB_CANCELLED,
                EventName.TRANSCRIPT_READY,
                EventName.PLUGIN_LOADED,
                EventName.NOTIFY,
            ],
            self._on_event,
        )

    def push(self, message: str, level: Level = "info", *, detail: str = "") -> Notification:
        """Add a notification and return it."""
        note = Notification(message=message, level=level, detail=detail)
        with self._lock:
            self._items.append(note)
        return note

    def info(self, message: str, *, detail: str = "") -> Notification:
        """Add an informational notification."""
        return self.push(message, "info", detail=detail)

    def success(self, message: str, *, detail: str = "") -> Notification:
        """Add a success notification."""
        return self.push(message, "success", detail=detail)

    def warning(self, message: str, *, detail: str = "") -> Notification:
        """Add a warning notification."""
        return self.push(message, "warning", detail=detail)

    def error(self, message: str, *, detail: str = "") -> Notification:
        """Add an error notification."""
        return self.push(message, "error", detail=detail)

    def recent(self, limit: int = 20) -> list[Notification]:
        """Newest notifications first."""
        with self._lock:
            return list(self._items)[-limit:][::-1]

    @property
    def unread(self) -> int:
        """How many notifications arrived since :meth:`mark_read`."""
        with self._lock:
            return max(0, len(self._items) - self._seen)

    def mark_read(self) -> None:
        """Mark everything as seen."""
        with self._lock:
            self._seen = len(self._items)

    def clear(self) -> None:
        """Empty the centre."""
        with self._lock:
            self._items.clear()
            self._seen = 0

    def _on_event(self, event: Event) -> None:
        """Translate bus events into notifications."""
        title = str(event.get("title", ""))
        if event.name == EventName.JOB_SUCCEEDED:
            outputs = event.get("outputs") or []
            detail = f"{len(outputs)} file{'s' if len(outputs) != 1 else ''} written" if outputs else ""
            self.success(f"{title} finished", detail=event.get("message") or detail)
        elif event.name == EventName.JOB_FAILED:
            self.error(f"{title} failed", detail=str(event.get("hint") or event.get("error") or ""))
        elif event.name == EventName.JOB_CANCELLED:
            self.info(f"{title} cancelled")
        elif event.name == EventName.TRANSCRIPT_READY:
            self.success("Transcript ready", detail=f"{event.get('words', 0)} words")
        elif event.name == EventName.PLUGIN_LOADED:
            self.info(f"Plugin loaded: {event.get('name', 'unknown')}")
        elif event.name == EventName.NOTIFY:
            self.push(
                str(event.get("message", "")),
                str(event.get("level", "info")),  # type: ignore[arg-type]
                detail=str(event.get("detail", "")),
            )
