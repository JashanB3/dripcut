"""Subtitle Studio: captions from a transcript, styled and written out.

Writing a subtitle file is instant, so those actions run inline. Burning captions
into the picture is a full re-encode, so it reports progress and can be cancelled.
Soft-attaching is a remux and lands somewhere in between.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gradio as gr

from dripcut.engines.video.encode import Quality
from dripcut.models.subtitle import SubtitleFormat
from dripcut.ui.components.widgets import banner, card, chips, empty_state, table
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.concurrency import CancelToken

__all__ = ["SubtitlesPage"]

_FORMATS = [fmt.value for fmt in SubtitleFormat]


class SubtitlesPage(Page):
    """Generate, style, preview and apply captions."""

    key = "subtitles"
    label = "Subtitle Studio"
    icon = "\u2263"
    group = "Workspace"
    title = "Subtitle Studio"
    subtitle = "Six presets, four formats, and a burn-in that matches the preview."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None
        self._token: CancelToken | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the subtitle studio."""
        self._ctx = ctx
        presets = self._presets()
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            media_state = gr.State(None)
            transcript_state = gr.State(None)
            subtitle_state = gr.State(None)

            message = gr.HTML()

            with gr.Row():
                with gr.Column(scale=2):
                    source = gr.File(
                        label="Video",
                        type="filepath",
                        elem_classes=["dc-dropzone"],
                        elem_id="dc-subs-source",
                    )
                    info = gr.HTML()
                    load_transcript = gr.Button(
                        "Load or create the transcript",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-primary-subtitles",
                    )
                    gr.HTML(
                        '<div class="dc-note-detail">Uses the cached transcript when there '
                        "is one, otherwise runs Whisper.</div>"
                    )
                with gr.Column(scale=3):
                    style_name = gr.Dropdown(
                        presets, value=presets[0] if presets else None, label="Caption preset"
                    )
                    style_detail = gr.HTML(self._style_detail(presets[0] if presets else ""))
                    with gr.Row():
                        max_chars = gr.Slider(
                            16, 60, value=34, step=1, label="Characters per line"
                        )
                        max_lines = gr.Slider(1, 3, value=2, step=1, label="Lines per caption")
                        offset = gr.Slider(
                            -5.0, 5.0, value=0.0, step=0.1, label="Timing offset (s)"
                        )
                    uppercase = gr.Checkbox(value=False, label="Force uppercase")
                    preview = gr.HTML()

            with gr.Tabs():
                with gr.Tab("Write a file"):
                    subtitle_format = gr.Dropdown(_FORMATS, value="srt", label="Format")
                    destination = gr.Textbox(
                        label="Output folder", value=str(ctx.output_dir)
                    )
                    write = gr.Button(
                        "Write subtitles",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-subs-write",
                    )
                    written_files = gr.Files(label="Subtitle file", visible=False)

                with gr.Tab("Burn into the picture"):
                    burn_quality = gr.Dropdown(
                        [quality.value for quality in Quality], value="high", label="Quality"
                    )
                    gr.HTML(
                        '<div class="dc-note-detail">Burning re-encodes the video, so it '
                        "takes about as long as an export. The captions become part of the "
                        "image and cannot be turned off later.</div>"
                    )
                    with gr.Row():
                        burn = gr.Button(
                            "Burn captions",
                            variant="primary",
                            elem_classes=["dc-btn", "dc-btn-primary"],
                            elem_id="dc-subs-burn",
                        )
                        stop = gr.Button(
                            "Stop", elem_classes=["dc-btn", "dc-btn-danger"],
                            elem_id="dc-subs-stop",
                        )
                    burned = gr.Files(label="Burned video", visible=False)

                with gr.Tab("Attach as a track"):
                    language = gr.Textbox(value="eng", label="Language tag")
                    gr.HTML(
                        '<div class="dc-note-detail">A soft track can be switched off by '
                        "the player. Much faster: the video is copied, not re-encoded.</div>"
                    )
                    attach = gr.Button(
                        "Attach subtitles",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-subs-attach",
                    )
                    attached = gr.Files(label="Video with a subtitle track", visible=False)

            # --------------------------------------------------------- wiring
            source.change(self._load, inputs=source, outputs=[media_state, info, message])
            style_name.change(self._style_detail, inputs=style_name, outputs=style_detail)

            preview_inputs = [transcript_state, style_name, max_chars, max_lines, uppercase]
            load_transcript.click(
                self._transcript,
                inputs=[media_state, *preview_inputs[1:]],
                outputs=[transcript_state, preview, message],
            )
            for control in (style_name, max_chars, max_lines, uppercase):
                control.change(self._preview, inputs=preview_inputs, outputs=preview)

            write.click(
                self._write,
                inputs=[
                    media_state, transcript_state, style_name, max_chars, max_lines,
                    uppercase, subtitle_format, offset, destination,
                ],
                outputs=[subtitle_state, written_files, message],
            )
            burn.click(
                self._burn,
                inputs=[
                    media_state, transcript_state, style_name, max_chars, max_lines,
                    uppercase, burn_quality, offset, destination,
                ],
                outputs=[burned, message],
            )
            stop.click(self._stop, outputs=message)
            attach.click(
                self._attach,
                inputs=[media_state, subtitle_state, language, destination],
                outputs=[attached, message],
            )
        return column

    # ----------------------------------------------------------------- helpers

    def _presets(self) -> list[str]:
        """Available caption preset names."""
        if self._ctx is None:
            return []
        try:
            return list(self._ctx.subtitles.presets())
        except Exception:  # noqa: BLE001 - never blank the page over a preset list
            return []

    def _style(
        self, name: str, max_chars: float, max_lines: float, uppercase: bool
    ) -> Any:
        """Load a preset and apply the page's overrides."""
        if self._ctx is None:
            return None
        style = self._ctx.subtitles.preset(str(name))
        style.max_chars = int(max_chars)
        style.max_lines = int(max_lines)
        style.uppercase = bool(uppercase)
        return style

    def _style_detail(self, name: str) -> str:
        """Describe a preset's typography and placement."""
        if self._ctx is None or not name:
            return ""
        style, error = safe_call(self._ctx.subtitles.preset, str(name))
        if error or style is None:
            return ""
        tags = [
            style.font_name,
            f"{style.font_size}px",
            "bold" if style.bold else "regular",
            f"outline {style.outline_width}",
            f"align {style.alignment}",
            f"{style.max_lines}\u00d7{style.max_chars}",
        ]
        if style.karaoke:
            tags.append("karaoke")
        return chips(tags)

    def _require(self, media: Any, transcript: Any) -> tuple[Any, str]:
        """Both a video and a transcript are needed for everything here."""
        if self._ctx is None:
            return None, banner("Not ready yet.", level="error")
        if media is None:
            return None, banner(
                "Add a video first.", level="warning", title="Nothing selected"
            )
        if transcript is None:
            return None, banner(
                "Load the transcript first.", level="warning", title="No transcript"
            )
        return self._ctx, ""

    @staticmethod
    def _folder(destination: str, fallback: Any) -> Path:
        """Resolve the output folder box."""
        cleaned = (destination or "").strip()
        return Path(cleaned).expanduser() if cleaned else Path(fallback)

    # ---------------------------------------------------------------- actions

    def _load(self, path: str | None) -> tuple[Any, str, str]:
        """Probe the chosen video."""
        if not path or self._ctx is None:
            return None, "", ""
        media, error = safe_call(self._ctx.media.import_file, path)
        if error:
            return None, "", error
        return media, card(table(["Property", "Value"], media.summary_rows()), title=media.name), ""

    def _stop(self) -> str:
        """Cancel a burn in progress."""
        if self._token is None:
            return banner("Nothing is running.", level="info", title="Stop")
        self._token.cancel()
        return banner("Stopping the burn\u2026", level="info", title="Stop")

    def _transcript(
        self,
        media: Any,
        style_name: str,
        max_chars: float,
        max_lines: float,
        uppercase: bool,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection contract
    ) -> tuple[Any, str, str]:
        """Fetch the cached transcript, or run Whisper to create one."""
        if self._ctx is None:
            return None, "", banner("Not ready yet.", level="error")
        if media is None:
            return None, "", banner(
                "Add a video first.", level="warning", title="Nothing selected"
            )

        self._token = CancelToken()

        def report(fraction: float, stage: str) -> None:
            """Forward engine progress into the Gradio bar."""
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        transcript, error = safe_call(
            self._ctx.ai.transcribe,
            media.path,
            on_progress=report,
            cancel_token=self._token,
        )
        self._token = None
        if error or transcript is None:
            return None, "", error
        return (
            transcript,
            self._preview(transcript, style_name, max_chars, max_lines, uppercase),
            banner(
                f"{transcript.word_count} words ready to caption.",
                level="success",
                title="Transcript loaded",
            ),
        )

    def _preview(
        self, transcript: Any, style_name: str, max_chars: float, max_lines: float, uppercase: bool
    ) -> str:
        """Show the first dozen cues exactly as they will be written."""
        if self._ctx is None or transcript is None:
            return card(
                empty_state("No preview yet", "Load a transcript to see the cues."),
                title="Preview",
            )
        style = self._style(style_name, max_chars, max_lines, uppercase)
        lines, error = safe_call(self._ctx.subtitles.preview_lines, transcript, style, limit=12)
        if error or not lines:
            return card(empty_state("Nothing to preview"), title="Preview")
        return card(table(["At", "Caption"], lines, mono=(0,)), title="Preview")

    def _write(
        self,
        media: Any,
        transcript: Any,
        style_name: str,
        max_chars: float,
        max_lines: float,
        uppercase: bool,
        subtitle_format: str,
        offset: float,
        destination: str,
    ) -> tuple[Any, Any, str]:
        """Write a subtitle file next to the video."""
        ctx, error = self._require(media, transcript)
        if error:
            return None, gr.update(visible=False), error
        folder = self._folder(destination, ctx.output_dir)
        target = folder / media.stem
        written, error = safe_call(
            ctx.subtitles.write,
            transcript,
            target,
            style=self._style(style_name, max_chars, max_lines, uppercase),
            subtitle_format=SubtitleFormat(str(subtitle_format)),
            video_size=media.video.display_resolution if media.video else (1920, 1080),
            offset=float(offset),
        )
        if error or written is None:
            return None, gr.update(visible=False), error
        return (
            written,
            gr.update(value=[str(written)], visible=True),
            banner(f"Wrote {written}", level="success", title="Subtitles written"),
        )

    def _burn(
        self,
        media: Any,
        transcript: Any,
        style_name: str,
        max_chars: float,
        max_lines: float,
        uppercase: bool,
        quality: str,
        offset: float,
        destination: str,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection contract
    ) -> tuple[Any, str]:
        """Burn captions into the picture."""
        ctx, error = self._require(media, transcript)
        if error:
            return gr.update(visible=False), error

        self._token = CancelToken()

        def report(fraction: float, stage: str) -> None:
            """Forward encode progress into the Gradio bar."""
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        folder = self._folder(destination, ctx.output_dir)
        target = folder / f"{media.stem}-captioned.mp4"
        output, error = safe_call(
            ctx.subtitles.burn,
            media,
            transcript,
            target,
            style=self._style(style_name, max_chars, max_lines, uppercase),
            quality=Quality(str(quality)),
            offset=float(offset),
            on_progress=report,
            cancel_token=self._token,
        )
        self._token = None
        if error or output is None:
            return gr.update(visible=False), error
        return gr.update(value=[str(output)], visible=True), banner(
            f"Burned captions into {output.name}", level="success", title="Done"
        )

    def _attach(
        self, media: Any, subtitles: Any, language: str, destination: str
    ) -> tuple[Any, str]:
        """Mux an existing subtitle file in as a switchable track."""
        if self._ctx is None:
            return gr.update(visible=False), banner("Not ready yet.", level="error")
        if media is None:
            return gr.update(visible=False), banner(
                "Add a video first.", level="warning", title="Nothing selected"
            )
        if subtitles is None:
            return gr.update(visible=False), banner(
                "Write a subtitle file first, on the previous tab.",
                level="warning",
                title="No subtitle file",
            )
        folder = self._folder(destination, self._ctx.output_dir)
        target = folder / f"{media.stem}-subtitled.mp4"
        output, error = safe_call(
            self._ctx.subtitles.attach,
            media,
            Path(subtitles),
            target,
            language=(language or "eng").strip(),
        )
        if error or output is None:
            return gr.update(visible=False), error
        return gr.update(value=[str(output)], visible=True), banner(
            f"Attached a {language} track to {output.name}",
            level="success",
            title="Done",
        )

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the caption actions."""
        actions = [
            ("Load the transcript", "dc-primary-subtitles", "whisper words"),
            ("Write subtitles", "dc-subs-write", "srt vtt ass txt file"),
            ("Burn captions", "dc-subs-burn", "hardcode render"),
            ("Attach subtitle track", "dc-subs-attach", "soft mux switchable"),
        ]
        return [
            *super().commands(),
            *[
                {"label": label, "group": "Subtitles", "target": target, "keywords": keywords}
                for label, target, keywords in actions
            ],
        ]
