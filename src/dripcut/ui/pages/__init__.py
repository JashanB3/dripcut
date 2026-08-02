"""Page registry.

The single list in :func:`build_pages` is the application's site map: the sidebar,
the router and the command palette are all derived from it, so adding a page means
appending one entry and nothing else.
"""

from __future__ import annotations

from dripcut.ui.components.shell import NavGroup, NavItem
from dripcut.ui.pages.ai_studio import AIStudioPage
from dripcut.ui.pages.base import Page, PageContext
from dripcut.ui.pages.batch import BatchPage
from dripcut.ui.pages.dashboard import DashboardPage
from dripcut.ui.pages.exports import ExportsPage
from dripcut.ui.pages.plugins import PluginsPage
from dripcut.ui.pages.projects import ProjectsPage
from dripcut.ui.pages.settings import SettingsPage
from dripcut.ui.pages.split import SplitPage
from dripcut.ui.pages.subtitles import SubtitlesPage
from dripcut.ui.pages.workspace import WorkspacePage

__all__ = [
    "AIStudioPage",
    "BatchPage",
    "DashboardPage",
    "ExportsPage",
    "Page",
    "PageContext",
    "PluginsPage",
    "ProjectsPage",
    "SettingsPage",
    "SplitPage",
    "SubtitlesPage",
    "WorkspacePage",
    "build_pages",
    "nav_items",
    "nav_layout",
    "group_for",
]


def build_pages() -> list[Page]:
    """Every page, in sidebar order.

    Grouped by what the person is doing: get oriented, work on a file, then deal
    with the output and the system.
    """
    return [
        DashboardPage(),
        WorkspacePage(),
        SplitPage(),
        AIStudioPage(),
        SubtitlesPage(),
        BatchPage(),
        ExportsPage(),
        ProjectsPage(),
        SettingsPage(),
    ]


def nav_items(pages: list[Page]) -> list[NavItem]:
    """Sidebar entries derived from the page list."""
    return [
        NavItem(key=page.key, label=page.label, icon=page.icon, group=page.group)
        for page in pages
    ]


def nav_layout(items: list[NavItem]) -> list[NavItem | NavGroup]:
    """What the sidebar shows, in order.

    Three destinations carry the product: Home is where you land, Create holds
    the five tools that make something, and Projects is everything you have
    made. Downloads and Preferences sit below a rule because they are places you
    visit occasionally rather than things you set out to do.
    """
    by_key = {item.key: item for item in items}
    rule = NavItem(key="__rule__", label="", icon="")
    layout: list[NavItem | NavGroup] = []
    if "dashboard" in by_key:
        layout.append(by_key["dashboard"])
    making = [
        key
        for key in ("workspace", "split", "ai_studio", "subtitles", "batch")
        if key in by_key
    ]
    if making:
        layout.append(
            NavGroup(key="create", label="Create", icon="\u2726", items=tuple(making))
        )
    if "projects" in by_key:
        layout.append(by_key["projects"])
    tail = [key for key in ("exports", "settings") if key in by_key]
    if tail:
        layout.append(rule)
        layout.extend(by_key[key] for key in tail)
    return layout


def group_for(layout: list[NavItem | NavGroup], page_key: str) -> str:
    """The group key holding ``page_key``, or an empty string when it is top level."""
    for entry in layout:
        if isinstance(entry, NavGroup) and page_key in entry.items:
            return entry.key
    return ""
