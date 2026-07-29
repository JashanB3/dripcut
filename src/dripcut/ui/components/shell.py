"""Application chrome: sidebar, top bar and status bar.

These are the only components that touch Gradio directly. They return small
dataclasses holding the created controls so :mod:`dripcut.ui.app` can wire events
without reaching into the widget tree, and every rendering decision that produces
markup is delegated to :mod:`dripcut.ui.components.widgets`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import gradio as gr

from dripcut import APP_NAME, __version__
from dripcut.ui.components.widgets import status_dot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

__all__ = [
    "NavItem",
    "Sidebar",
    "StatusBar",
    "TopBar",
    "build_sidebar",
    "build_statusbar",
    "build_topbar",
    "render_statusbar",
]


@dataclass(frozen=True, slots=True)
class NavItem:
    """One sidebar destination.

    Attributes:
        key: Page identifier used by the router.
        label: Text shown in the sidebar.
        icon: Single glyph rendered before the label.
        group: Section heading; consecutive items sharing a group are grouped.
    """

    key: str
    label: str
    icon: str = "\u25a0"
    group: str = "Workspace"


@dataclass(slots=True)
class Sidebar:
    """The created sidebar controls."""

    column: Any
    buttons: dict[str, gr.Button] = field(default_factory=dict)


@dataclass(slots=True)
class TopBar:
    """Controls in the header strip above the page body."""

    theme_toggle: gr.Button
    palette_button: gr.Button
    heading: gr.HTML


@dataclass(slots=True)
class StatusBar:
    """The footer strip. ``html`` is refreshed by the app's status tick."""

    html: gr.HTML


def build_sidebar(items: Sequence[NavItem], *, active: str = "") -> Sidebar:
    """Create the brand block and navigation buttons.

    Args:
        items: Destinations, in display order.
        active: Key of the initially selected page.

    Returns:
        A :class:`Sidebar` whose ``buttons`` map page keys to buttons.
    """
    buttons: dict[str, gr.Button] = {}
    with gr.Column(elem_classes=["dc-sidebar"], scale=0, min_width=232) as column:
        gr.HTML(
            '<div class="dc-brand">'
            '<div class="dc-brand-mark"></div>'
            f'<div><div class="dc-brand-text">{APP_NAME}</div>'
            f'<div class="dc-brand-version">v{__version__}</div></div>'
            "</div>"
        )
        current_group = ""
        for item in items:
            if item.group != current_group:
                current_group = item.group
                gr.HTML(f'<div class="dc-nav-group">{item.group}</div>')
            classes = ["dc-nav-item"]
            if item.key == active:
                classes.append("dc-active")
            buttons[item.key] = gr.Button(
                f"{item.icon}  {item.label}",
                elem_classes=classes,
                elem_id=f"dc-nav-{item.key}",
                variant="secondary",
            )
    return Sidebar(column=column, buttons=buttons)


def build_topbar(*, title: str = "", subtitle: str = "") -> TopBar:
    """Create the header strip: page heading, palette trigger and theme toggle."""
    from dripcut.ui.components.widgets import page_header  # noqa: PLC0415

    with gr.Row(equal_height=True):
        heading = gr.HTML(page_header(title, subtitle), elem_classes=["dc-page-head-slot"])
        with gr.Column(scale=0, min_width=210), gr.Row():
            palette_button = gr.Button(
                "\u2318K  Commands",
                elem_classes=["dc-btn", "dc-btn-quiet"],
                elem_id="dc-palette-button",
                scale=0,
            )
            theme_toggle = gr.Button(
                "\u25d0",
                elem_classes=["dc-btn", "dc-btn-quiet"],
                elem_id="dc-theme-toggle",
                scale=0,
            )
    return TopBar(theme_toggle=theme_toggle, palette_button=palette_button, heading=heading)


def build_statusbar(initial: str = "") -> StatusBar:
    """Create the footer status strip."""
    return StatusBar(html=gr.HTML(initial, elem_classes=["dc-statusbar"]))


def render_statusbar(
    *,
    ready: bool,
    ai_label: str,
    ai_state: str,
    jobs_running: int,
    jobs_queued: int,
    output_label: str,
    notice: str = "",
) -> str:
    """Build the status-bar markup.

    Pure and side-effect free so the app can call it on every tick, and so its
    output can be asserted in tests without a browser.
    """
    engine_state = "on" if ready else "off"
    engine_label = "FFmpeg ready" if ready else "FFmpeg missing"

    if jobs_running:
        jobs_state, jobs_label = "busy", f"{jobs_running} running"
        if jobs_queued:
            jobs_label += f", {jobs_queued} queued"
    elif jobs_queued:
        jobs_state, jobs_label = "warn", f"{jobs_queued} queued"
    else:
        jobs_state, jobs_label = "on", "idle"

    segments = [
        status_dot(engine_state, engine_label),
        status_dot(ai_state, ai_label),
        status_dot(jobs_state, jobs_label),
        '<span class="dc-status-spacer"></span>',
    ]
    if notice:
        segments.append(f'<span class="dc-mono">{notice}</span>')
    segments.append(f'<span class="dc-mono">{output_label}</span>')
    segments.append('<span class="dc-kbd">\u2318K</span>')
    return "".join(segments)
