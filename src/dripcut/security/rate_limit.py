"""Small process-local rate limiter for auth and expensive API entry points."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class InMemoryRateLimiter:
    """Bound request bursts locally; hosted deployments can replace this with Redis."""

    def __init__(self, *, window_seconds: int = 60, clock=time.monotonic) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self._clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(True, limit, 0, 0)
        now = float(self._clock())
        cutoff = now - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                retry_after = max(1, int(self.window_seconds - (now - requests[0]) + 0.999))
                return RateLimitResult(False, limit, 0, retry_after)
            requests.append(now)
            return RateLimitResult(True, limit, max(0, limit - len(requests)), 0)
