"""Projects: durable state.

A project is a manifest on disk holding a source, a plan, a caption style and the
files produced from them. This page is the front end to
:class:`~dripcut.services.project_service.ProjectService` and nothing else -- no
project logic lives here, only the forms that drive it.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dripcut.ui.components.widgets import (
    banner,
    card,
    empty_state,
    project_card,
    stat_grid,
    table,
)
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["ProjectsPage"]


class ProjectsPage(Page):
    """Manage saved projects and the space they occupy."""

    key = "projects"
    label = "Projects"
    icon = "\u25eb"
    group = "Output"
    title = "Projects"
    subtitle = "Saved work, on disk, in a format you can read without this app."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the projects page."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            stats = gr.HTML(self._stats())

            with gr.Row():
                with gr.Column(scale=2):
                    new_name = gr.Textbox(
                        label="New project name",
                        placeholder="Tuesday interview",
                        elem_id="dc-projects-name",
                    )
                    new_source = gr.File(
                        label="Source video (optional)",
                        type="filepath",
                        elem_classes=["dc-dropzone"],
                    )
                    create = gr.Button(
                        "Create project",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-primary-projects",
                    )
                with gr.Column(scale=3):
                    gallery = gr.HTML(self._gallery())

            listing = gr.HTML(self._listing())

            with gr.Accordion("Work on a project", open=True):
                chooser = gr.Dropdown(
                    choices=self._choices(),
                    label="Project",
                    elem_id="dc-projects-chooser",
                    interactive=True,
                )
                detail = gr.HTML()
                rename_to = gr.Textbox(label="New name", placeholder="Renamed project")
                with gr.Row():
                    open_button = gr.Button(
                        "Show details", elem_classes=["dc-btn"], elem_id="dc-projects-open"
                    )
                    rename_button = gr.Button(
                        "Rename", elem_classes=["dc-btn"], elem_id="dc-projects-rename"
                    )
                    duplicate_button = gr.Button(
                        "Duplicate", elem_classes=["dc-btn"], elem_id="dc-projects-duplicate"
                    )
                with gr.Row():
                    keep_outputs = gr.Checkbox(
                        value=True, label="Keep rendered files when deleting"
                    )
                    confirm = gr.Checkbox(
                        value=False,
                        label="Yes, delete this project",
                        elem_id="dc-projects-confirm",
                    )
                    delete_button = gr.Button(
                        "Delete", elem_classes=["dc-btn", "dc-btn-danger"],
                        elem_id="dc-projects-delete",
                    )

            with gr.Accordion("Storage", open=False):
                storage = gr.HTML(self._storage())
                purge = gr.Button(
                    "Purge cached thumbnails and proxies",
                    elem_classes=["dc-btn"],
                    elem_id="dc-projects-purge",
                )

            panels = [stats, gallery, listing, chooser, storage]

            create.click(
                self._create, inputs=[new_name, new_source], outputs=[*panels, message]
            )
            open_button.click(self._detail, inputs=chooser, outputs=[detail, message])
            rename_button.click(
                self._rename, inputs=[chooser, rename_to], outputs=[*panels, message]
            )
            duplicate_button.click(self._duplicate, inputs=chooser, outputs=[*panels, message])
            delete_button.click(
                self._delete,
                inputs=[chooser, keep_outputs, confirm],
                outputs=[*panels, message],
            )
            purge.click(self._purge, outputs=[storage, message])
        return column

    # ----------------------------------------------------------------- panels

    def _summaries(self) -> list[Any]:
        """Project summaries, newest first, or an empty list when unavailable."""
        if self._ctx is None:
            return []
        try:
            return self._ctx.projects.list_projects()
        except Exception:  # noqa: BLE001 - a bad manifest must not blank the page
            return []

    def _choices(self) -> list[tuple[str, str]]:
        """Dropdown entries as ``(label, project_id)``."""
        return [(f"{item.name}", item.id) for item in self._summaries()]

    def _stats(self) -> str:
        """Headline counts across every saved project."""
        summaries = self._summaries()
        clips = sum(int(getattr(item, "clip_count", 0) or 0) for item in summaries)
        transcripts = sum(1 for item in summaries if getattr(item, "has_transcript", False))
        return stat_grid(
            [
                ("Projects", len(summaries)),
                ("Clips", clips),
                ("Transcribed", transcripts),
                ("Recent", summaries[0].name if summaries else "\u2014"),
            ]
        )

    def _gallery(self) -> str:
        """Tiles for the most recent projects."""
        summaries = self._summaries()[:6]
        if not summaries:
            return card(
                empty_state(
                    "No projects yet",
                    "Create one on the left, or plan a split and save it.",
                ),
                title="Recent",
            )
        tiles = "".join(
            project_card(
                name=item.name,
                meta=f"{getattr(item, 'duration_label', '')} \u00b7 "
                f"{getattr(item, 'clip_count', 0)} clips \u00b7 "
                f"{getattr(item, 'updated_label', '')}".strip(" \u00b7"),
                thumbnail=str(getattr(item, "thumbnail", "") or ""),
            )
            for item in summaries
        )
        return card(tiles, title="Recent")

    def _listing(self) -> str:
        """Full project table."""
        summaries = self._summaries()
        if not summaries:
            return ""
        rows = [
            (
                item.name,
                getattr(item, "duration_label", "\u2014"),
                getattr(item, "clip_count", 0),
                "yes" if getattr(item, "has_transcript", False) else "no",
                getattr(item, "updated_label", "\u2014"),
                item.id,
            )
            for item in summaries
        ]
        return card(
            table(
                ["Project", "Duration", "Clips", "Transcript", "Updated", "Id"],
                rows,
                mono=(1, 5),
            ),
            title="All projects",
        )

    def _storage(self) -> str:
        """Where projects live and how much room they take."""
        if self._ctx is None:
            return ""
        report, error = safe_call(self._ctx.projects.storage_report)
        if error or report is None:
            return card(empty_state("Storage report unavailable"), title="Storage")
        return card(table(["Item", "Value"], list(report)), title="Storage")

    def _refresh(self) -> tuple[str, str, str, Any, str]:
        """Rebuild every panel that depends on the project list."""
        return (
            self._stats(),
            self._gallery(),
            self._listing(),
            gr.update(choices=self._choices()),
            self._storage(),
        )

    # ---------------------------------------------------------------- actions

    def _create(self, name: str, source: str | None) -> tuple[Any, ...]:
        """Create a project, optionally attaching a source video."""
        if self._ctx is None:
            return *self._refresh(), banner("Not ready yet.", level="error")
        cleaned = (name or "").strip()
        if not cleaned:
            return *self._refresh(), banner(
                "Give the project a name first.", level="warning", title="Name required"
            )
        media = None
        if source:
            media, error = safe_call(self._ctx.media.import_file, source)
            if error:
                return *self._refresh(), error
        project, error = safe_call(self._ctx.projects.create, cleaned, media)
        if error or project is None:
            return *self._refresh(), error
        saved, error = safe_call(self._ctx.projects.save, project)
        if error:
            return *self._refresh(), error
        return *self._refresh(), banner(
            f"Created '{project.name}' at {saved}", level="success", title="Project created"
        )

    def _detail(self, project_id: str | None) -> tuple[str, str]:
        """Show one project's manifest as a table."""
        if self._ctx is None or not project_id:
            return "", banner(
                "Choose a project first.", level="warning", title="Nothing selected"
            )
        project, error = safe_call(self._ctx.projects.load, project_id)
        if error or project is None:
            return "", error
        summary, error = safe_call(project.summary)
        rows = list(summary) if isinstance(summary, (list, tuple)) else []
        if not rows:
            rows = [
                ("Name", project.name),
                ("Id", project.id),
                ("Source", str(project.source_path)),
                ("Clips", project.clip_count),
                ("Transcript", "yes" if project.has_transcript else "no"),
            ]
        return card(table(["Property", "Value"], rows), title=project.name), ""

    def _rename(self, project_id: str | None, new_name: str) -> tuple[Any, ...]:
        """Rename a project in place."""
        if self._ctx is None or not project_id:
            return *self._refresh(), banner(
                "Choose a project first.", level="warning", title="Nothing selected"
            )
        cleaned = (new_name or "").strip()
        if not cleaned:
            return *self._refresh(), banner(
                "Type the new name first.", level="warning", title="Name required"
            )
        project, error = safe_call(self._ctx.projects.rename, project_id, cleaned)
        if error or project is None:
            return *self._refresh(), error
        return *self._refresh(), banner(
            f"Renamed to '{project.name}'.", level="success", title="Renamed"
        )

    def _duplicate(self, project_id: str | None) -> tuple[Any, ...]:
        """Copy a project, manifest and all."""
        if self._ctx is None or not project_id:
            return *self._refresh(), banner(
                "Choose a project first.", level="warning", title="Nothing selected"
            )
        project, error = safe_call(self._ctx.projects.duplicate, project_id)
        if error or project is None:
            return *self._refresh(), error
        return *self._refresh(), banner(
            f"Created '{project.name}'.", level="success", title="Duplicated"
        )

    def _delete(
        self, project_id: str | None, keep_outputs: bool, confirmed: bool
    ) -> tuple[Any, ...]:
        """Delete a project. Requires the confirmation box, deliberately."""
        if self._ctx is None or not project_id:
            return *self._refresh(), banner(
                "Choose a project first.", level="warning", title="Nothing selected"
            )
        if not confirmed:
            return *self._refresh(), banner(
                "Tick the confirmation box to delete. This cannot be undone.",
                level="warning",
                title="Confirm first",
            )
        _, error = safe_call(
            self._ctx.projects.delete, project_id, keep_outputs=bool(keep_outputs)
        )
        if error:
            return *self._refresh(), error
        note = "Rendered files were kept." if keep_outputs else "Rendered files were removed too."
        return *self._refresh(), banner(note, level="success", title="Project deleted")

    def _purge(self) -> tuple[str, str]:
        """Clear cached thumbnails, proxies and waveforms."""
        if self._ctx is None:
            return "", banner("Not ready yet.", level="error")
        result, error = safe_call(self._ctx.projects.purge_cache)
        if error:
            return self._storage(), error
        return self._storage(), banner(
            str(result or "Cache cleared."), level="success", title="Cache purged"
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus project management actions."""
        return [
            *super().commands(),
            {
                "label": "Create a project",
                "group": "Projects",
                "target": "dc-primary-projects",
                "keywords": "new add",
            },
            {
                "label": "Duplicate a project",
                "group": "Projects",
                "target": "dc-projects-duplicate",
                "keywords": "copy clone",
            },
            {
                "label": "Purge the cache",
                "group": "Projects",
                "target": "dc-projects-purge",
                "keywords": "storage clean thumbnails proxies",
            },
        ]
