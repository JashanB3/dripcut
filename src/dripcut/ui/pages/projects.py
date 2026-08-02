"""Projects: durable state.

A project is a manifest on disk holding a source, a plan, a caption style and the
files produced from them. This page is the front end to
:class:`~dripcut.services.project_service.ProjectService` and nothing else -- no
project logic lives here, only the forms that drive it.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.ui.components.widgets import (
    banner,
    card,
    empty_state,
    stat_grid,
    table,
)
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.fs import ensure_dir, human_size

__all__ = ["ProjectsPage"]


class ProjectsPage(Page):
    """Manage saved projects and the space they occupy."""

    key = "projects"
    label = "Projects"
    icon = "\u25eb"
    group = "Library"
    title = "Projects"
    subtitle = "Every video you have brought in, and everything DripCut made from it."

    #: Project tiles rendered in the library grid.
    LIBRARY_LIMIT = 12

    #: Download rows in the open project. Gradio needs a fixed number of
    #: components, so the page builds a pool and shows as many as it needs.
    FILE_SLOTS = 8

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the projects library and the open-project view."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            stats = gr.HTML(self._stats())
            selected = gr.State("")

            with gr.Row(elem_classes=["dc-library-head"]):
                gr.HTML(
                    '<div class="dc-section-title">Your library</div>'
                    '<p class="dc-section-note">Open a project to get its clips '
                    "and download them.</p>"
                )
                chooser = gr.Dropdown(
                    choices=self._choices(),
                    label="Jump to project",
                    elem_id="dc-projects-chooser",
                    interactive=True,
                )

            library = gr.HTML(self._library())

            # One trigger per tile. They live off-screen rather than behind
            # `visible=False` so the tile's click handler can always reach them.
            openers: list[gr.Button] = [
                gr.Button(
                    f"open-{index}",
                    elem_id=f"dc-project-open-{index}",
                    elem_classes=["dc-hidden-trigger"],
                )
                for index in range(self.LIBRARY_LIMIT)
            ]

            with gr.Column(elem_classes=["dc-project-view"], visible=False) as view:
                with gr.Row(elem_classes=["dc-project-columns"]):
                    detail = gr.HTML()
                    with gr.Column(
                        scale=0, min_width=320, elem_classes=["dc-file-panel"]
                    ):
                        files_head = gr.HTML()
                        file_slots = [
                            gr.DownloadButton(
                                "File",
                                visible=False,
                                elem_classes=["dc-file-row"],
                            )
                            for _ in range(self.FILE_SLOTS)
                        ]
                        zip_button = gr.Button(
                            "Zip every clip",
                            variant="primary",
                            elem_classes=["dc-btn", "dc-btn-primary"],
                            elem_id="dc-projects-zip",
                        )
                        zip_download = gr.DownloadButton(
                            "Download ZIP", visible=False, interactive=True
                        )

                with gr.Accordion("Manage this project", open=False):
                    rename_to = gr.Textbox(
                        label="New name", placeholder="Renamed project"
                    )
                    with gr.Row():
                        rename_button = gr.Button(
                            "Rename", elem_classes=["dc-btn"], elem_id="dc-projects-rename"
                        )
                        duplicate_button = gr.Button(
                            "Duplicate",
                            elem_classes=["dc-btn"],
                            elem_id="dc-projects-duplicate",
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
                            "Delete",
                            elem_classes=["dc-btn", "dc-btn-danger"],
                            elem_id="dc-projects-delete",
                        )

            with gr.Accordion("Start a new project", open=False):
                new_name = gr.Textbox(
                    label="Project name",
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

            with gr.Accordion("Storage", open=False):
                storage = gr.HTML(self._storage())
                purge = gr.Button(
                    "Purge cached thumbnails and proxies",
                    elem_classes=["dc-btn"],
                    elem_id="dc-projects-purge",
                )

            panels = [stats, library, chooser, storage]
            open_outputs = [
                view,
                detail,
                files_head,
                *file_slots,
                zip_download,
                selected,
                chooser,
            ]

            for index, opener in enumerate(openers):
                opener.click(
                    lambda position=index: self._open_index(position),
                    outputs=open_outputs,
                    show_progress="hidden",
                )
            # The chooser must not write back to itself: a change handler that
            # returns a new value for its own input can bounce.
            chooser.change(
                self._open_from_chooser, inputs=chooser, outputs=open_outputs
            )
            zip_button.click(
                self._zip_all, inputs=selected, outputs=[zip_download, message]
            )

            create.click(
                self._create, inputs=[new_name, new_source], outputs=[*panels, message]
            )
            rename_button.click(
                self._rename, inputs=[selected, rename_to], outputs=[*panels, message]
            )
            duplicate_button.click(
                self._duplicate, inputs=selected, outputs=[*panels, message]
            )
            delete_button.click(
                self._delete,
                inputs=[selected, keep_outputs, confirm],
                outputs=[*panels, message],
            )
            purge.click(self._purge, outputs=[storage, message])
        return column

    # ------------------------------------------------------------- open a project

    def _outputs_for(self, project: Any) -> list[Path]:
        """Every rendered file belonging to a project, newest first.

        Reads both the manifest's ``outputs`` list and the project's clips
        folder, because a render that crashed before the manifest was written
        still leaves usable files on disk.
        """
        found: dict[str, Path] = {}
        for path in getattr(project, "outputs", []) or []:
            candidate = Path(str(path))
            if candidate.exists() and candidate.is_file():
                found[str(candidate.resolve())] = candidate
        if self._ctx is not None:
            clips, _ = safe_call(self._ctx.projects.clips_dir, project)
            if clips is not None and Path(clips).exists():
                for candidate in sorted(Path(clips).iterdir()):
                    if candidate.is_file():
                        found.setdefault(str(candidate.resolve()), candidate)
        return sorted(found.values(), key=lambda item: item.stat().st_mtime, reverse=True)

    def _open_index(self, position: int) -> tuple[Any, ...]:
        """Open the project shown in tile ``position``."""
        summaries = self._summaries()[: self.LIBRARY_LIMIT]
        if position >= len(summaries):
            return self._closed_view()
        return self._open_project(summaries[position].id)

    def _closed_view(self) -> tuple[Any, ...]:
        """Every output the open view owns, back to its resting state."""
        return (
            gr.update(visible=False),
            "",
            "",
            *[gr.update(visible=False) for _ in range(self.FILE_SLOTS)],
            gr.update(visible=False),
            "",
            gr.update(),
        )

    def _open_from_chooser(self, project_id: str | None) -> tuple[Any, ...]:
        """Open a project picked from the dropdown, leaving the dropdown alone."""
        return (*self._open_project(project_id)[:-1], gr.update())

    def _open_project(self, project_id: str | None) -> tuple[Any, ...]:
        """Show one project: what it is, and every file it produced."""
        if self._ctx is None or not project_id:
            return self._closed_view()
        project, error = safe_call(self._ctx.projects.load, project_id)
        if error or project is None:
            return self._closed_view()

        files = self._outputs_for(project)
        shown = files[: self.FILE_SLOTS]
        slots: list[Any] = []
        for index in range(self.FILE_SLOTS):
            if index < len(shown):
                path = shown[index]
                label = path.name
                if len(label) > 34:
                    label = f"{label[:20]}\u2026{label[-12:]}"
                slots.append(
                    gr.update(
                        visible=True,
                        value=str(path),
                        label=f"{label}  \u00b7  {human_size(path.stat().st_size)}",
                    )
                )
            else:
                slots.append(gr.update(visible=False))

        if not files:
            head = (
                '<div class="dc-files-head"><div class="dc-section-title">Files</div>'
                '<p class="dc-section-note">Nothing rendered from this project yet. '
                "Open Make Clips with it and the results land here.</p></div>"
            )
        else:
            extra = (
                f" \u00b7 {len(files) - len(shown)} more in the folder"
                if len(files) > len(shown)
                else ""
            )
            total = human_size(sum(item.stat().st_size for item in files))
            head = (
                '<div class="dc-files-head"><div class="dc-section-title">Files</div>'
                f'<p class="dc-section-note">{len(files)} rendered \u00b7 {total}{extra}'
                "</p></div>"
            )
        return (
            gr.update(visible=True),
            self._project_detail(project, files),
            head,
            *slots,
            gr.update(visible=False),
            project.id,
            gr.update(value=project.id),
        )

    def _project_detail(self, project: Any, files: list[Path]) -> str:
        """The open project's header card."""
        thumb = str(getattr(project, "thumbnail", "") or "")
        rows = [
            ("Source", getattr(project, "source_name", "\u2014") or "\u2014"),
            ("Duration", getattr(project, "duration_label", "\u2014")),
            ("Clips rendered", len(files)),
            ("Transcript", "yes" if getattr(project, "has_transcript", False) else "no"),
            ("Project id", project.id),
        ]
        header = (
            '<div class="dc-project-hero">'
            '<div class="dc-project-hero-thumb"'
            + (f' style="background-image:url({thumb})"' if thumb else "")
            + "></div>"
            f'<div><div class="dc-eyebrow">Open project</div>'
            f'<div class="dc-project-hero-name">{project.name}</div></div></div>'
        )
        return card(header + table(["Detail", "Value"], rows))

    def _zip_all(self, project_id: str | None) -> tuple[Any, str]:
        """Bundle every rendered file into one archive and offer it."""
        if self._ctx is None or not project_id:
            return gr.update(visible=False), banner(
                "Open a project first.", level="warning", title="Nothing selected"
            )
        project, error = safe_call(self._ctx.projects.load, project_id)
        if error or project is None:
            return gr.update(visible=False), error or ""
        files = self._outputs_for(project)
        if not files:
            return gr.update(visible=False), banner(
                "This project has no rendered files yet.",
                level="warning",
                title="Nothing to zip",
            )
        target = ensure_dir(self._ctx.paths.temp) / f"{project.slug or project.id}-clips.zip"
        try:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as handle:
                for path in files:
                    handle.write(path, arcname=path.name)
        except OSError as problem:
            return gr.update(visible=False), banner(
                str(problem), level="error", title="Could not write the archive"
            )
        return (
            gr.update(
                visible=True,
                value=str(target),
                label=f"Download ZIP \u00b7 {human_size(target.stat().st_size)}",
            ),
            banner(
                f"{len(files)} files bundled.", level="success", title="Archive ready"
            ),
        )

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

    def _library(self) -> str:
        """The project grid. Each tile opens its own project."""
        summaries = self._summaries()[: self.LIBRARY_LIMIT]
        if not summaries:
            return empty_state(
                "No projects yet",
                "Make a set of clips, or start a project below and attach a video.",
            )
        tiles = []
        for index, item in enumerate(summaries):
            thumb = str(getattr(item, "thumbnail", "") or "")
            style = f' style="background-image:url({thumb})"' if thumb else ""
            clips = int(getattr(item, "clip_count", 0) or 0)
            handler = (
                f"var b=document.getElementById('dc-project-open-{index}');"
                "if(b){b.click();}"
            )
            tiles.append(
                f'<button type="button" class="dc-lib-card" onclick="{handler}">'
                f'<span class="dc-lib-thumb"{style}></span>'
                f'<span class="dc-lib-body">'
                f'<span class="dc-lib-name">{item.name}</span>'
                f'<span class="dc-lib-meta">{getattr(item, "duration_label", "")} '
                f'\u00b7 {clips} clip{"" if clips == 1 else "s"} '
                f'\u00b7 {getattr(item, "updated_label", "")}</span>'
                "</span></button>"
            )
        return f'<div class="dc-lib-grid">{"".join(tiles)}</div>'

    def _storage(self) -> str:
        """Where projects live and how much room they take."""
        if self._ctx is None:
            return ""
        report, error = safe_call(self._ctx.projects.storage_report)
        if error or report is None:
            return card(empty_state("Storage report unavailable"), title="Storage")
        return card(table(["Item", "Value"], list(report)), title="Storage")

    def _refresh(self) -> tuple[str, str, Any, str]:
        """Rebuild every panel that depends on the project list."""
        return (
            self._stats(),
            self._library(),
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
                "label": "Zip a project's clips",
                "group": "Projects",
                "target": "dc-projects-zip",
                "keywords": "download archive bundle",
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
