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

from dripcut import APP_NAME
from dripcut.ui.components.widgets import status_dot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

__all__ = [
    "NavGroup",
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


@dataclass(frozen=True, slots=True)
class NavGroup:
    """A disclosure in the sidebar.

    One labelled row that opens to reveal the pages underneath it. Grouping the
    five making tools behind "Create" keeps the sidebar to three top-level
    destinations, which is the whole point: Home, Create, Projects.

    Attributes:
        key: Identifier for the group itself, not a page.
        label: Row text.
        icon: Glyph before the label.
        items: Page keys revealed when the group is open, in display order.
    """

    key: str
    label: str
    icon: str
    items: tuple[str, ...]


@dataclass(slots=True)
class Sidebar:
    """The created sidebar controls.

    Attributes:
        column: The sidebar container.
        buttons: Page key to its navigation button.
        toggles: Group key to its disclosure row.
        panels: Group key to the column that row shows and hides.
    """

    column: Any
    buttons: dict[str, gr.Button] = field(default_factory=dict)
    toggles: dict[str, gr.Button] = field(default_factory=dict)
    panels: dict[str, Any] = field(default_factory=dict)


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


def _nav_button(item: NavItem, *, active: bool, nested: bool = False) -> gr.Button:
    """One navigation row."""
    classes = ["dc-nav-item"]
    if nested:
        classes.append("dc-nav-sub")
    if active:
        classes.append("dc-active")
    return gr.Button(
        f"{item.icon}\u2003{item.label}",
        elem_classes=classes,
        elem_id=f"dc-nav-{item.key}",
        variant="secondary",
    )


def build_sidebar(
    items: Sequence[NavItem],
    layout: Sequence[NavItem | NavGroup],
    *,
    active: str = "",
    open_groups: Sequence[str] = (),
) -> Sidebar:
    """Create the brand mark and the navigation sidebar.

    Args:
        items: Every destination, used to resolve the page keys a group names.
        layout: What the sidebar shows, in order. A :class:`NavItem` is a row of
            its own; a :class:`NavGroup` is a disclosure holding rows.
        active: Key of the initially selected page.
        open_groups: Group keys that start expanded.

    Returns:
        A :class:`Sidebar` exposing every control the router needs to update.
    """
    by_key = {item.key: item for item in items}
    sidebar = Sidebar(column=None)
    opened = set(open_groups)

    with gr.Column(elem_classes=["dc-sidebar"], scale=0, min_width=248) as column:
        gr.HTML(
            '<div class="dc-brand">'
            '<span class="dc-brand-mark" aria-hidden="true"></span>'
            f'<span class="dc-brand-text" aria-label="{APP_NAME}">DripCut</span>'
            "</div>"
        )
        for entry in layout:
            if isinstance(entry, NavGroup):
                is_open = entry.key in opened
                toggle_classes = ["dc-nav-item", "dc-nav-toggle"]
                if is_open:
                    toggle_classes.append("dc-open")
                sidebar.toggles[entry.key] = gr.Button(
                    f"{entry.icon}\u2003{entry.label}",
                    elem_classes=toggle_classes,
                    elem_id=f"dc-nav-group-{entry.key}",
                    variant="secondary",
                )
                with gr.Column(
                    elem_classes=["dc-nav-panel"], visible=is_open
                ) as panel:
                    for key in entry.items:
                        child = by_key.get(key)
                        if child is None:
                            continue
                        sidebar.buttons[key] = _nav_button(
                            child, active=key == active, nested=True
                        )
                sidebar.panels[entry.key] = panel
                continue

            if entry.key == "__rule__":
                gr.HTML('<div class="dc-nav-rule"></div>')
                continue
            sidebar.buttons[entry.key] = _nav_button(entry, active=entry.key == active)

    sidebar.column = column
    return sidebar


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
    engine_label = "Render ready" if ready else "Video engine missing"

    if jobs_running:
        jobs_state, jobs_label = "busy", f"{jobs_running} creating"
        if jobs_queued:
            jobs_label += f", {jobs_queued} waiting"
    elif jobs_queued:
        jobs_state, jobs_label = "warn", f"{jobs_queued} waiting"
    else:
        jobs_state, jobs_label = "on", "Ready"

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
