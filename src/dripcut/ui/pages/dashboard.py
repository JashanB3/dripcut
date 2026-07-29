"""Dashboard: what the app knows right now, and the fastest way into the work."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gradio as gr

from dripcut.ui.components.widgets import (
    banner,
    card,
    chips,
    empty_state,
    notes_list,
    stat_grid,
    table,
)
from dripcut.ui.pages.base import Page, PageContext

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

__all__ = ["DashboardPage"]


class DashboardPage(Page):
    """Landing page. Read-only by design: it reports, it does not mutate."""

    key = "dashboard"
    label = "Dashboard"
    icon = "\u25f4"
    group = "Overview"
    title = "Dashboard"
    subtitle = "Everything is local. Nothing leaves this machine."

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the dashboard."""
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            stats = gr.HTML(self._stats(ctx))
            with gr.Row():
                with gr.Column(scale=3):
                    recent = gr.HTML(self._recent(ctx))
                    capabilities = gr.HTML(self._capabilities(ctx))
                with gr.Column(scale=2):
                    activity = gr.HTML(self._activity(ctx))
                    storage = gr.HTML(self._storage(ctx))
            refresh = gr.Button(
                "Refresh",
                elem_classes=["dc-btn", "dc-btn-quiet"],
                elem_id="dc-primary-dashboard",
            )
            refresh.click(
                lambda: (
                    self._stats(ctx),
                    self._recent(ctx),
                    self._capabilities(ctx),
                    self._activity(ctx),
                    self._storage(ctx),
                ),
                outputs=[stats, recent, capabilities, activity, storage],
            )
        return column

    # ------------------------------------------------------------------ panels

    def _stats(self, ctx: PageContext) -> str:
        """Headline counts across projects, clips and the job queue."""
        projects = ctx.projects.list_projects()
        clips = sum(getattr(project, "clip_count", 0) for project in projects)
        counts = ctx.queue.stats()
        return stat_grid(
            [
                ("Projects", len(projects)),
                ("Clips planned", clips),
                ("Jobs done", counts.get("succeeded", 0)),
                ("In flight", counts.get("running", 0) + counts.get("queued", 0)),
            ]
        )

    def _recent(self, ctx: PageContext) -> str:
        """Recently imported media, newest first."""
        recent = ctx.media.recent(limit=ctx.settings.ui.recent_limit)
        if not recent:
            return card(
                empty_state(
                    "No media yet",
                    "Open Split and drop a video in to get started.",
                ),
                title="Recent media",
            )
        rows = []
        for path in recent:
            try:
                size = f"{path.stat().st_size / (1024 * 1024):.1f} MB"
            except OSError:
                size = "\u2014"
            rows.append((path.name, path.suffix.lstrip(".").upper() or "\u2014", size))
        return card(table(["File", "Type", "Size"], rows), title="Recent media")

    def _capabilities(self, ctx: PageContext) -> str:
        """Which optional subsystems are usable right now."""
        status = ctx.ai.status()
        ready, missing = [], []
        (ready if status["whisper_installed"] else missing).append("Transcription")
        (ready if status["ollama_up"] else missing).append("Ollama")
        (ready if status["ollama_model_installed"] else missing).append(
            f"Model {status['ollama_model']}"
        )
        plugin_names = [record.meta.name for record in ctx.plugins.records() if record.enabled]
        body = chips(ready, mint=ready) + chips(missing)
        if plugin_names:
            body += f'<div class="dc-note-detail">Plugins: {", ".join(plugin_names)}</div>'
        if missing:
            body += banner(
                "Video tools all work without these. Run 'dripcut doctor' for setup steps.",
                level="info",
            )
        return card(body, title="Capabilities", eyebrow="AI is optional")

    def _activity(self, ctx: PageContext) -> str:
        """The notification centre's recent entries."""
        return card(notes_list(ctx.notifications.recent(limit=8)), title="Activity")

    def _storage(self, ctx: PageContext) -> str:
        """Where things are written, and how much room is left."""
        from dripcut.utils.fs import free_space_gb  # noqa: PLC0415

        report = ctx.projects.storage_report()
        rows = [
            ("Output", str(ctx.output_dir)),
            ("Projects", str(ctx.paths.projects)),
            ("Cache", str(ctx.paths.cache)),
            ("Free", f"{free_space_gb(ctx.output_dir):.1f} GB"),
        ]
        if isinstance(report, dict):
            for label, value in report.items():
                rows.append((str(label).replace("_", " ").title(), str(value)))
        return card(table(["Location", "Path"], rows), title="Storage")

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the dashboard's own refresh action."""
        return [
            *super().commands(),
            {
                "label": "Refresh dashboard",
                "group": "Dashboard",
                "target": "dc-primary-dashboard",
                "keywords": "reload update stats",
            },
        ]
