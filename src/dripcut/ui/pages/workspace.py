"""Workspace: the single-file toolbox.

Every tool here queues a job rather than blocking the interface, so the page stays
responsive and progress is reported in one place (Exports). The page owns no video
logic at all -- it collects parameters and hands them to :class:`ExportService`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.engines.video.encode import Quality
from dripcut.models.job import JobKind
from dripcut.ui.components.widgets import banner, card, table
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["WorkspacePage"]

_CONTAINERS = ["mp4", "mov", "mkv", "webm"]
_QUALITIES = [quality.value for quality in Quality]


class WorkspacePage(Page):
    """Trim, transform, compress, convert, extract and watermark one file."""

    key = "workspace"
    label = "Edit Tools"
    icon = "\u25a3"
    group = "Create"
    title = "Edit Tools"
    subtitle = "Quick fixes for one video: trim, convert, watermark, audio, and more."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    # ------------------------------------------------------------------ layout

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the workspace."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            media_state = gr.State(None)

            with gr.Row():
                with gr.Column(scale=2):
                    source = gr.File(
                        label="Video",
                        type="filepath",
                        elem_classes=["dc-dropzone"],
                        elem_id="dc-workspace-source",
                    )
                    info = gr.HTML()
                with gr.Column(scale=3):
                    message = gr.HTML()
                    queued = gr.HTML()

            with gr.Tabs():
                with gr.Tab("Trim"):
                    trim_start = gr.Number(value=0.0, label="Start (seconds)", minimum=0)
                    trim_end = gr.Number(value=10.0, label="End (seconds)", minimum=0)
                    trim_accurate = gr.Checkbox(
                        value=True, label="Frame-accurate (re-encode) \u2014 off cuts on keyframes"
                    )
                    trim_quality = gr.Dropdown(_QUALITIES, value="high", label="Quality")
                    trim_button = gr.Button(
                        "Queue trim",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-primary-workspace",
                    )

                with gr.Tab("Resize, crop and rotate"):
                    with gr.Row():
                        width = gr.Number(value=0, label="Width (0 = keep)", minimum=0)
                        height = gr.Number(value=0, label="Height (0 = keep)", minimum=0)
                        scale_mode = gr.Dropdown(
                            ["fit", "fill", "stretch", "exact"], value="fit", label="Scale mode"
                        )
                    with gr.Row():
                        rotate = gr.Dropdown(
                            [("None", 0), ("90\u00b0 right", 90), ("180\u00b0", 180), ("90\u00b0 left", 270)],
                            value=0,
                            label="Rotate",
                        )
                        flip = gr.Dropdown(
                            [("None", ""), ("Horizontal", "h"), ("Vertical", "v")],
                            value="",
                            label="Flip",
                        )
                        fps = gr.Number(value=0, label="Frames per second (0 = keep)", minimum=0)
                    speed = gr.Slider(0.25, 4.0, value=1.0, step=0.05, label="Speed")
                    transform_quality = gr.Dropdown(_QUALITIES, value="high", label="Quality")
                    transform_button = gr.Button(
                        "Queue transform",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-transform",
                    )

                with gr.Tab("Compress"):
                    compress_quality = gr.Dropdown(_QUALITIES, value="small", label="Quality")
                    target_mb = gr.Number(
                        value=0, label="Target size in MB (0 = use quality instead)", minimum=0
                    )
                    max_height = gr.Number(value=0, label="Cap height (0 = keep)", minimum=0)
                    compress_button = gr.Button(
                        "Queue compress",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-compress",
                    )

                with gr.Tab("Convert"):
                    convert_container = gr.Dropdown(_CONTAINERS, value="mp4", label="Format")
                    convert_quality = gr.Dropdown(_QUALITIES, value="balanced", label="Quality")
                    convert_button = gr.Button(
                        "Queue convert",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-convert",
                    )

                with gr.Tab("Audio and frames"):
                    with gr.Row():
                        audio_format = gr.Dropdown(
                            ["m4a", "mp3", "wav", "flac"], value="m4a", label="Audio format"
                        )
                        audio_bitrate = gr.Dropdown(
                            ["128k", "192k", "256k", "320k"], value="192k", label="Bitrate"
                        )
                        audio_mono = gr.Checkbox(value=False, label="Mono")
                    audio_button = gr.Button(
                        "Queue audio extract",
                        elem_classes=["dc-btn"],
                        elem_id="dc-workspace-audio",
                    )
                    with gr.Row():
                        every_seconds = gr.Number(value=1.0, label="A frame every N seconds", minimum=0)
                        frame_width = gr.Number(value=0, label="Frame width (0 = source)", minimum=0)
                        image_format = gr.Dropdown(["png", "jpg"], value="png", label="Image format")
                    frames_button = gr.Button(
                        "Queue frame export",
                        elem_classes=["dc-btn"],
                        elem_id="dc-workspace-frames",
                    )

                with gr.Tab("GIF"):
                    with gr.Row():
                        gif_start = gr.Number(value=0.0, label="Start (seconds)", minimum=0)
                        gif_end = gr.Number(value=6.0, label="End (seconds)", minimum=0)
                    with gr.Row():
                        gif_fps = gr.Slider(5, 30, value=15, step=1, label="Frames per second")
                        gif_width = gr.Slider(160, 1280, value=640, step=20, label="Width")
                    gif_button = gr.Button(
                        "Queue GIF",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-gif",
                    )

                with gr.Tab("Watermark"):
                    logo = gr.File(label="Logo image (optional)", type="filepath")
                    watermark_text = gr.Textbox(label="Or text", placeholder="@yourhandle")
                    with gr.Row():
                        position = gr.Dropdown(
                            ["top-left", "top-right", "bottom-left", "bottom-right", "center"],
                            value="bottom-right",
                            label="Position",
                        )
                        opacity = gr.Slider(0.1, 1.0, value=0.85, step=0.05, label="Opacity")
                        font_size = gr.Slider(12, 96, value=36, step=2, label="Text size")
                    watermark_button = gr.Button(
                        "Queue watermark",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-watermark",
                    )

                with gr.Tab("Merge"):
                    merge_sources = gr.File(
                        label="Videos to join, in order",
                        type="filepath",
                        file_count="multiple",
                        elem_classes=["dc-dropzone"],
                    )
                    merge_name = gr.Textbox(value="merged", label="Output name")
                    merge_container = gr.Dropdown(_CONTAINERS, value="mp4", label="Format")
                    merge_button = gr.Button(
                        "Queue merge",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-workspace-merge",
                    )

            destination = gr.Textbox(
                label="Output folder", value=str(ctx.output_dir), placeholder=str(ctx.output_dir)
            )

            # --------------------------------------------------------- wiring
            source.change(self._load, inputs=source, outputs=[media_state, info, message])

            trim_button.click(
                self._trim,
                inputs=[media_state, trim_start, trim_end, trim_accurate, trim_quality, destination],
                outputs=[queued, message],
            )
            transform_button.click(
                self._transform,
                inputs=[
                    media_state, width, height, scale_mode, rotate, flip, fps, speed,
                    transform_quality, destination,
                ],
                outputs=[queued, message],
            )
            compress_button.click(
                self._compress,
                inputs=[media_state, compress_quality, target_mb, max_height, destination],
                outputs=[queued, message],
            )
            convert_button.click(
                self._convert,
                inputs=[media_state, convert_container, convert_quality, destination],
                outputs=[queued, message],
            )
            audio_button.click(
                self._audio,
                inputs=[media_state, audio_format, audio_bitrate, audio_mono, destination],
                outputs=[queued, message],
            )
            frames_button.click(
                self._frames,
                inputs=[media_state, every_seconds, frame_width, image_format, destination],
                outputs=[queued, message],
            )
            gif_button.click(
                self._gif,
                inputs=[media_state, gif_start, gif_end, gif_fps, gif_width, destination],
                outputs=[queued, message],
            )
            watermark_button.click(
                self._watermark,
                inputs=[media_state, logo, watermark_text, position, opacity, font_size, destination],
                outputs=[queued, message],
            )
            merge_button.click(
                self._merge,
                inputs=[merge_sources, merge_name, merge_container, destination],
                outputs=[queued, message],
            )
        return column

    # ----------------------------------------------------------------- helpers

    def _require(self, media: Any) -> tuple[Any, str]:
        """Guard used by every tool: a file and a live context are needed."""
        if self._ctx is None:
            return None, banner("The workspace is not ready yet.", level="error")
        if media is None:
            return None, banner(
                "Add a video first.", level="warning", title="Nothing selected"
            )
        return self._ctx, ""

    @staticmethod
    def _folder(destination: str) -> str | None:
        """Normalise the output folder box; blank means the configured default."""
        cleaned = (destination or "").strip()
        return cleaned or None

    def _queued(self, job: Any) -> tuple[str, str]:
        """Confirmation card for a job that has just been submitted."""
        return (
            card(
                table(
                    ["Job", "Value"],
                    [
                        ("Title", job.title),
                        ("Kind", job.kind.value),
                        ("Status", job.status.value),
                        ("Id", job.id),
                    ],
                ),
                title="Queued",
                eyebrow="Watch it on the Exports page",
            ),
            "",
        )

    def _load(self, path: str | None) -> tuple[Any, str, str]:
        """Probe the chosen file."""
        if not path or self._ctx is None:
            return None, "", ""
        media, error = safe_call(self._ctx.media.import_file, path)
        if error:
            return None, "", error
        return media, card(table(["Property", "Value"], media.summary_rows()), title=media.name), ""

    # ------------------------------------------------------------------- tools

    def _trim(
        self, media: Any, start: float, end: float, accurate: bool, quality: str, destination: str
    ) -> tuple[str, str]:
        """Queue a trim between two times."""
        ctx, error = self._require(media)
        if error:
            return "", error
        if float(end) <= float(start):
            return "", banner(
                "The end time must be after the start time.",
                level="warning",
                title="Check the range",
            )
        job, error = safe_call(
            ctx.export.queue_trim,
            media,
            start=float(start),
            end=float(end),
            accurate=bool(accurate),
            quality=Quality(str(quality)),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _transform(
        self,
        media: Any,
        width: float,
        height: float,
        scale_mode: str,
        rotate: int,
        flip: str,
        fps: float,
        speed: float,
        quality: str,
        destination: str,
    ) -> tuple[str, str]:
        """Queue any combination of resize, rotate, flip, fps and speed."""
        ctx, error = self._require(media)
        if error:
            return "", error
        options: dict[str, Any] = {"scale_mode": str(scale_mode)}
        if int(width) or int(height):
            options["resize"] = (int(width) or None, int(height) or None)
        if int(rotate):
            options["rotate"] = int(rotate)
        if flip:
            options["flip"] = str(flip)
        if float(fps) > 0:
            options["fps"] = float(fps)
        if abs(float(speed) - 1.0) > 1e-3:
            options["speed"] = float(speed)
        if len(options) == 1:
            return "", banner(
                "Choose at least one change to apply.", level="warning", title="Nothing to do"
            )
        job, error = safe_call(
            ctx.export.queue_transform,
            media,
            quality=Quality(str(quality)),
            kind=JobKind.RESIZE,
            folder=self._folder(destination),
            **options,
        )
        return self._queued(job) if job else ("", error)

    def _compress(
        self, media: Any, quality: str, target_mb: float, max_height: float, destination: str
    ) -> tuple[str, str]:
        """Queue a compression pass, by quality or to a size budget."""
        ctx, error = self._require(media)
        if error:
            return "", error
        job, error = safe_call(
            ctx.export.queue_compress,
            media,
            quality=Quality(str(quality)),
            target_mb=float(target_mb) or None,
            max_height=int(max_height) or None,
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _convert(self, media: Any, container: str, quality: str, destination: str) -> tuple[str, str]:
        """Queue a container change."""
        ctx, error = self._require(media)
        if error:
            return "", error
        job, error = safe_call(
            ctx.export.queue_convert,
            media,
            container=str(container),
            quality=Quality(str(quality)),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _audio(
        self, media: Any, audio_format: str, bitrate: str, mono: bool, destination: str
    ) -> tuple[str, str]:
        """Queue an audio-only export."""
        ctx, error = self._require(media)
        if error:
            return "", error
        job, error = safe_call(
            ctx.export.queue_extract_audio,
            media,
            audio_format=str(audio_format),
            bitrate=str(bitrate),
            mono=bool(mono),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _frames(
        self, media: Any, every_seconds: float, width: float, image_format: str, destination: str
    ) -> tuple[str, str]:
        """Queue a still-frame export."""
        ctx, error = self._require(media)
        if error:
            return "", error
        job, error = safe_call(
            ctx.export.queue_frames,
            media,
            every_seconds=float(every_seconds) or None,
            width=int(width) or None,
            image_format=str(image_format),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _gif(
        self, media: Any, start: float, end: float, fps: float, width: float, destination: str
    ) -> tuple[str, str]:
        """Queue an animated GIF."""
        ctx, error = self._require(media)
        if error:
            return "", error
        if float(end) <= float(start):
            return "", banner(
                "The end time must be after the start time.",
                level="warning",
                title="Check the range",
            )
        job, error = safe_call(
            ctx.export.queue_gif,
            media,
            start=float(start),
            end=float(end),
            fps=int(fps),
            width=int(width),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _watermark(
        self,
        media: Any,
        logo: str | None,
        text: str,
        position: str,
        opacity: float,
        font_size: float,
        destination: str,
    ) -> tuple[str, str]:
        """Queue an image or text watermark."""
        ctx, error = self._require(media)
        if error:
            return "", error
        if not logo and not (text or "").strip():
            return "", banner(
                "Add a logo image or some text.", level="warning", title="Nothing to overlay"
            )
        job, error = safe_call(
            ctx.export.queue_watermark,
            media,
            logo=Path(logo) if logo else None,
            text=(text or "").strip(),
            position=str(position),
            opacity=float(opacity),
            font_size=int(font_size),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def _merge(
        self, sources: list[str] | None, name: str, container: str, destination: str
    ) -> tuple[str, str]:
        """Queue a join of several files, in the order given."""
        if self._ctx is None:
            return "", banner("The workspace is not ready yet.", level="error")
        paths = [Path(item) for item in (sources or [])]
        if len(paths) < 2:
            return "", banner(
                "Pick at least two files to join.", level="warning", title="Not enough input"
            )
        job, error = safe_call(
            self._ctx.export.queue_merge,
            paths,
            name=(name or "merged").strip(),
            container=str(container),
            folder=self._folder(destination),
        )
        return self._queued(job) if job else ("", error)

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus every tool in the workspace."""
        tools = [
            ("Trim video", "dc-primary-workspace", "cut range"),
            ("Resize or rotate", "dc-workspace-transform", "crop scale flip fps speed"),
            ("Compress video", "dc-workspace-compress", "shrink size"),
            ("Convert format", "dc-workspace-convert", "container mp4 mov mkv webm"),
            ("Extract audio", "dc-workspace-audio", "sound m4a mp3 wav"),
            ("Export frames", "dc-workspace-frames", "stills png jpg"),
            ("Make a GIF", "dc-workspace-gif", "animation loop"),
            ("Add a watermark", "dc-workspace-watermark", "logo text overlay"),
            ("Merge videos", "dc-workspace-merge", "join concatenate"),
        ]
        return [
            *super().commands(),
            *[
                {"label": label, "group": "Workspace", "target": target, "keywords": keywords}
                for label, target, keywords in tools
            ],
        ]
