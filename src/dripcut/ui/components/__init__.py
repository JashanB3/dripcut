"""Reusable interface components.

Split by dependency rather than by widget: :mod:`widgets` is pure HTML and imports
nothing from Gradio, while :mod:`shell` creates real controls. Pages import from
this package so the split can change without touching every page.
"""

from __future__ import annotations

from dripcut.ui.components.shell import (
    NavItem,
    Sidebar,
    StatusBar,
    TopBar,
    build_sidebar,
    build_statusbar,
    build_topbar,
    render_statusbar,
)
from dripcut.ui.components.widgets import (
    banner,
    card,
    chips,
    clip_card,
    commands_script,
    empty_state,
    kbd,
    notes_list,
    page_header,
    project_card,
    rail,
    splash,
    stat_grid,
    status_dot,
    table,
    timecode,
    timeline_strip,
)

__all__ = [
    "NavItem",
    "Sidebar",
    "StatusBar",
    "TopBar",
    "banner",
    "build_sidebar",
    "build_statusbar",
    "build_topbar",
    "card",
    "chips",
    "clip_card",
    "commands_script",
    "empty_state",
    "kbd",
    "notes_list",
    "page_header",
    "project_card",
    "rail",
    "render_statusbar",
    "splash",
    "stat_grid",
    "status_dot",
    "table",
    "timecode",
    "timeline_strip",
]
