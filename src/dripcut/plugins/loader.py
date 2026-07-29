"""Plugin discovery and lifecycle.

Two sources, both offline:

1. Installed distributions declaring the ``dripcut.plugins`` entry-point group.
2. Loose ``.py`` files in ``<app home>/plugins`` - the zero-packaging path for a
   user writing a one-off automation.

A plugin that raises during import or registration is recorded as failed and the app
continues. A broken third-party extension must never stop someone editing video.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dripcut.core.errors import PluginError
from dripcut.core.events import Event, EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.plugins.api import Plugin, PluginContext, PluginMeta, ToolAction

__all__ = ["PluginRecord", "PluginRegistry"]

_log = get_logger("plugins.loader")

ENTRY_POINT_GROUP = "dripcut.plugins"


@dataclass(slots=True)
class PluginRecord:
    """A discovered plugin plus its runtime state."""

    meta: PluginMeta
    instance: Plugin | None
    source: str
    enabled: bool = True
    error: str = ""

    @property
    def status(self) -> str:
        """``active``, ``disabled`` or ``failed``."""
        if self.error:
            return "failed"
        return "active" if self.enabled else "disabled"


class PluginRegistry:
    """Discovers, registers and exposes plugin contributions."""

    def __init__(self, context: PluginContext, events: EventBus) -> None:
        self.context = context
        self.events = events
        self._records: dict[str, PluginRecord] = {}
        self._tools: dict[str, ToolAction] = {}
        events.subscribe(EventBus.WILDCARD, self._fan_out)

    # ------------------------------------------------------------------ discovery

    def discover(
        self, *, extra_dirs: list[Path] | None = None, disabled: list[str] | None = None
    ) -> list[PluginRecord]:
        """Find and register every available plugin."""
        blocked = set(disabled or [])
        for meta_source, plugin_cls in [*self._from_entry_points(), *self._from_directories(extra_dirs)]:
            try:
                instance = plugin_cls()
                meta = getattr(instance, "meta", None) or PluginMeta(
                    id=plugin_cls.__name__.lower(), name=plugin_cls.__name__
                )
                if not meta.compatible:
                    raise PluginError(
                        f"{meta.name} targets plugin API v{meta.api_version}, "
                        f"this build provides v1."
                    )
                record = PluginRecord(
                    meta=meta, instance=instance, source=meta_source, enabled=meta.id not in blocked
                )
                self._records[meta.id] = record
                if record.enabled:
                    self._activate(record)
            except Exception as exc:  # noqa: BLE001 - never let a plugin break startup
                name = getattr(plugin_cls, "__name__", "unknown")
                _log.warning("plugin %s failed to load: %s", name, exc)
                self._records[name] = PluginRecord(
                    meta=PluginMeta(id=name, name=name),
                    instance=None,
                    source=meta_source,
                    enabled=False,
                    error=str(exc)[:200],
                )
        return self.records()

    def _from_entry_points(self) -> list[tuple[str, type[Plugin]]]:
        """Load plugin classes advertised through packaging metadata."""
        found: list[tuple[str, type[Plugin]]] = []
        try:
            from importlib.metadata import entry_points  # noqa: PLC0415

            for entry in entry_points(group=ENTRY_POINT_GROUP):
                try:
                    loaded = entry.load()
                except Exception as exc:  # noqa: BLE001
                    _log.warning("entry point %s failed: %s", entry.name, exc)
                    continue
                if isinstance(loaded, type) and issubclass(loaded, Plugin):
                    found.append((f"entry-point:{entry.name}", loaded))
        except Exception:  # noqa: BLE001 - metadata is unavailable in odd installs
            _log.debug("entry point discovery unavailable", exc_info=True)
        return found

    def _from_directories(self, extra_dirs: list[Path] | None) -> list[tuple[str, type[Plugin]]]:
        """Import loose ``.py`` files from the user plugin folders."""
        directories = [self.context.data_dir, *(extra_dirs or [])]
        found: list[tuple[str, type[Plugin]]] = []
        for directory in directories:
            if not directory or not Path(directory).is_dir():
                continue
            for module_path in sorted(Path(directory).glob("*.py")):
                if module_path.name.startswith("_"):
                    continue
                module_name = f"dripcut_userplugin_{module_path.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("could not import %s: %s", module_path.name, exc)
                    continue
                for attribute in vars(module).values():
                    if (
                        isinstance(attribute, type)
                        and issubclass(attribute, Plugin)
                        and attribute is not Plugin
                    ):
                        found.append((f"file:{module_path.name}", attribute))
        return found

    # ------------------------------------------------------------------ lifecycle

    def _activate(self, record: PluginRecord) -> None:
        """Run a plugin's registration hooks and collect its contributions."""
        instance = record.instance
        if instance is None:
            return
        instance.register(self.context)

        for tool in instance.tools(self.context) or ():
            self._tools[tool.id] = tool

        split_registry = self.context.service("split_registry")
        if split_registry is not None:
            for strategy in instance.split_strategies(self.context) or ():
                try:
                    split_registry.register(strategy, replace=True)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("plugin %s split strategy rejected: %s", record.meta.id, exc)

        styles = instance.caption_styles(self.context) or {}
        if styles:
            from dripcut.engines.subtitle.styles import CAPTION_PRESETS  # noqa: PLC0415

            CAPTION_PRESETS.update(styles)

        self.events.publish(
            EventName.PLUGIN_LOADED, name=record.meta.name, plugin_id=record.meta.id
        )
        _log.info("plugin active: %s v%s (%s)", record.meta.name, record.meta.version, record.source)

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRecord:
        """Enable or disable a plugin.

        Enabling re-runs registration; disabling detaches its tools. Split strategies
        already registered stay put until restart, which is noted in the UI.
        """
        record = self._records.get(plugin_id)
        if record is None:
            raise PluginError(f"Plugin {plugin_id!r} is not installed.")
        if enabled and not record.enabled and record.instance is not None:
            record.enabled = True
            record.error = ""
            try:
                self._activate(record)
            except Exception as exc:  # noqa: BLE001
                record.enabled = False
                record.error = str(exc)[:200]
        elif not enabled and record.enabled:
            record.enabled = False
            self._tools = {
                key: tool for key, tool in self._tools.items() if not key.startswith(f"{plugin_id}.")
            }
        return record

    def shutdown(self) -> None:
        """Let every active plugin release its resources."""
        for record in self._records.values():
            if record.instance is not None and record.enabled:
                try:
                    record.instance.shutdown()
                except Exception:  # noqa: BLE001
                    _log.debug("plugin shutdown failed: %s", record.meta.id, exc_info=True)

    # -------------------------------------------------------------------- queries

    def records(self) -> list[PluginRecord]:
        """Every discovered plugin, ordered by name."""
        return sorted(self._records.values(), key=lambda record: record.meta.name.lower())

    def tools(self, *, group: str | None = None) -> list[ToolAction]:
        """Tool actions contributed by enabled plugins."""
        tools = list(self._tools.values())
        if group:
            tools = [tool for tool in tools if tool.group == group]
        return sorted(tools, key=lambda tool: (tool.group, tool.label))

    def tool(self, tool_id: str) -> ToolAction | None:
        """Look up a single tool action."""
        return self._tools.get(tool_id)

    def table_rows(self) -> list[list[Any]]:
        """Rows for the Plugins page table."""
        return [
            [
                record.meta.name,
                record.meta.version,
                record.status,
                record.meta.description or record.error or "-",
                record.source,
            ]
            for record in self.records()
        ]

    def _fan_out(self, event: Event) -> None:
        """Forward every bus event to enabled plugins."""
        for record in self._records.values():
            if record.enabled and record.instance is not None:
                try:
                    record.instance.on_event(event)
                except Exception:  # noqa: BLE001
                    _log.debug("plugin %s event handler failed", record.meta.id, exc_info=True)
