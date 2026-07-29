"""Plugin system: extend DripCut without forking it."""

from __future__ import annotations

from dripcut.plugins.api import Plugin, PluginContext, PluginMeta, ToolAction
from dripcut.plugins.loader import PluginRegistry

__all__ = ["Plugin", "PluginContext", "PluginMeta", "PluginRegistry", "ToolAction"]
