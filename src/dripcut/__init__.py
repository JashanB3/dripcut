"""DripCut - a local-first, offline AI video processing suite.

The package is organised in strict layers; nothing in an inner layer is allowed
to import from an outer one:

    utils      -> pure helpers, no DripCut imports
    core       -> configuration, logging, events, DI container, errors
    models     -> immutable domain objects (media, clips, transcripts, jobs)
    engines    -> capability implementations (ffmpeg, video, split, ai, subtitle, export)
    services   -> orchestration / use-cases consumed by any front-end
    plugins    -> third-party extension points
    ui         -> Gradio presentation layer (thin, no business logic)
    cli        -> process entry point and pre-flight checks
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_TAGLINE"]

__version__ = "1.0.0rc1"

APP_NAME = "DripCut"
APP_TAGLINE = "Edit your vibe in a few clicks"
