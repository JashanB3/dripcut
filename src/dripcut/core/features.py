"""Small environment-backed feature switches for the hosted MVP profile."""

from __future__ import annotations

import os


def enabled(name: str, *, default: bool = False) -> bool:
    """Return a boolean environment switch without accepting ambiguous values."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def mvp_profile() -> bool:
    """Keep resource-heavy product paths off on constrained hosted instances."""
    return enabled("DRIPCUT_MVP_PROFILE", default=False)

