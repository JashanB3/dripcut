"""Dashboard: the quickest path back to the latest render."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.ui.components.widgets import (
    card,
    empty_state,
    recent_strip,
    studio_bar,
    table,
    tool_cards,
)
from dripcut.ui.pages.base import Page, PageContext
from dripcut.utils.fs import human_size

__all__ = ["DashboardPage"]


class DashboardPage(Page):
    """A product-facing landing page focused on recent output."""

    key = "dashboard"
    label = "Home"
    icon = "\u25f4"
    group = "Studio"
    title = "Home"
    subtitle = "Start something, or pick up where you left off."

    #: The tool deck: ``(page key, glyph, name, what it is for)``.
    TOOLS: tuple[tuple[str, str, str, str], ...] = (
        ("split", "\u2702", "Make clips", "Cut one video into posts"),
        ("subtitles", "\u2263", "Captions", "Burn in readable subtitles"),
        ("ai_studio", "\u25c8", "AI clips", "Find the moments worth posting"),
        ("workspace", "\u25a3", "Edit tools", "Trim, crop, convert, watermark"),
        ("batch", "\u2637", "Bulk edit", "Run one action across a folder"),
        ("exports", "\u2913", "Downloads", "Everything rendered, ready to grab"),
    )

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the home deck."""
        last = self._last_render(ctx)
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            gr.HTML(self._studio(ctx, last))
            gr.HTML(tool_cards(self.TOOLS))

            gr.HTML(
                '<div class="dc-section-title">Pick up where you left off</div>'
            )
            recent = gr.HTML(self._recent_projects(ctx))

            with gr.Row(elem_classes=["dc-home-split"], equal_height=False):
                latest = gr.HTML(self._recent(last))
                with gr.Column(
                    scale=0, min_width=300, elem_classes=["dc-side-card"]
                ):
                    ready = gr.HTML(self._ready_panel(last))
                    download = gr.DownloadButton(
                        "Download ZIP",
                        value=self._archive_value(last),
                        visible=True,
                        interactive=bool(self._archive_value(last)),
                        variant="primary",
                    )
                    refresh = gr.Button(
                        "Refresh",
                        elem_classes=["dc-btn", "dc-btn-quiet"],
                        elem_id="dc-primary-dashboard",
                    )

            def refresh_dashboard() -> tuple[str, str, str, Any]:
                fresh = self._last_render(ctx)
                archive = self._archive_value(fresh)
                return (
                    self._recent_projects(ctx),
                    self._recent(fresh),
                    self._ready_panel(fresh),
                    gr.update(value=archive, interactive=bool(archive)),
                )

            refresh.click(
                refresh_dashboard, outputs=[recent, latest, ready, download]
            )
        return column

    # ------------------------------------------------------------------ panels

    def _studio(self, ctx: PageContext, last: dict[str, Any] | None) -> str:
        """The masthead, including whether the machine is ready to render."""
        counts = ctx.queue.stats()
        running = int(counts.get("running", 0)) + int(counts.get("queued", 0))
        try:
            engine_ok = bool(ctx.container.resolve("ffmpeg").version())
        except Exception:  # noqa: BLE001 - the masthead must never raise
            engine_ok = False
        try:
            ai = ctx.ai.status()
            ai_ready = bool(ai.get("whisper_installed"))
        except Exception:  # noqa: BLE001 - ditto
            ai_ready = False

        signals = [
            ("Render engine", "on" if engine_ok else "off"),
            ("Captions", "on" if ai_ready else "warn"),
            (
                f"{running} in the queue" if running else "Queue clear",
                "busy" if running else "on",
            ),
        ]
        if last and self._archive_value(last):
            detail = (
                f"Your last render finished with "
                f"{int(last.get('clip_count', 0) or 0)} clips. "
                "Grab the ZIP below, or start the next one."
            )
        else:
            detail = (
                "Bring in a video and DripCut cuts it into captioned clips "
                "sized for the platform you are posting to."
            )
        return studio_bar(
            greeting="DripCut studio",
            headline="What will you clip today?",
            detail=detail,
            action="Make clips",
            action_target="split",
            secondary="Open projects",
            secondary_target="projects",
            signals=signals,
        )

    def _recent_projects(self, ctx: PageContext) -> str:
        """Recent projects, newest first."""
        try:
            summaries = ctx.projects.list_projects(limit=6)
        except Exception:  # noqa: BLE001 - a bad manifest must not blank the page
            summaries = []
        items = [
            {
                "name": item.name,
                "meta": f"{getattr(item, 'duration_label', '')} \u00b7 "
                f"{getattr(item, 'clip_count', 0)} clips \u00b7 "
                f"{getattr(item, 'updated_label', '')}".strip(" \u00b7"),
                "thumbnail": str(getattr(item, "thumbnail", "") or ""),
            }
            for item in summaries
        ]
        return recent_strip(items)

    def _ready_panel(self, last: dict[str, Any] | None) -> str:
        """The download side card: what is waiting, and how big it is.

        The button underneath is a real Gradio control, so this fragment covers
        only the description above it. When nothing has rendered it says so and
        points at the one action that fixes that.
        """
        archive = self._archive_value(last)
        if not archive or not last:
            return (
                '<div class="dc-ready dc-ready-empty">'
                '<div class="dc-ready-eyebrow">Your ZIP</div>'
                "<div class=\"dc-ready-headline\">Nothing rendered yet</div>"
                "<p>Make a set of clips and the archive lands here, "
                "ready to download in one click.</p>"
                "</div>"
            )
        path = Path(archive)
        size = human_size(path.stat().st_size) if path.exists() else "\u2014"
        clips = int(last.get("clip_count", 0) or 0)
        return (
            '<div class="dc-ready">'
            '<div class="dc-ready-eyebrow">Your ZIP</div>'
            f'<div class="dc-ready-headline">{clips} clips \u00b7 {size}</div>'
            f'<p class="dc-ready-file">{path.name}</p>'
            "</div>"
        )

    def _recent(self, last: dict[str, Any] | None) -> str:
        """Latest render details with the archive state."""
        if not last:
            return card(
                empty_state(
                    "No edit yet",
                    "Open Make Clips, upload a video, create clips, then download the ZIP here.",
                ),
                title="Latest edit",
            )
        archive = Path(str(last.get("archive", "")))
        rows = [
            ("Video", str(last.get("source", "Untitled"))),
            ("Status", str(last.get("status", "Done"))),
            ("Clips", str(last.get("clip_count", 0))),
            ("Format", str(last.get("output_format", "landscape")).title()),
            ("Subtitles", "Yes" if last.get("subtitles") else "No"),
            ("Archive", archive.name if archive.exists() else "Preparing again required"),
            ("Size", human_size(archive.stat().st_size) if archive.exists() else "Unavailable"),
            ("Rendered", self._when(last.get("created_at"))),
        ]
        return card(table(["Detail", "Value"], rows), title="Latest edit")

    @staticmethod
    def _last_render(ctx: PageContext) -> dict[str, Any] | None:
        """Read the last render record written by Split."""
        path = ctx.paths.cache / "last_render.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _archive_value(last: dict[str, Any] | None) -> str | None:
        if not last:
            return None
        archive = Path(str(last.get("archive", "")))
        return str(archive) if archive.exists() else None

    @staticmethod
    def _when(timestamp: Any) -> str:
        try:
            return datetime.fromtimestamp(float(timestamp)).strftime("%b %d, %I:%M %p")
        except (TypeError, ValueError, OSError):
            return "Just now"

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the dashboard refresh action."""
        return [
            *super().commands(),
            {
                "label": "Refresh dashboard",
                "group": "Dashboard",
                "target": "dc-primary-dashboard",
                "keywords": "reload update latest render download",
            },
        ]
