"""Split: turn one long recording into clips, in any of the six modes."""

from __future__ import annotations

import json
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.core.config import save_settings
from dripcut.engines.video.encode import Quality
from dripcut.models.clip import SplitMode
from dripcut.ui.components.widgets import (
    banner,
    card,
    table,
    timeline_strip,
)
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.fs import ensure_dir, human_size, safe_filename
from dripcut.utils.timecode import format_duration

__all__ = ["SplitPage"]

_MODE_HELP: dict[str, str] = {
    "fixed": "Quick, even clips. Best when you already know the length you want.",
    "scene": "Find visual changes automatically. Great for edited videos.",
    "silence": "Cut around pauses. Nice for podcasts and talking-head clips.",
    "timestamps": "Use your exact moments. Paste times or ranges below.",
    "chapters": "Use chapter markers already inside the video.",
    "ai_highlight": "Let AI pick the best moments for hooks, stories, and quotes.",
}


class SplitPage(Page):
    """Plan a split, inspect it, then render it."""

    key = "split"
    label = "Make Clips"
    icon = "\u2702"
    group = "Create"
    title = "Make Clips"
    subtitle = "Drop a video, choose the vibe, and download a ready-to-post ZIP."

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the split workspace."""
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            plan_state = gr.State(None)
            media_state = gr.State(None)

            with gr.Row(elem_classes=["dc-workspace-grid"], equal_height=False):
                # ------------------------------------------------ left: inputs
                with gr.Column(scale=2, elem_classes=["dc-workspace-inputs"]):
                    with gr.Tabs(elem_classes=["dc-source-tabs"]):
                        with gr.Tab("Upload video"):
                            source = gr.File(
                                label="Video",
                                type="filepath",
                                elem_classes=["dc-dropzone"],
                                elem_id="dc-split-source",
                            )
                        with gr.Tab("YouTube link"):
                            youtube_url = gr.Textbox(
                                label="YouTube video link",
                                placeholder="https://www.youtube.com/watch?v=...",
                                lines=1,
                                elem_id="dc-split-youtube-url",
                            )
                            youtube_rights = gr.Checkbox(
                                value=False,
                                label="I have permission to download and edit this video",
                            )
                            youtube_import = gr.Button(
                                "Use this YouTube video",
                                elem_classes=["dc-btn", "dc-btn-secondary"],
                                elem_id="dc-split-youtube-import",
                            )

                    mode = gr.Dropdown(
                        choices=[(item.label, item.value) for item in SplitMode],
                        value=SplitMode.FIXED.value,
                        label="How should we cut it?",
                        elem_id="dc-split-mode",
                    )
                    mode_help = gr.HTML(self._mode_help(SplitMode.FIXED.value))

                    with gr.Group():
                        clip_length = gr.Slider(
                            5, 300, value=30, step=5, label="Clip length"
                        )
                        overlap = gr.Slider(0, 10, value=0, step=0.5, label="Overlap")
                        threshold = gr.Slider(
                            -60, 60, value=27, step=1,
                            label="Sensitivity",
                        )
                        timestamps = gr.Textbox(
                            label="Exact moments",
                            placeholder="0:30, 1:15, 2:40   or   0:10-0:25, 1:00-1:30",
                        )
                        max_clips = gr.Slider(1, 40, value=8, step=1, label="Maximum clips")
                        focus = gr.Dropdown(
                            choices=["auto", "hooks", "funny", "educational", "story", "quotes"],
                            value="auto",
                            label="What the AI should look for",
                        )

                    plan_button = gr.Button(
                        "Plan my clips",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-primary-split",
                    )

                # ----------------------------------------------- right: result
                with gr.Column(scale=3, elem_classes=["dc-workspace-results"]):
                    message = gr.HTML()
                    summary = gr.HTML()
                    strip = gr.HTML(timeline_strip([]))
                    clip_table = gr.HTML()

                    with gr.Row():
                        container_choice = gr.Dropdown(
                            choices=["mp4", "mov", "mkv", "webm"], value="mp4", label="Container"
                        )
                        quality = gr.Dropdown(
                            choices=[q.value for q in Quality],
                            value=Quality.BALANCED.value,
                            label="Quality",
                        )
                        accurate = gr.Checkbox(
                            value=False, label="Precise cuts"
                        )
                    with gr.Row():
                        output_format = gr.Dropdown(
                            [("Landscape", "landscape"), ("Portrait", "portrait"), ("Square", "square")],
                            value=ctx.settings.ui.split_output_format,
                            label="Output format",
                        )
                        portrait_mode = gr.Dropdown(
                            [
                                ("AI Tracking", "ai_tracking"),
                                ("Center Crop", "center_crop"),
                                ("Blur Background", "blur_background"),
                            ],
                            value=ctx.settings.ui.split_portrait_mode,
                            label="Portrait mode",
                        )
                    gr.HTML(
                        '<div class="dc-note-detail">Portrait is made for Reels, Shorts, and TikTok. Captions auto-fit the vertical canvas.</div>'
                    )
                    add_subtitles = gr.Checkbox(
                        value=False,
                        label="Add auto captions",
                    )
                    render_button = gr.Button(
                        "Create my ZIP",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-split-render",
                    )
                    download = gr.DownloadButton(
                        label="Download",
                        value=None,
                        visible=True,
                        interactive=False,
                        variant="primary",
                    )

            # ------------------------------------------------------- behaviour
            mode.change(self._mode_help, inputs=mode, outputs=mode_help)

            source.change(
                lambda path: self._load(ctx, path),
                inputs=source,
                outputs=[media_state, message],
            )

            def import_youtube(
                url: str,
                confirmed: bool,
                progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio injection
            ) -> tuple[Any, str]:
                return self._import_youtube(ctx, url, confirmed, progress)

            youtube_import.click(
                import_youtube,
                inputs=[youtube_url, youtube_rights],
                outputs=[media_state, message],
            )

            plan_button.click(
                lambda media, chosen, length, over, thresh, stamps, limit, want: self._plan(
                    ctx, media, chosen, length, over, thresh, stamps, limit, want
                ),
                inputs=[media_state, mode, clip_length, overlap, threshold, timestamps, max_clips, focus],
                outputs=[plan_state, summary, strip, clip_table, message],
            )

            render_button.click(
                lambda plan, media, fmt, qual, exact, out_fmt, portrait, captions: self._render(
                    ctx, plan, media, fmt, qual, exact, out_fmt, portrait, captions
                ),
                inputs=[
                    plan_state,
                    media_state,
                    container_choice,
                    quality,
                    accurate,
                    output_format,
                    portrait_mode,
                    add_subtitles,
                ],
                outputs=[download, message],
            )
            output_format.change(
                lambda value, mode: self._remember_split_defaults(ctx, value, mode),
                inputs=[output_format, portrait_mode],
            )
            portrait_mode.change(
                lambda fmt, value: self._remember_split_defaults(ctx, fmt, value),
                inputs=[output_format, portrait_mode],
            )
        return column

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _mode_help(mode: str) -> str:
        """One line explaining the selected mode."""
        return f'<div class="dc-note-detail">{_MODE_HELP.get(str(mode), "")}</div>'

    @staticmethod
    def _load(ctx: PageContext, path: str | None) -> tuple[Any, str]:
        """Probe the dropped file and show its properties."""
        if not path:
            return None, ""
        media, error = safe_call(ctx.media.import_file, path)
        if error:
            return None, error
        return media, banner(
            f"{media.name} is ready. Plan the clips, then download the ZIP.",
            level="success",
            title="Video ready",
        )

    @staticmethod
    def _import_youtube(
        ctx: PageContext,
        url: str,
        confirmed: bool,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio injection
    ) -> tuple[Any, str]:
        """Download a permitted YouTube video and feed it to the normal importer."""
        if not confirmed:
            return None, banner(
                "Confirm that you have permission to use this video.",
                level="warning",
                title="Permission required",
            )

        def report(fraction: float, stage: str) -> None:
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        path, error = safe_call(ctx.youtube.download, url, on_progress=report)
        if error or path is None:
            return None, error
        return SplitPage._load(ctx, str(path))

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
        output_format: str,
        portrait_mode: str,
        add_subtitles: bool,
        progress: gr.Progress | None = None,
    ) -> tuple[Any, str]:
        """Render every segment in the current plan."""
        if plan is None:
            return gr.update(value=None, interactive=False), banner(
                "Plan a split before rendering.", level="warning", title="No plan yet"
            )

        def report(fraction: float, stage: str) -> None:
            """Forward per-clip progress to the Gradio progress bar."""
            if progress is not None:
                progress(min(max(fraction, 0.0), 1.0), desc=stage)

        target = ensure_dir(
            ctx.paths.temp
            / "downloads"
            / f"{safe_filename(media.stem, fallback='clips')}-{int(time.time())}"
        )
        render_args = {
            "container": str(container),
            "quality": Quality(str(quality)),
            "accurate": bool(accurate),
            "on_progress": report,
            "output_format": str(output_format),
            "portrait_mode": str(portrait_mode),
        }

        cleanup_paths: list[Path] = []
        succeeded = False
        try:
            if add_subtitles:
                transcript, error = safe_call(
                    ctx.ai.transcribe,
                    media.path,
                    on_progress=lambda fraction, stage: report(fraction, f"Subtitles · {stage}"),
                )
                if error or transcript is None:
                    return gr.update(value=None, interactive=False), error or banner(
                        "The transcript could not be created, so captioned clips were not rendered.",
                        level="error",
                        title="Subtitles failed",
                    )
            if add_subtitles:
                rendered, error = safe_call(ctx.split.render, plan, target / "raw", **render_args)
                if error or not rendered:
                    return gr.update(value=None, interactive=False), error or banner(
                        "Nothing was written.", level="warning", title="Empty render"
                    )
                cleanup_paths.extend(rendered)
                paths: list[Path] = []
                caption_dir = ensure_dir(target / "captioned")
                for clip, segment in zip(rendered, plan.segments, strict=False):
                    clip_media, probe_error = safe_call(ctx.media.import_file, clip)
                    if probe_error or clip_media is None:
                        return gr.update(value=None, interactive=False), probe_error
                    burned, burn_error = safe_call(
                        ctx.subtitles.burn,
                        clip_media,
                        transcript,
                        caption_dir / clip.name,
                        quality=Quality(str(quality)),
                        offset=float(segment.start),
                        on_progress=report,
                    )
                    if burn_error or burned is None:
                        return gr.update(value=None, interactive=False), burn_error or banner(
                            "Caption rendering failed before the ZIP could be prepared.",
                            level="error",
                            title="Subtitles failed",
                        )
                    paths.append(burned)
                    cleanup_paths.append(burned)
                zip_path = ctx.split._zip_outputs(
                    paths,
                    caption_dir,
                    stem=media.stem,
                    output_format=str(output_format),
                    portrait_mode=str(portrait_mode),
                )
            else:
                rendered, error = safe_call(ctx.split.render_bundle, plan, target / "clips", **render_args)
                if error or not rendered:
                    return gr.update(value=None, interactive=False), error or banner(
                        "Nothing was written.", level="warning", title="Empty render"
                    )
                paths, zip_path = rendered
                cleanup_paths.extend(paths)

            SplitPage._cleanup_clip_files(cleanup_paths)
            SplitPage._record_render(ctx, media, paths, zip_path, output_format, add_subtitles)
            succeeded = True
            caption_note = " with captions" if add_subtitles else ""
            detail = (
                f"Rendered {len(paths)} clips{caption_note} and prepared "
                f"{zip_path.name} ({human_size(zip_path.stat().st_size)})."
            )
            return (
                gr.update(value=str(zip_path), label="Download", visible=True, interactive=True),
                banner(detail, level="success", title="Download ready"),
            )
        finally:
            if not succeeded:
                shutil.rmtree(target, ignore_errors=True)

    @staticmethod
    def _record_render(
        ctx: PageContext,
        media: Any,
        paths: list[Path],
        zip_path: Path,
        output_format: str,
        add_subtitles: bool,
    ) -> None:
        """Persist the latest downloadable render for the dashboard."""
        payload = {
            "source": media.name,
            "stem": media.stem,
            "archive": str(zip_path),
            "clip_count": len(paths),
            "size_bytes": zip_path.stat().st_size if zip_path.exists() else 0,
            "output_format": str(output_format),
            "subtitles": bool(add_subtitles),
            "created_at": time.time(),
            "status": "Done",
        }
        target = ctx.paths.cache / "last_render.json"
        try:
            ensure_dir(target.parent)
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _cleanup_clip_files(paths: list[Path]) -> None:
        """Remove temporary clip files once the ZIP is ready for download."""
        parents = {path.parent for path in paths}
        for path in paths:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        for parent in parents:
            with suppress(OSError):
                shutil.rmtree(parent)

    @staticmethod
    def _remember_split_defaults(ctx: PageContext, output_format: str, portrait_mode: str) -> None:
        """Persist the last selected output options."""
        ctx.settings.ui.split_output_format = str(output_format)
        ctx.settings.ui.split_portrait_mode = str(portrait_mode)
        with suppress(Exception):
            save_settings(ctx.settings, ctx.container.paths.config_file)

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
