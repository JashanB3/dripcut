"""Logging setup: Rich console for humans, rotating file for post-mortems.

The console handler is intentionally quiet (INFO, no module paths) because the
launcher output doubles as the app's splash screen. The file handler keeps DEBUG
with full context so a user can attach ``~/Library/Logs`` style output to a bug
report without reproducing the failure.
"""

from __future__ import annotations

import logging
import logging.handlers
from typing import Any

from dripcut.core.paths import app_paths

__all__ = ["setup_logging", "get_logger", "LOG_FORMAT_FILE"]

LOG_FORMAT_FILE = "%(asctime)s | %(levelname)-8s | %(name)-34s | %(message)s"
_CONFIGURED = False


def setup_logging(level: str = "INFO", *, quiet: bool = False) -> logging.Logger:
    """Configure the root ``dripcut`` logger exactly once per process.

    Args:
        level: Console log level name.
        quiet: When true the console handler is dropped entirely (used by
            ``--json`` CLI output so machine-readable stdout stays clean).

    Returns:
        The configured ``dripcut`` logger.
    """
    global _CONFIGURED
    logger = logging.getLogger("dripcut")
    if _CONFIGURED:
        logger.setLevel(logging.DEBUG)
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not quiet:
        console_handler = _build_console_handler(level)
        logger.addHandler(console_handler)

    log_file = app_paths().logs / "dripcut.log"
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
    except OSError:
        # Logging must never stop the app from starting; fall back to console-only.
        logger.warning("could not open log file at %s; continuing without file logging", log_file)
    else:
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT_FILE))
        logger.addHandler(file_handler)

    # Third-party libraries are noisy on import; keep them out of the console.
    for noisy in ("httpx", "urllib3", "faster_whisper", "matplotlib", "PIL", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logger.debug("logging initialised (console=%s, file=%s)", level, log_file)
    return logger


def _build_console_handler(level: str) -> logging.Handler:
    """Rich handler when available, plain stream handler otherwise."""
    resolved = getattr(logging, str(level).upper(), logging.INFO)
    try:
        from rich.logging import RichHandler

        handler: logging.Handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            show_time=True,
            omit_repeated_times=False,
            markup=False,
            log_time_format="[%H:%M:%S]",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
    except ImportError:  # pragma: no cover - rich is a hard dependency
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.setLevel(resolved)
    return handler


def get_logger(name: str, **context: Any) -> logging.Logger:
    """Return a namespaced child logger, e.g. ``get_logger("engines.video")``."""
    logger = logging.getLogger(f"dripcut.{name}" if not name.startswith("dripcut") else name)
    if context:
        logger = logging.LoggerAdapter(logger, context)  # type: ignore[assignment]
    return logger
