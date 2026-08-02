"""Batch: the same operation across many files.

The service submits one job for the whole batch rather than one per file, so the
queue shows honest overall progress instead of a dozen rows racing each other.
This page's job is to build a clean file list and a valid options dictionary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.ui.components.widgets import banner, card, empty_state, stat_grid, table
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.fs import human_size
from dripcut.utils.timecode import format_duration

__all__ = ["BatchPage"]

# Operations the export service exposes for batches, with what each one needs.
_OPERATIONS: list[tuple[str, str, str]] = [
    ("resize", "Resize", "Scale every file to the same frame size."),
    ("audio", "Extract audio", "Pull the audio track out of every file."),
    ("gif", "Make GIFs", "Turn the opening seconds of each file into a GIF."),
    ("thumbnail", "Thumbnails", "Grab one representative still from each file."),
]


class BatchPage(Page):
    """Import a folder, pick one operation, queue it."""

    key = "batch"
    label = "Bulk Edit"
    icon = "\u2637"
    group = "Create"
    title = "Bulk Edit"
    subtitle = "Drop a folder, pick one action, and let DripCut handle the boring part."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the batch page."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            media_state = gr.State([])
            message = gr.HTML()

            with gr.Row():
                with gr.Column(scale=2):
                    folder = gr.Textbox(
                        label="Folder to import",
                        placeholder=str(Path.home() / "Movies"),
                        elem_id="dc-batch-folder",
                    )
                    recursive = gr.Checkbox(value=False, label="Include subfolders")
                    scan = gr.Button(
                        "Scan folder",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        variant="primary",
                        elem_id="dc-batch-scan",
                    )
                    picked = gr.File(
                        label="Or pick files directly",
                        type="filepath",
                        file_count="multiple",
                        elem_classes=["dc-dropzone"],
                    )
                    add_picked = gr.Button(
                        "Add those files", elem_classes=["dc-btn"], elem_id="dc-batch-add"
                    )
                    clear = gr.Button(
                        "Clear the list", elem_classes=["dc-btn", "dc-btn-quiet"],
                        elem_id="dc-batch-clear",
                    )
                with gr.Column(scale=3):
                    stats = gr.HTML(self._stats([]))
                    listing = gr.HTML(self._listing([]))

            operation = gr.Radio(
                choices=[(label, key) for key, label, _ in _OPERATIONS],
                value=_OPERATIONS[0][0],
                label="Operation",
                elem_id="dc-batch-operation",
            )
            operation_help = gr.HTML(self._operation_help(_OPERATIONS[0][0]))

            with gr.Row():
                width = gr.Number(value=1080, label="Width (resize, GIF, thumbnail)", minimum=0)
                height = gr.Number(value=1920, label="Height (resize only)", minimum=0)
                scale_mode = gr.Dropdown(
                    ["fit", "fill", "stretch", "exact"], value="fit", label="Scale mode"
                )
            with gr.Row():
                audio_format = gr.Dropdown(
                    ["m4a", "mp3", "wav", "flac"], value="m4a", label="Audio format"
                )
                gif_seconds = gr.Slider(
                    1, 20, value=6, step=1, label="GIF length from the start (s)"
                )
            destination = gr.Textbox(
                label="Output folder",
                value=str(ctx.output_dir),
                placeholder=str(ctx.output_dir),
            )

            run = gr.Button(
                "Queue the batch",
                variant="primary",
                elem_classes=["dc-btn", "dc-btn-primary"],
                elem_id="dc-primary-batch",
            )
            queued = gr.HTML()

            # --------------------------------------------------------- wiring
            operation.change(self._operation_help, inputs=operation, outputs=operation_help)
            scan.click(
                self._scan, inputs=[folder, recursive], outputs=[media_state, stats, listing, message]
            )
            add_picked.click(
                self._add, inputs=[media_state, picked], outputs=[media_state, stats, listing, message]
            )
            clear.click(
                lambda: ([], self._stats([]), self._listing([]), ""),
                outputs=[media_state, stats, listing, message],
            )
            run.click(
                self._run,
                inputs=[
                    media_state, operation, width, height, scale_mode,
                    audio_format, gif_seconds, destination,
                ],
                outputs=[queued, message],
            )
        return column

    # ----------------------------------------------------------------- panels

    @staticmethod
    def _operation_help(operation: str) -> str:
        """One line describing the selected operation."""
        for key, _, description in _OPERATIONS:
            if key == operation:
                return f'<div class="dc-note-detail">{description}</div>'
        return ""

    @staticmethod
    def _stats(items: list[Any]) -> str:
        """Totals across the current file list."""
        if not items:
            return stat_grid([("Files", 0), ("Duration", "\u2014"), ("Size", "\u2014"), ("With audio", 0)])
        total_duration = sum(float(item.duration or 0) for item in items)
        total_size = sum(int(item.size_bytes or 0) for item in items)
        with_audio = sum(1 for item in items if item.has_audio)
        return stat_grid(
            [
                ("Files", len(items)),
                ("Duration", format_duration(total_duration)),
                ("Size", human_size(total_size)),
                ("With audio", with_audio),
            ]
        )

    @staticmethod
    def _listing(items: list[Any]) -> str:
        """The batch file table."""
        if not items:
            return card(
                empty_state(
                    "No files yet",
                    "Scan a folder on the left, or drop files in directly.",
                ),
                title="Batch",
            )
        rows = [
            (
                index,
                item.name,
                item.timecode_label,
                item.size_label,
                item.video.display_resolution[0] if item.video else "\u2014",
                "yes" if item.has_audio else "no",
            )
            for index, item in enumerate(items, start=1)
        ]
        return card(
            table(["#", "File", "Duration", "Size", "Width", "Audio"], rows, mono=(2, 3)),
            title=f"Batch \u00b7 {len(items)} file(s)",
        )

    def _refresh(self, items: list[Any]) -> tuple[list[Any], str, str]:
        """State plus both panels, for handlers that change the list."""
        return items, self._stats(items), self._listing(items)

    # ---------------------------------------------------------------- actions

    def _scan(self, folder: str, recursive: bool) -> tuple[list[Any], str, str, str]:
        """Import every media file in a folder."""
        if self._ctx is None:
            return *self._refresh([]), banner("Not ready yet.", level="error")
        cleaned = (folder or "").strip()
        if not cleaned:
            return *self._refresh([]), banner(
                "Type a folder path first.", level="warning", title="No folder"
            )
        target = Path(cleaned).expanduser()
        if not target.is_dir():
            return *self._refresh([]), banner(
                f"{target} is not a folder.",
                level="warning",
                title="Cannot scan",
            )
        items, error = safe_call(
            self._ctx.media.import_folder, target, recursive=bool(recursive), fallback=[]
        )
        if error:
            return *self._refresh([]), error
        found = list(items or [])
        return *self._refresh(found), banner(
            f"Imported {len(found)} file(s).", level="success", title="Scanned"
        )

    def _add(
        self, existing: list[Any], picked: list[str] | None
    ) -> tuple[list[Any], str, str, str]:
        """Append individually chosen files to the list, skipping duplicates."""
        if self._ctx is None:
            return *self._refresh(existing or []), banner("Not ready yet.", level="error")
        chosen = picked or []
        if not chosen:
            return *self._refresh(existing or []), banner(
                "Pick some files first.", level="warning", title="Nothing chosen"
            )
        items = list(existing or [])
        seen = {str(item.path) for item in items}
        added = 0
        problems: list[str] = []
        for path in chosen:
            if str(Path(path)) in seen:
                continue
            media, error = safe_call(self._ctx.media.import_file, path)
            if error or media is None:
                problems.append(Path(path).name)
                continue
            items.append(media)
            seen.add(str(media.path))
            added += 1
        note = banner(
            f"Added {added} file(s)." + (f" Skipped: {', '.join(problems)}." if problems else ""),
            level="success" if added else "warning",
            title="Batch updated",
        )
        return *self._refresh(items), note

    def _run(
        self,
        items: list[Any],
        operation: str,
        width: float,
        height: float,
        scale_mode: str,
        audio_format: str,
        gif_seconds: float,
        destination: str,
    ) -> tuple[str, str]:
        """Queue one job covering every file in the list."""
        if self._ctx is None:
            return "", banner("Not ready yet.", level="error")
        sources = list(items or [])
        if not sources:
            return "", banner(
                "Add some files to the batch first.", level="warning", title="Empty batch"
            )

        options: dict[str, Any] = {
            "width": int(width) or None,
            "scale_mode": str(scale_mode),
            "audio_format": str(audio_format),
            "gif_seconds": float(gif_seconds),
        }
        if str(operation) == "resize":
            if not int(width) and not int(height):
                return "", banner(
                    "Give the resize a width or a height.",
                    level="warning",
                    title="No target size",
                )
            options["height"] = int(height) or None

        folder = (destination or "").strip() or None
        job, error = safe_call(
            self._ctx.export.queue_batch, sources, str(operation), folder=folder, **options
        )
        if error or job is None:
            return "", error
        return card(
            table(
                ["Job", "Value"],
                [
                    ("Title", job.title),
                    ("Files", len(sources)),
                    ("Operation", str(operation)),
                    ("Status", job.status.value),
                    ("Id", job.id),
                ],
            ),
            title="Batch queued",
            eyebrow="Watch it on the Exports page",
        ), banner(
            f"Queued {len(sources)} file(s) for {operation}.",
            level="success",
            title="Batch started",
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the batch actions."""
        return [
            *super().commands(),
            {
                "label": "Scan a folder for the batch",
                "group": "Batch",
                "target": "dc-batch-scan",
                "keywords": "import folder files",
            },
            {
                "label": "Queue the batch",
                "group": "Batch",
                "target": "dc-primary-batch",
                "keywords": "run start process",
            },
            {
                "label": "Clear the batch list",
                "group": "Batch",
                "target": "dc-batch-clear",
                "keywords": "empty reset",
            },
        ]
