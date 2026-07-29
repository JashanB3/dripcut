"""Plugins: extend DripCut without forking it.

The registry does the discovery and lifecycle work; this page shows what it found,
lets a plugin be switched on or off (persisting the choice to settings.json), and
runs the tool actions plugins contribute.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dripcut.core.config import save_settings
from dripcut.ui.components.widgets import banner, card, chips, empty_state, stat_grid, table
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["PluginsPage"]


class PluginsPage(Page):
    """Inspect, toggle and run plugins."""

    key = "plugins"
    label = "Plugins"
    icon = "\u2726"
    group = "System"
    title = "Plugins"
    subtitle = "Drop a Python file in the plugins folder, or ship an entry point."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the plugins page."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            stats = gr.HTML(self._stats())
            listing = gr.HTML(self._listing())

            with gr.Row():
                chooser = gr.Dropdown(
                    choices=self._plugin_choices(),
                    label="Plugin",
                    elem_id="dc-plugins-chooser",
                    interactive=True,
                )
                enable = gr.Button(
                    "Enable", elem_classes=["dc-btn", "dc-btn-primary"],
                    elem_id="dc-primary-plugins", variant="primary",
                )
                disable = gr.Button(
                    "Disable", elem_classes=["dc-btn"], elem_id="dc-plugins-disable"
                )
                rescan = gr.Button(
                    "Rescan", elem_classes=["dc-btn", "dc-btn-quiet"], elem_id="dc-plugins-rescan"
                )

            with gr.Accordion("Contributed tools", open=True):
                tools = gr.HTML(self._tools())
                tool_chooser = gr.Dropdown(
                    choices=self._tool_choices(),
                    label="Tool",
                    elem_id="dc-plugins-tool",
                    interactive=True,
                )
                tool_source = gr.File(
                    label="Video for tools that need one",
                    type="filepath",
                    elem_classes=["dc-dropzone"],
                )
                run_tool = gr.Button(
                    "Run tool", elem_classes=["dc-btn", "dc-btn-primary"],
                    elem_id="dc-plugins-run", variant="primary",
                )
                tool_outputs = gr.Files(label="Tool output", visible=False)

            with gr.Accordion("Where plugins come from", open=False):
                gr.HTML(self._sources())

            panels = [stats, listing, chooser, tools, tool_chooser]

            enable.click(
                lambda pid: self._toggle(pid, True), inputs=chooser, outputs=[*panels, message]
            )
            disable.click(
                lambda pid: self._toggle(pid, False), inputs=chooser, outputs=[*panels, message]
            )
            rescan.click(self._rescan, outputs=[*panels, message])
            run_tool.click(
                self._run_tool,
                inputs=[tool_chooser, tool_source],
                outputs=[tool_outputs, message],
            )
        return column

    # ----------------------------------------------------------------- panels

    def _records(self) -> list[Any]:
        """Discovered plugin records."""
        if self._ctx is None:
            return []
        try:
            return self._ctx.plugins.records()
        except Exception:  # noqa: BLE001 - a broken plugin must not blank the page
            return []

    def _plugin_choices(self) -> list[tuple[str, str]]:
        """Dropdown entries as ``(label, plugin_id)``."""
        return [(f"{record.meta.name} ({record.status})", record.meta.id) for record in self._records()]

    def _tool_choices(self) -> list[tuple[str, str]]:
        """Dropdown entries for contributed tool actions."""
        if self._ctx is None:
            return []
        try:
            return [(f"{tool.icon} {tool.label}".strip(), tool.id) for tool in self._ctx.plugins.tools()]
        except Exception:  # noqa: BLE001 - ditto
            return []

    def _stats(self) -> str:
        """Counts across the registry."""
        records = self._records()
        active = [record for record in records if record.status == "active"]
        broken = [record for record in records if record.error]
        tool_count = len(self._tool_choices())
        return stat_grid(
            [
                ("Discovered", len(records)),
                ("Active", len(active)),
                ("Tools", tool_count),
                ("Broken", len(broken)),
            ]
        )

    def _listing(self) -> str:
        """The plugin table."""
        records = self._records()
        if not records:
            return card(
                empty_state(
                    "No plugins found",
                    "Three ship with DripCut; if none appear, reinstall with pip install -e .",
                ),
                title="Installed",
            )
        rows = [
            (
                record.meta.name,
                record.meta.id,
                record.meta.version,
                record.status,
                record.source,
                record.error or record.meta.description,
            )
            for record in records
        ]
        return card(
            table(["Plugin", "Id", "Version", "State", "Source", "Details"], rows, mono=(2,)),
            title="Installed",
        )

    def _tools(self) -> str:
        """Tool actions contributed by active plugins."""
        if self._ctx is None:
            return ""
        try:
            actions = self._ctx.plugins.tools()
        except Exception:  # noqa: BLE001 - ditto
            actions = []
        if not actions:
            return empty_state(
                "No tools contributed",
                "Plugins can add tools, split modes and caption styles.",
            )
        rows = [
            (
                tool.label,
                tool.group or "\u2014",
                "yes" if tool.needs_media else "no",
                tool.description,
            )
            for tool in actions
        ]
        return table(["Tool", "Group", "Needs a video", "What it does"], rows)

    def _sources(self) -> str:
        """Explain discovery, with the real folder path."""
        if self._ctx is None:
            return ""
        folder = self._ctx.paths.plugins
        tags: list[str] = []
        for record in self._records():
            tags.extend(record.meta.tags)
        body = (
            f'<div class="dc-note-detail">Entry points in the <span class="dc-mono">'
            f"dripcut.plugins</span> group are loaded automatically. Loose Python files in "
            f'<span class="dc-mono">{folder}</span> are loaded too, so a single-file plugin '
            f"needs no packaging.</div>"
        )
        if tags:
            body += chips(sorted(set(tags)))
        return body

    def _refresh(self) -> tuple[str, str, Any, str, Any]:
        """Rebuild everything that depends on the registry."""
        return (
            self._stats(),
            self._listing(),
            gr.update(choices=self._plugin_choices()),
            self._tools(),
            gr.update(choices=self._tool_choices()),
        )

    # ---------------------------------------------------------------- actions

    def _toggle(self, plugin_id: str | None, enabled: bool) -> tuple[Any, ...]:
        """Enable or disable a plugin and persist the choice."""
        if self._ctx is None or not plugin_id:
            return *self._refresh(), banner(
                "Choose a plugin first.", level="warning", title="Nothing selected"
            )
        record, error = safe_call(self._ctx.plugins.set_enabled, plugin_id, enabled)
        if error or record is None:
            return *self._refresh(), error

        settings = self._ctx.settings
        disabled = set(settings.disabled_plugins)
        if enabled:
            disabled.discard(plugin_id)
        else:
            disabled.add(plugin_id)
        settings.disabled_plugins = sorted(disabled)
        _, error = safe_call(save_settings, settings, self._ctx.paths.config_file)
        if error:
            return *self._refresh(), error

        state = "enabled" if enabled else "disabled"
        return *self._refresh(), banner(
            f"{record.meta.name} {state}.", level="success", title="Saved"
        )

    def _rescan(self) -> tuple[Any, ...]:
        """Re-run discovery, picking up files added since startup."""
        if self._ctx is None:
            return *self._refresh(), banner("Not ready yet.", level="error")
        _, error = safe_call(
            self._ctx.plugins.discover, disabled=self._ctx.settings.disabled_plugins
        )
        if error:
            return *self._refresh(), error
        return *self._refresh(), banner(
            f"Found {len(self._records())} plugin(s).", level="info", title="Rescanned"
        )

    def _run_tool(self, tool_id: str | None, source: str | None) -> tuple[Any, str]:
        """Run a contributed tool action against an optional source file."""
        if self._ctx is None or not tool_id:
            return gr.update(visible=False), banner(
                "Choose a tool first.", level="warning", title="Nothing selected"
            )
        tool = self._ctx.plugins.tool(tool_id)
        if tool is None:
            return gr.update(visible=False), banner(
                f"Tool {tool_id} is no longer available.",
                level="warning",
                title="Tool missing",
            )
        media = None
        if source:
            media, error = safe_call(self._ctx.media.import_file, source)
            if error:
                return gr.update(visible=False), error
        if tool.needs_media and media is None:
            return gr.update(visible=False), banner(
                f"'{tool.label}' needs a video. Add one above.",
                level="warning",
                title="Video required",
            )

        result, error = safe_call(tool.run, media)
        if error:
            return gr.update(visible=False), error

        paths = [str(item) for item in (result or []) if getattr(item, "exists", bool)()]
        if not paths:
            return gr.update(visible=False), banner(
                f"'{tool.label}' finished without producing a file.",
                level="info",
                title="Done",
            )
        return gr.update(value=paths, visible=True), banner(
            f"'{tool.label}' produced {len(paths)} file(s).", level="success", title="Done"
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus registry actions."""
        return [
            *super().commands(),
            {
                "label": "Rescan plugins",
                "group": "Plugins",
                "target": "dc-plugins-rescan",
                "keywords": "reload discover",
            },
            {
                "label": "Run a plugin tool",
                "group": "Plugins",
                "target": "dc-plugins-run",
                "keywords": "action execute",
            },
        ]
