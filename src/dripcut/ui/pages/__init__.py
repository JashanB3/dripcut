"""Page registry.

The single list in :func:`build_pages` is the application's site map: the sidebar,
the router and the command palette are all derived from it, so adding a page means
appending one entry and nothing else.
"""

from __future__ import annotations

from dripcut.ui.components.shell import NavItem
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
        PluginsPage(),
        SettingsPage(),
    ]


def nav_items(pages: list[Page]) -> list[NavItem]:
    """Sidebar entries derived from the page list."""
    return [
        NavItem(key=page.key, label=page.label, icon=page.icon, group=page.group)
        for page in pages
    ]
