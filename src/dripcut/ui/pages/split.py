"""Split: turn one long recording into clips, in any of the six modes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.engines.video.encode import Quality
from dripcut.models.clip import SplitMode
from dripcut.ui.components.widgets import (
    banner,
    card,
    table,
    timeline_strip,
)
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.timecode import format_duration

__all__ = ["SplitPage"]

_MODE_HELP: dict[str, str] = {
    "fixed": "Even clips of a length you choose. Predictable, and the fastest to plan.",
    "scene": "Cuts where the picture changes. Good for edited footage and screen recordings.",
    "silence": "Cuts in the pauses. Good for talking-head video and podcasts.",
    "timestamps": "Cuts exactly where you say. Paste times or ranges below.",
    "chapters": "Uses chapter markers already embedded in the file.",
    "ai_highlight": "Transcribes, then asks the local model for the strongest moments.",
}


class SplitPage(Page):
    """Plan a split, inspect it, then render it."""

    key = "split"
    label = "Split"
    icon = "\u2702"
    group = "Workspace"
    title = "Split"
    subtitle = "Plan first, look at what you got, then render."

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the split workspace."""
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            plan_state = gr.State(None)
            media_state = gr.State(None)

            with gr.Row():
                # ------------------------------------------------ left: inputs
                with gr.Column(scale=2):
                    source = gr.File(
                        label="Video",
                        type="filepath",
                        elem_classes=["dc-dropzone"],
                        elem_id="dc-split-source",
                    )
                    media_info = gr.HTML()

                    mode = gr.Dropdown(
                        choices=[(item.label, item.value) for item in SplitMode],
                        value=SplitMode.FIXED.value,
                        label="Mode",
                        elem_id="dc-split-mode",
                    )
                    mode_help = gr.HTML(self._mode_help(SplitMode.FIXED.value))

                    with gr.Group():
                        clip_length = gr.Slider(
                            5, 300, value=30, step=5, label="Clip length (seconds)"
                        )
                        overlap = gr.Slider(0, 10, value=0, step=0.5, label="Overlap (seconds)")
                        threshold = gr.Slider(
                            -60, 60, value=27, step=1,
                            label="Sensitivity (scene score, or dB for silence)",
                        )
                        timestamps = gr.Textbox(
                            label="Cut points or ranges",
                            placeholder="0:30, 1:15, 2:40   or   0:10-0:25, 1:00-1:30",
                        )
                        max_clips = gr.Slider(1, 40, value=8, step=1, label="Maximum clips")
                        focus = gr.Dropdown(
                            choices=["auto", "hooks", "funny", "educational", "story", "quotes"],
                            value="auto",
                            label="What the AI should look for",
                        )

                    plan_button = gr.Button(
                        "Plan the split",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-primary-split",
                    )

                # ----------------------------------------------- right: result
                with gr.Column(scale=3):
                    message = gr.HTML()
                    summary = gr.HTML()
                    strip = gr.HTML(timeline_strip([]))
                    clip_table = gr.HTML()

                    with gr.Row():
                        container_choice = gr.Dropdown(
                            choices=["mp4", "mov", "mkv", "webm"], value="mp4", label="Format"
                        )
                        quality = gr.Dropdown(
                            choices=[q.value for q in Quality],
                            value=Quality.BALANCED.value,
                            label="Quality",
                        )
                        accurate = gr.Checkbox(
                            value=True, label="Frame-accurate (slower, re-encodes)"
                        )
                    destination = gr.Textbox(
                        label="Output folder",
                        value=str(ctx.output_dir),
                        placeholder=str(ctx.output_dir),
                    )
                    render_button = gr.Button(
                        "Render clips",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-split-render",
                    )
                    outputs = gr.Files(label="Rendered clips", visible=False)

            # ------------------------------------------------------- behaviour
            mode.change(self._mode_help, inputs=mode, outputs=mode_help)

            source.change(
                lambda path: self._load(ctx, path),
                inputs=source,
                outputs=[media_state, media_info, message],
            )

            plan_button.click(
                lambda media, chosen, length, over, thresh, stamps, limit, want: self._plan(
                    ctx, media, chosen, length, over, thresh, stamps, limit, want
                ),
                inputs=[media_state, mode, clip_length, overlap, threshold, timestamps, max_clips, focus],
                outputs=[plan_state, summary, strip, clip_table, message],
            )

            render_button.click(
                lambda plan, media, fmt, qual, exact, folder: self._render(
                    ctx, plan, media, fmt, qual, exact, folder
                ),
                inputs=[plan_state, media_state, container_choice, quality, accurate, destination],
                outputs=[outputs, message],
            )
        return column

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _mode_help(mode: str) -> str:
        """One line explaining the selected mode."""
        return f'<div class="dc-note-detail">{_MODE_HELP.get(str(mode), "")}</div>'

    @staticmethod
    def _load(ctx: PageContext, path: str | None) -> tuple[Any, str, str]:
        """Probe the dropped file and show its properties."""
        if not path:
            return None, "", ""
        media, error = safe_call(ctx.media.import_file, path)
        if error:
            return None, "", error
        rows = media.summary_rows()
        return media, card(table(["Property", "Value"], rows), title=media.name), ""

    @staticmethod
    def _plan(
        ctx: PageContext,
        media: Any,
        mode: str,
        clip_length: float,
        overlap: float,
        threshold: float,
        timestamps: str,
        max_clips: float,
        focus: str,
        progress: gr.Progress | None = None,
    ) -> tuple[Any, str, str, str, str]:
        """Build a split plan and render its preview."""
        if media is None:
            return None, "", timeline_strip([]), "", banner(
                "Add a video first.", level="warning", title="Nothing to split"
            )

        resolved = SplitMode(str(mode))
        parameters: dict[str, Any] = {
            "clip_length": float(clip_length),
            "overlap": float(overlap),
            "max_clips": int(max_clips),
            "focus": str(focus),
        }
        if resolved is SplitMode.SCENE:
            parameters["threshold"] = float(threshold)
        elif resolved is SplitMode.SILENCE:
            parameters["threshold_db"] = float(threshold)
        if timestamps.strip():
            key = "ranges" if "-" in timestamps else "timestamps"
            parameters[key] = timestamps.strip()

        def report(fraction: float, stage: str) -> None:
            """Forward engine progress to the Gradio progress bar."""
            if progress is not None:
                progress(min(max(fraction, 0.0), 1.0), desc=stage)

        plan, error = safe_call(ctx.split.plan, media, resolved, parameters, on_progress=report)
        if error or plan is None:
            return None, "", timeline_strip([]), "", error

        segments = [
            {
                "index": segment.index,
                "label": f"{segment.index:02d}",
                "range": segment.timecode_range,
                "duration": segment.duration,
                "ai": segment.score is not None,
            }
            for segment in plan.segments
        ]
        rows = [
            (
                segment.index,
                segment.timecode_range,
                format_duration(segment.duration),
                segment.display_title(media.stem),
                f"{segment.score:.0%}" if segment.score is not None else "\u2014",
            )
            for segment in plan.segments
        ]
        summary = card(
            f'<div class="dc-display">{plan.count} clips</div>'
            f'<div class="dc-sub">total {format_duration(plan.total_duration)} \u00b7 '
            f"average {format_duration(plan.average_duration)}</div>",
            eyebrow=resolved.label,
        )
        return (
            plan,
            summary,
            timeline_strip(segments, total=media.duration),
            card(table(["#", "Range", "Length", "Title", "Score"], rows, mono=(1, 2)), title="Clips"),
            "",
        )

    @staticmethod
    def _render(
        ctx: PageContext,
        plan: Any,
        media: Any,
        container: str,
        quality: str,
        accurate: bool,
        folder: str,
        progress: gr.Progress | None = None,
    ) -> tuple[Any, str]:
        """Render every segment in the current plan."""
        if plan is None:
            return gr.update(visible=False), banner(
                "Plan a split before rendering.", level="warning", title="No plan yet"
            )

        def report(fraction: float, stage: str) -> None:
            """Forward per-clip progress to the Gradio progress bar."""
            if progress is not None:
                progress(min(max(fraction, 0.0), 1.0), desc=stage)

        target = Path(folder).expanduser() if folder.strip() else ctx.output_dir
        paths, error = safe_call(
            ctx.split.render,
            plan,
            target / media.stem,
            container=str(container),
            quality=Quality(str(quality)),
            accurate=bool(accurate),
            on_progress=report,
        )
        if error or not paths:
            return gr.update(visible=False), error or banner(
                "Nothing was written.", level="warning", title="Empty render"
            )
        return gr.update(value=[str(path) for path in paths], visible=True), banner(
            f"Wrote {len(paths)} clips to {target / media.stem}",
            level="success",
            title="Render finished",
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the page's two primary actions."""
        return [
            *super().commands(),
            {
                "label": "Plan the split",
                "group": "Split",
                "target": "dc-primary-split",
                "keywords": "plan clips segments",
            },
            {
                "label": "Render clips",
                "group": "Split",
                "target": "dc-split-render",
                "keywords": "render export write clips",
            },
        ]

