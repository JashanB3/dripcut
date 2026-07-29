"""Cancellation and throttling primitives used by long-running engines."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

__all__ = ["CancelToken", "Throttle", "OperationCancelled"]


class OperationCancelled(RuntimeError):
    """Raised inside a worker when its :class:`CancelToken` has been tripped."""


class CancelToken:
    """A thread-safe cooperative cancellation flag.

    Engines call :meth:`raise_if_cancelled` between FFmpeg invocations and inside
    progress callbacks, so cancelling an export never leaves a half-written file
    behind without the caller knowing.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        """True once :meth:`cancel` has been called."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Request cancellation. Safe to call from any thread, more than once."""
        self._event.set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`OperationCancelled` if cancellation was requested."""
        if self._event.is_set():
            raise OperationCancelled("operation cancelled")

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or ``timeout`` elapses."""
        return self._event.wait(timeout)


class Throttle:
    """Drop callbacks that arrive faster than ``interval`` seconds apart.

    FFmpeg emits progress lines several times per second; the UI only needs a few
    updates per second, and every skipped update is a saved round-trip.
    """

    __slots__ = ("_interval", "_last", "_lock")

    def __init__(self, interval: float = 0.25) -> None:
        self._interval = max(0.0, interval)
        self._last = 0.0
        self._lock = threading.Lock()

    def ready(self, *, force: bool = False) -> bool:
        """True when enough time has passed since the last accepted call."""
        now = time.monotonic()
        with self._lock:
            if force or now - self._last >= self._interval:
                self._last = now
                return True
        return False

    def wrap(self, func: Callable[..., None]) -> Callable[..., None]:
        """Return ``func`` guarded by this throttle."""

        def _throttled(*args: object, **kwargs: object) -> None:
            if self.ready():
                func(*args, **kwargs)

        return _throttled
