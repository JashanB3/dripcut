"""Cross-cutting infrastructure: paths, config, logging, events, DI container."""

from __future__ import annotations

from dripcut.core.config import Settings, load_settings, save_settings
from dripcut.core.container import Container, ServiceContainer
from dripcut.core.errors import (
    DripCutError,
    ExportError,
    FFmpegError,
    MediaProbeError,
    ModelUnavailableError,
    PluginError,
    ValidationError,
)
from dripcut.core.events import Event, EventBus, EventName
from dripcut.core.logging import get_logger, setup_logging
from dripcut.core.paths import AppPaths, app_paths

__all__ = [
    "AppPaths",
    "Container",
    "DripCutError",
    "Event",
    "EventBus",
    "EventName",
    "ExportError",
    "FFmpegError",
    "MediaProbeError",
    "ModelUnavailableError",
    "PluginError",
    "ServiceContainer",
    "Settings",
    "ValidationError",
    "app_paths",
    "get_logger",
    "load_settings",
    "save_settings",
    "setup_logging",
]
