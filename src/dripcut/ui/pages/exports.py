"""Exports: the job queue, live.

Everything long-running in DripCut becomes a :class:`Job`, and this is where those
jobs are watched, cancelled and reviewed. The page polls rather than streams: a
timer tick is far simpler than a websocket, and at two workers there is never
enough churn to justify anything cleverer.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dripcut.models.job import JobStatus
from dripcut.ui.components.widgets import (
    banner,
    card,
    empty_state,
    notes_list,
    rail,
    stat_grid,
    table,
)
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.timecode import format_duration

__all__ = ["ExportsPage"]

class ExportsPage(Page):
    """Watch the queue, cancel work, and collect finished files."""

    key = "exports"
    label = "Exports"
    icon = "\u2913"
    group = "Output"
    title = "Exports"
    subtitle = "Every job, its progress, and where the files landed."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the exports page."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            stats = gr.HTML(self._stats())

            with gr.Row():
                refresh = gr.Button(
                    "Refresh",
                    elem_classes=["dc-btn", "dc-btn-primary"],
                    elem_id="dc-primary-exports",
                    variant="primary",
                )
                cancel_all = gr.Button(
                    "Cancel everything", elem_classes=["dc-btn", "dc-btn-danger"],
                    elem_id="dc-exports-cancel-all",
                )
                clear = gr.Button(
                    "Clear finished", elem_classes=["dc-btn", "dc-btn-quiet"],
                    elem_id="dc-exports-clear",
                )
                live = gr.Checkbox(value=True, label="Follow progress", elem_id="dc-exports-live")

            active = gr.HTML(self._active())

            with gr.Row():
                job_id = gr.Textbox(
                    label="Cancel one job by id",
                    placeholder="paste an id from the table below",
                    elem_id="dc-exports-job-id",
                )
                cancel_one = gr.Button(
                    "Cancel that job", elem_classes=["dc-btn"], elem_id="dc-exports-cancel-one"
                )

            recent = gr.HTML(self._recent())
            outputs = gr.Files(label="Finished files", visible=False)
            collect = gr.Button(
                "Collect finished files", elem_classes=["dc-btn"], elem_id="dc-exports-collect"
            )
            activity = gr.HTML(self._activity())

            ticker = gr.Timer(2.0, active=True)

            # --------------------------------------------------------- wiring
            panels = [stats, active, recent, activity]

            refresh.click(self._snapshot, outputs=[*panels, message])
            ticker.tick(self._tick, inputs=live, outputs=panels)
            live.change(lambda on: gr.update(active=bool(on)), inputs=live, outputs=ticker)

            cancel_all.click(self._cancel_all, outputs=[*panels, message])
            cancel_one.click(self._cancel_one, inputs=job_id, outputs=[*panels, message])
            clear.click(self._clear, outputs=[*panels, message])
            collect.click(self._collect, outputs=[outputs, message])
        return column

    # ----------------------------------------------------------------- panels

    def _jobs(self, limit: int | None = None) -> list[Any]:
        """Every known job, newest first."""
        if self._ctx is None:
            return []
        return self._ctx.queue.all_jobs(limit=limit)

    def _stats(self) -> str:
        """Counts by status."""
        if self._ctx is None:
            return ""
        counts = self._ctx.queue.stats()
        return stat_grid(
            [
                ("Running", counts.get("running", 0)),
                ("Queued", counts.get("queued", 0)),
                ("Done", counts.get("succeeded", 0)),
                ("Failed", counts.get("failed", 0) + counts.get("cancelled", 0)),
            ]
        )

    def _active(self) -> str:
        """Progress rails for everything still in flight."""
        if self._ctx is None:
            return ""
        running = [job for job in self._jobs() if job.is_active]
        if not running:
            return card(
                empty_state("Nothing running", "Queue something from Workspace, Split or Batch."),
                title="In flight",
            )
        blocks = []
        for job in running:
            blocks.append(
                f'<div class="dc-project-name">{job.title}</div>'
                f'<div class="dc-project-meta"><span class="dc-mono">{job.id}</span>'
                f'<span class="dc-chip">{job.status.value}</span></div>'
                + rail(job.progress, job.stage or job.kind.value)
            )
        return card("".join(blocks), title="In flight")

    def _recent(self) -> str:
        """The full job table, newest first."""
        jobs = self._jobs(limit=40)
        if not jobs:
            return card(empty_state("No jobs yet"), title="Recent jobs")
        rows = []
        for job in jobs:
            elapsed = format_duration(job.elapsed) if job.elapsed else "\u2014"
            detail = job.error or (
                ", ".join(path.name for path in job.result.outputs)
                if job.result and job.result.outputs
                else job.stage or "\u2014"
            )
            rows.append(
                (
                    f"{job.status.icon} {job.status.value}",
                    job.kind.value,
                    job.title,
                    f"{job.percent}%",
                    elapsed,
                    detail,
                    job.id,
                )
            )
        return card(
            table(
                ["State", "Kind", "Job", "Progress", "Elapsed", "Detail", "Id"],
                rows,
                mono=(3, 4, 6),
            ),
            title="Recent jobs",
        )

    def _activity(self) -> str:
        """Notification centre entries, so failures are visible without hunting."""
        if self._ctx is None:
            return ""
        return card(notes_list(self._ctx.notifications.recent(limit=8)), title="Activity")

    def _snapshot(self) -> tuple[str, str, str, str, str]:
        """Refresh every panel and clear any message."""
        return self._stats(), self._active(), self._recent(), self._activity(), ""

    def _tick(self, following: bool) -> tuple[Any, Any, Any, Any]:
        """Timer handler. Skips work entirely when the user turned following off."""
        if not following:
            return gr.skip(), gr.skip(), gr.skip(), gr.skip()
        return self._stats(), self._active(), self._recent(), self._activity()

    # ---------------------------------------------------------------- actions

    def _cancel_all(self) -> tuple[str, str, str, str, str]:
        """Cancel every queued and running job."""
        if self._ctx is None:
            return *self._snapshot()[:4], banner("Not ready yet.", level="error")
        count, error = safe_call(self._ctx.queue.cancel_all)
        panels = self._snapshot()[:4]
        if error:
            return *panels, error
        level = "success" if count else "info"
        return *panels, banner(
            f"Cancelled {count} job(s)." if count else "There was nothing to cancel.",
            level=level,
            title="Cancel",
        )

    def _cancel_one(self, job_id: str) -> tuple[str, str, str, str, str]:
        """Cancel a single job by its id."""
        panels = self._snapshot()[:4]
        if self._ctx is None:
            return *panels, banner("Not ready yet.", level="error")
        wanted = (job_id or "").strip()
        if not wanted:
            return *panels, banner(
                "Paste a job id from the table.", level="warning", title="No id given"
            )
        ok, error = safe_call(self._ctx.queue.cancel, wanted)
        panels = self._snapshot()[:4]
        if error:
            return *panels, error
        if ok:
            return *panels, banner(f"Cancelled {wanted}.", level="success", title="Cancel")
        return *panels, banner(
            f"No running job with id {wanted}.",
            level="warning",
            title="Nothing to cancel",
        )

    def _clear(self) -> tuple[str, str, str, str, str]:
        """Drop finished jobs from the table, keeping the queue readable."""
        panels = self._snapshot()[:4]
        if self._ctx is None:
            return *panels, banner("Not ready yet.", level="error")
        count, error = safe_call(self._ctx.queue.clear_finished)
        panels = self._snapshot()[:4]
        if error:
            return *panels, error
        return *panels, banner(
            f"Cleared {count} finished job(s).", level="info", title="Tidy up"
        )

    def _collect(self) -> tuple[Any, str]:
        """Gather every output path from successful jobs into a download list."""
        if self._ctx is None:
            return gr.update(visible=False), banner("Not ready yet.", level="error")
        paths: list[str] = []
        for job in self._jobs():
            if job.status is JobStatus.SUCCEEDED and job.result:
                paths.extend(str(path) for path in job.result.outputs if path.exists())
        if not paths:
            return gr.update(visible=False), banner(
                "No finished files yet.", level="info", title="Nothing to collect"
            )
        return gr.update(value=paths, visible=True), banner(
            f"Collected {len(paths)} file(s).", level="success", title="Ready"
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the queue controls."""
        return [
            *super().commands(),
            {
                "label": "Refresh the queue",
                "group": "Exports",
                "target": "dc-primary-exports",
                "keywords": "jobs reload",
            },
            {
                "label": "Cancel every job",
                "group": "Exports",
                "target": "dc-exports-cancel-all",
                "keywords": "stop abort",
            },
            {
                "label": "Clear finished jobs",
                "group": "Exports",
                "target": "dc-exports-clear",
                "keywords": "tidy remove",
            },
            {
                "label": "Collect finished files",
                "group": "Exports",
                "target": "dc-exports-collect",
                "keywords": "download outputs",
            },
        ]
