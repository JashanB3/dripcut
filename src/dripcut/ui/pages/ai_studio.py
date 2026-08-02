"""AI Studio: transcription and analysis, entirely on this machine.

Whisper runs locally and Ollama runs on localhost. Both are slow enough to need
real progress and a working cancel button, so every long call here takes a
:class:`CancelToken` that the Stop button flips.

Nothing on this page is required to use DripCut. When Whisper or Ollama are
missing the page says so plainly and stays usable for anything cached.
"""

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
from dripcut.models.clip import Segment, SplitMode, SplitPlan
from dripcut.ui.components.widgets import banner, card, chips, empty_state, stat_grid, table
from dripcut.ui.pages.base import Page, PageContext, safe_call
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir, human_size, safe_filename
from dripcut.utils.timecode import format_timecode

__all__ = ["AIStudioPage"]

_FOCUS = ["auto", "hooks", "funny", "educational", "story", "quotes"]


class AIStudioPage(Page):
    """Transcribe, then ask the local model what is worth keeping."""

    key = "ai_studio"
    label = "AI Clips"
    icon = "\u25c8"
    group = "Create"
    title = "AI Clips"
    subtitle = "Find the moments people actually want to watch, then download them."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None
        self._token: CancelToken | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the AI studio."""
        self._ctx = ctx
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            media_state = gr.State(None)
            transcript_state = gr.State(None)
            highlights_state = gr.State([])

            status = gr.HTML(self._status())
            message = gr.HTML()

            with gr.Row():
                with gr.Column(scale=2):
                    with gr.Tabs(elem_classes=["dc-source-tabs"]):
                        with gr.Tab("Upload video"):
                            source = gr.File(
                                label="Video or audio",
                                type="filepath",
                                elem_classes=["dc-dropzone"],
                                elem_id="dc-ai-source",
                            )
                        with gr.Tab("YouTube link"):
                            youtube_url = gr.Textbox(
                                label="YouTube video link",
                                placeholder="https://www.youtube.com/watch?v=...",
                                lines=1,
                                elem_id="dc-ai-youtube-url",
                            )
                            youtube_rights = gr.Checkbox(
                                value=False,
                                label="I have permission to download and edit this video",
                            )
                            youtube_import = gr.Button(
                                "Use this YouTube video",
                                elem_classes=["dc-btn", "dc-btn-secondary"],
                                elem_id="dc-ai-youtube-import",
                            )
                    info = gr.HTML()
                    force = gr.Checkbox(
                        value=False, label="Ignore the cached transcript and run again"
                    )
                    initial_prompt = gr.Textbox(
                        label="Vocabulary hint (names, jargon)",
                        placeholder="DripCut, Anthropic, VideoToolbox",
                    )
                    with gr.Row():
                        transcribe = gr.Button(
                            "Transcribe",
                            variant="primary",
                            elem_classes=["dc-btn", "dc-btn-primary"],
                            elem_id="dc-primary-ai_studio",
                        )
                        stop = gr.Button(
                            "Stop", elem_classes=["dc-btn", "dc-btn-danger"],
                            elem_id="dc-ai-stop",
                        )
                with gr.Column(scale=3):
                    overview = gr.HTML()
                    transcript_view = gr.Textbox(
                        label="Transcript",
                        lines=14,
                        elem_id="dc-ai-transcript",
                    )

            with gr.Tabs():
                with gr.Tab("Highlights"):
                    with gr.Row():
                        target_length = gr.Slider(
                            10, 180, value=45, step=5, label="Target clip length (s)"
                        )
                        max_clips = gr.Slider(1, 20, value=8, step=1, label="How many")
                        focus = gr.Dropdown(_FOCUS, value="auto", label="Look for")
                        min_score = gr.Slider(
                            0.0, 1.0, value=0.35, step=0.05, label="Minimum score"
                        )
                    find_highlights = gr.Button(
                        "Find highlights",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-ai-highlights",
                    )
                    with gr.Row(elem_classes=["dc-render-options"]):
                        output_format = gr.Dropdown(
                            [
                                ("Landscape", "landscape"),
                                ("Portrait", "portrait"),
                                ("Square", "square"),
                            ],
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
                    add_subtitles = gr.Checkbox(
                        value=False,
                        label="Add subtitles to rendered highlights",
                    )
                    render_highlights = gr.Button(
                        "Render highlights",
                        variant="primary",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        elem_id="dc-ai-render-highlights",
                    )
                    highlight_download = gr.DownloadButton(
                        "Download",
                        value=None,
                        visible=True,
                        interactive=False,
                        variant="primary",
                    )
                    highlights_view = gr.HTML()

                with gr.Tab("Hooks"):
                    find_hooks = gr.Button(
                        "Find hooks",
                        elem_classes=["dc-btn", "dc-btn-primary"],
                        variant="primary",
                        elem_id="dc-ai-hooks",
                    )
                    hooks_view = gr.HTML()

                with gr.Tab("Titles and summary"):
                    title_count = gr.Slider(3, 10, value=5, step=1, label="How many titles")
                    with gr.Row():
                        suggest_titles = gr.Button(
                            "Suggest titles", elem_classes=["dc-btn"], elem_id="dc-ai-titles"
                        )
                        summarise = gr.Button(
                            "Summarise", elem_classes=["dc-btn"], elem_id="dc-ai-summary"
                        )
                    titles_view = gr.HTML()

                with gr.Tab("Chapters"):
                    max_chapters = gr.Slider(3, 16, value=8, step=1, label="Maximum chapters")
                    suggest_chapters = gr.Button(
                        "Suggest chapters", elem_classes=["dc-btn"], elem_id="dc-ai-chapters"
                    )
                    chapters_view = gr.HTML()

            # --------------------------------------------------------- wiring
            source.change(self._load, inputs=source, outputs=[media_state, info, message])
            youtube_import.click(
                self._import_youtube,
                inputs=[youtube_url, youtube_rights],
                outputs=[media_state, info, message],
            )
            transcribe.click(
                self._transcribe,
                inputs=[media_state, force, initial_prompt],
                outputs=[transcript_state, transcript_view, overview, status, message],
            )
            stop.click(self._stop, outputs=message)
            find_highlights.click(
                self._highlights,
                inputs=[transcript_state, target_length, max_clips, focus, min_score],
                outputs=[highlights_state, highlights_view, message],
            )
            render_highlights.click(
                self._render_highlights,
                inputs=[
                    media_state,
                    transcript_state,
                    highlights_state,
                    output_format,
                    portrait_mode,
                    add_subtitles,
                ],
                outputs=[highlight_download, message],
            )
            output_format.change(
                self._remember_output_defaults,
                inputs=[output_format, portrait_mode],
            )
            portrait_mode.change(
                self._remember_output_defaults,
                inputs=[output_format, portrait_mode],
            )
            find_hooks.click(
                self._hooks, inputs=transcript_state, outputs=[hooks_view, message]
            )
            suggest_titles.click(
                self._titles, inputs=[transcript_state, title_count], outputs=[titles_view, message]
            )
            summarise.click(
                self._summary, inputs=transcript_state, outputs=[titles_view, message]
            )
            suggest_chapters.click(
                self._chapters,
                inputs=[transcript_state, max_chapters],
                outputs=[chapters_view, message],
            )
        return column

    # ----------------------------------------------------------------- panels

    def _status(self) -> str:
        """What is installed and reachable right now."""
        if self._ctx is None:
            return ""
        state, error = safe_call(self._ctx.ai.status)
        if error or state is None:
            return card(empty_state("AI status unavailable"), title="Local models")
        ready = [name for name, ok in (
            ("Whisper", state["whisper_installed"]),
            ("Ollama", state["ollama_up"]),
            (str(state["ollama_model"]), state["ollama_model_installed"]),
        ) if ok]
        missing = [name for name, ok in (
            ("Whisper", state["whisper_installed"]),
            ("Ollama", state["ollama_up"]),
            (str(state["ollama_model"]), state["ollama_model_installed"]),
        ) if not ok]
        body = chips(ready, mint=ready) + chips(missing)
        if not state["enabled"]:
            body += banner(
                "AI is switched off in Settings. Turn it on to use this page.",
                level="warning",
                title="Disabled",
            )
        elif missing:
            body += banner(
                "Run 'dripcut doctor' in a terminal for the exact install commands.",
                level="info",
                title=f"Not ready: {', '.join(missing)}",
            )
        return card(body, title="Local models")

    def _require(self, transcript: Any) -> tuple[Any, str]:
        """Analysis needs a transcript; say so once, in one place."""
        if self._ctx is None:
            return None, banner("Not ready yet.", level="error")
        if transcript is None:
            return None, banner(
                "Transcribe something first \u2014 the analysis works on the words.",
                level="warning",
                title="No transcript",
            )
        return self._ctx, ""

    # ---------------------------------------------------------------- actions

    def _load(self, path: str | None) -> tuple[Any, str, str]:
        """Probe the chosen file and warn early if it has no audio."""
        if not path or self._ctx is None:
            return None, "", ""
        media, error = safe_call(self._ctx.media.import_file, path)
        if error:
            return None, "", error
        note = ""
        if not media.has_audio:
            note = banner(
                f"{media.name} has no audio track, so it cannot be transcribed.",
                level="warning",
                title="No audio",
            )
        return media, card(table(["Property", "Value"], media.summary_rows()), title=media.name), note

    def _import_youtube(
        self,
        url: str,
        confirmed: bool,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio injection
    ) -> tuple[Any, str, str]:
        """Download a permitted YouTube video and load it like an uploaded file."""
        if self._ctx is None:
            return None, "", banner("Not ready yet.", level="error")
        if not confirmed:
            return None, "", banner(
                "Confirm that you have permission to use this video.",
                level="warning",
                title="Permission required",
            )

        def report(fraction: float, stage: str) -> None:
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        path, error = safe_call(self._ctx.youtube.download, url, on_progress=report)
        if error or path is None:
            return None, "", error
        return self._load(str(path))

    def _stop(self) -> str:
        """Cancel whatever long call is running."""
        if self._token is None:
            return banner("Nothing is running.", level="info", title="Stop")
        self._token.cancel()
        return banner("Stopping\u2026 the engine will wind down shortly.", level="info", title="Stop")

    def _transcribe(
        self,
        media: Any,
        force: bool,
        initial_prompt: str,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection contract
    ) -> tuple[Any, str, str, str, str]:
        """Run Whisper, or reuse the cached transcript."""
        if self._ctx is None:
            return None, "", "", self._status(), banner("Not ready yet.", level="error")
        if media is None:
            return None, "", "", self._status(), banner(
                "Add a file first.", level="warning", title="Nothing selected"
            )

        self._token = CancelToken()

        def report(fraction: float, stage: str) -> None:
            """Forward engine progress into the Gradio bar."""
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        transcript, error = safe_call(
            self._ctx.ai.transcribe,
            media.path,
            force=bool(force),
            initial_prompt=(initial_prompt or "").strip(),
            on_progress=report,
            cancel_token=self._token,
        )
        self._token = None
        if error or transcript is None:
            return None, "", "", self._status(), error

        overview = card(
            stat_grid(
                [
                    ("Words", transcript.word_count),
                    ("Segments", len(transcript.segments)),
                    ("Language", transcript.language or "unknown"),
                    ("Duration", format_timecode(transcript.duration, millis=False)
                     if hasattr(transcript, "duration") else media.timecode_label),
                ]
            ),
            title="Transcript",
        )
        return (
            transcript,
            transcript.text,
            overview,
            self._status(),
            banner(
                f"Transcribed {transcript.word_count} words.",
                level="success",
                title="Done",
            ),
        )

    def _highlights(
        self,
        transcript: Any,
        target_length: float,
        max_clips: float,
        focus: str,
        min_score: float,
    ) -> tuple[Any, str, str]:
        """Ask the model for the strongest moments."""
        ctx, error = self._require(transcript)
        if error:
            return [], "", error
        found, error = safe_call(
            ctx.ai.find_highlights,
            transcript,
            target_length=float(target_length),
            max_clips=int(max_clips),
            focus=str(focus),
            min_score=float(min_score),
        )
        if error:
            return [], "", error
        if not found:
            return [], card(
                empty_state(
                    "No highlights met that bar",
                    "Lower the minimum score, or try a different focus.",
                ),
                title="Highlights",
            ), ""
        rows = [
            (
                index,
                format_timecode(item.start, millis=False),
                format_timecode(item.end, millis=False),
                item.title,
                f"{item.score:.0%}",
                item.reason,
            )
            for index, item in enumerate(found, start=1)
        ]
        return found, card(
            table(["#", "From", "To", "Title", "Score", "Why"], rows, mono=(1, 2, 4)),
            title="Highlights",
            eyebrow=f"{len(found)} found",
        ), banner(
            f"Found {len(found)} highlight(s). Use the Split page's AI highlight mode to cut them.",
            level="success",
            title="Analysis complete",
        )

    def _render_highlights(
        self,
        media: Any,
        transcript: Any,
        highlights: Any,
        output_format: str,
        portrait_mode: str,
        add_subtitles: bool,
        progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection contract
    ) -> tuple[Any, str]:
        """Render AI highlights into a downloadable ZIP."""
        if self._ctx is None:
            return gr.update(value=None, interactive=False), banner("Not ready yet.", level="error")
        if media is None:
            return gr.update(value=None, interactive=False), banner(
                "Add a video first.", level="warning", title="Nothing selected"
            )
        if not highlights:
            return gr.update(value=None, interactive=False), banner(
                "Find highlights before rendering.", level="warning", title="No highlights"
            )
        if add_subtitles and transcript is None:
            return gr.update(value=None, interactive=False), banner(
                "Transcribe the video before rendering subtitled highlights.",
                level="warning",
                title="No transcript",
            )

        target = ensure_dir(
            self._ctx.paths.temp
            / "downloads"
            / f"{safe_filename(media.stem, fallback='highlights')}-ai-{int(time.time())}"
        )
        segments = [
            Segment(
                start=float(item.start),
                end=float(item.end),
                index=index,
                title=str(item.title),
                score=float(item.score),
                reason=str(getattr(item, "reason", "")),
            )
            for index, item in enumerate(highlights, start=1)
        ]
        plan = SplitPlan(
            source=media.path,
            mode=SplitMode.AI_HIGHLIGHT,
            segments=segments,
            parameters={"source": "ai_studio"},
        )

        def report(fraction: float, stage: str) -> None:
            progress(min(max(fraction, 0.0), 1.0), desc=stage)

        succeeded = False
        try:
            rendered, error = safe_call(
                self._ctx.split.render,
                plan,
                target / "raw",
                quality=Quality.BALANCED,
                output_format=str(output_format),
                portrait_mode=str(portrait_mode),
                on_progress=report,
            )
            if error or not rendered:
                return gr.update(value=None, interactive=False), error or banner(
                    "Nothing was written.", level="warning", title="Empty render"
                )

            cleanup_paths: list[Path] = list(rendered)
            if add_subtitles:
                final_paths: list[Path] = []
                caption_dir = ensure_dir(target / "captioned")
                for clip, segment in zip(rendered, segments, strict=False):
                    clip_media, probe_error = safe_call(self._ctx.media.import_file, clip)
                    if probe_error or clip_media is None:
                        return gr.update(value=None, interactive=False), probe_error
                    burned, burn_error = safe_call(
                        self._ctx.subtitles.burn,
                        clip_media,
                        transcript,
                        caption_dir / clip.name,
                        quality=Quality.BALANCED,
                        offset=float(segment.start),
                        on_progress=report,
                    )
                    if burn_error or burned is None:
                        return gr.update(value=None, interactive=False), burn_error or banner(
                            "Caption rendering failed before the ZIP could be prepared.",
                            level="error",
                            title="Subtitles failed",
                        )
                    final_paths.append(burned)
                    cleanup_paths.append(burned)
            else:
                final_paths = list(rendered)

            zip_path = self._ctx.split._zip_outputs(
                final_paths,
                final_paths[0].parent,
                stem=f"{media.stem}-highlights",
                output_format=str(output_format),
                portrait_mode=str(portrait_mode),
            )
            self._cleanup_clip_files(cleanup_paths)
            self._record_render(media, final_paths, zip_path, str(output_format), add_subtitles)
            succeeded = True
            caption_note = " with captions" if add_subtitles else ""
            detail = (
                f"Rendered {len(final_paths)} highlights{caption_note} and prepared "
                f"{zip_path.name} ({human_size(zip_path.stat().st_size)})."
            )
            return gr.update(value=str(zip_path), label="Download", interactive=True), banner(
                detail,
                level="success",
                title="Download ready",
            )
        finally:
            if not succeeded:
                shutil.rmtree(target, ignore_errors=True)

    def _remember_output_defaults(self, output_format: str, portrait_mode: str) -> None:
        """Remember AI Clips output choices alongside Make Clips choices."""
        if self._ctx is None:
            return
        self._ctx.settings.ui.split_output_format = str(output_format)
        self._ctx.settings.ui.split_portrait_mode = str(portrait_mode)
        with suppress(Exception):
            save_settings(self._ctx.settings, self._ctx.paths.config_file)

    def _record_render(
        self,
        media: Any,
        paths: list[Path],
        zip_path: Path,
        output_format: str,
        add_subtitles: bool,
    ) -> None:
        """Persist the latest AI render for the dashboard."""
        if self._ctx is None:
            return
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
        target = self._ctx.paths.cache / "last_render.json"
        try:
            ensure_dir(target.parent)
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _cleanup_clip_files(paths: list[Path]) -> None:
        """Remove temporary clips once their ZIP has been prepared."""
        parents = {path.parent for path in paths}
        for path in paths:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        for parent in parents:
            with suppress(OSError):
                shutil.rmtree(parent)

    def _hooks(self, transcript: Any) -> tuple[str, str]:
        """Find opening lines worth leading with."""
        ctx, error = self._require(transcript)
        if error:
            return "", error
        found, error = safe_call(ctx.ai.find_hooks, transcript)
        if error:
            return "", error
        if not found:
            return card(empty_state("No obvious hooks in this one"), title="Hooks"), ""
        rows = [
            (
                format_timecode(item.time, millis=False),
                item.text,
                f"{item.strength:.0%}",
                item.why,
            )
            for item in found
        ]
        return card(
            table(["At", "Line", "Strength", "Why"], rows, mono=(0, 2)), title="Hooks"
        ), ""

    def _titles(self, transcript: Any, count: float) -> tuple[str, str]:
        """Suggest titles for the whole piece."""
        ctx, error = self._require(transcript)
        if error:
            return "", error
        titles, error = safe_call(ctx.ai.suggest_titles, transcript.text, count=int(count))
        if error:
            return "", error
        if not titles:
            return card(empty_state("No titles came back"), title="Titles"), ""
        rows = [(index, title) for index, title in enumerate(titles, start=1)]
        return card(table(["#", "Title"], rows), title="Titles"), ""

    def _summary(self, transcript: Any) -> tuple[str, str]:
        """Summarise the transcript."""
        ctx, error = self._require(transcript)
        if error:
            return "", error
        summary, error = safe_call(ctx.ai.summarise, transcript)
        if error:
            return "", error
        if not summary:
            return card(empty_state("No summary came back"), title="Summary"), ""
        rows = [
            (str(key).replace("_", " ").title(), ", ".join(map(str, value))
             if isinstance(value, (list, tuple)) else str(value))
            for key, value in summary.items()
        ]
        return card(table(["Field", "Value"], rows), title="Summary"), ""

    def _chapters(self, transcript: Any, maximum: float) -> tuple[str, str]:
        """Propose chapter markers."""
        ctx, error = self._require(transcript)
        if error:
            return "", error
        chapters, error = safe_call(
            ctx.ai.suggest_chapters, transcript, max_chapters=int(maximum)
        )
        if error:
            return "", error
        if not chapters:
            return card(empty_state("No chapters proposed"), title="Chapters"), ""
        rows = [
            (format_timecode(item.time, millis=False), item.title) for item in chapters
        ]
        body = card(table(["At", "Chapter"], rows, mono=(0,)), title="Chapters")
        plain = "\n".join(f"{row[0]} {row[1]}" for row in rows)
        return body + card(
            f'<div class="dc-mono" data-dc-copy="{plain}">Click to copy as a description block</div>',
            tight=True,
        ), ""

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus every analysis action."""
        actions = [
            ("Transcribe", "dc-primary-ai_studio", "whisper words speech"),
            ("Find highlights", "dc-ai-highlights", "best moments clips"),
            ("Render highlights", "dc-ai-render-highlights", "export download zip"),
            ("Find hooks", "dc-ai-hooks", "opening lines"),
            ("Suggest titles", "dc-ai-titles", "naming"),
            ("Summarise", "dc-ai-summary", "abstract overview"),
            ("Suggest chapters", "dc-ai-chapters", "markers timestamps"),
            ("Stop AI work", "dc-ai-stop", "cancel abort"),
        ]
        return [
            *super().commands(),
            *[
                {"label": label, "group": "AI Studio", "target": target, "keywords": keywords}
                for label, target, keywords in actions
            ],
        ]
