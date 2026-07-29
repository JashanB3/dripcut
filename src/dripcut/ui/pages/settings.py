"""Settings: everything in settings.json, with the reasoning attached.

Each control maps to exactly one field on :class:`~dripcut.core.config.Settings`.
Saving validates first and writes atomically, so a bad value never lands on disk;
changes that only take effect on restart say so rather than pretending otherwise.
"""

from __future__ import annotations

from typing import Any

import gradio as gr

from dripcut.core.config import load_settings, reset_settings, save_settings
from dripcut.ui.components.widgets import banner, card, table
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["SettingsPage"]

_WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
_COMPUTE_TYPES = ["int8", "int8_float16", "float16", "float32"]
_DEVICES = ["auto", "cpu", "cuda"]
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
_PRESETS = ["ultrafast", "veryfast", "fast", "medium", "slow", "slower"]

# Restarting is only needed where the value is read once, at construction time.
_RESTART_FIELDS = "server host and port, worker count, and the Ollama host"


class SettingsPage(Page):
    """Read, change and reset the application configuration."""

    key = "settings"
    label = "Settings"
    icon = "\u2699"
    group = "System"
    title = "Settings"
    subtitle = "Stored as plain JSON. Editing the file by hand works just as well."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the settings form."""
        self._ctx = ctx
        settings = ctx.settings
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()

            with gr.Tabs():
                with gr.Tab("General"):
                    output_dir = gr.Textbox(
                        value=str(settings.output_path), label="Output folder"
                    )
                    with gr.Row():
                        ffmpeg_path = gr.Textbox(value=settings.ffmpeg_path, label="FFmpeg path")
                        ffprobe_path = gr.Textbox(
                            value=settings.ffprobe_path, label="FFprobe path"
                        )
                    log_level = gr.Dropdown(
                        _LOG_LEVELS, value=settings.log_level, label="Console log level"
                    )

                with gr.Tab("Appearance"):
                    theme = gr.Radio(
                        ["dark", "light"], value=settings.ui.theme, label="Theme"
                    )
                    default_page = gr.Dropdown(
                        [
                            "dashboard", "workspace", "split", "ai_studio", "subtitles",
                            "batch", "exports", "projects", "plugins", "settings",
                        ],
                        value=settings.ui.default_page,
                        label="Page to open on start",
                    )
                    reduce_motion = gr.Checkbox(
                        value=settings.ui.reduce_motion,
                        label="Reduce motion (the system preference is honoured regardless)",
                    )
                    show_status_bar = gr.Checkbox(
                        value=settings.ui.show_status_bar, label="Show the status bar"
                    )
                    recent_limit = gr.Slider(
                        4, 40, value=settings.ui.recent_limit, step=1, label="Recent items to keep"
                    )

                with gr.Tab("Video"):
                    hardware_accel = gr.Checkbox(
                        value=settings.video.hardware_accel,
                        label="Use hardware encoding (VideoToolbox on Apple Silicon)",
                    )
                    with gr.Row():
                        crf = gr.Slider(
                            12, 34, value=settings.video.crf, step=1,
                            label="Default CRF (lower is better quality)",
                        )
                        preset = gr.Dropdown(
                            _PRESETS, value=settings.video.preset, label="Encoder preset"
                        )
                    with gr.Row():
                        max_workers = gr.Slider(
                            1, 6, value=settings.video.max_workers, step=1,
                            label="Parallel jobs (2 suits 8 GB of memory)",
                        )
                        proxy_height = gr.Slider(
                            240, 1080, value=settings.video.proxy_height, step=60,
                            label="Proxy height",
                        )
                    prefer_stream_copy = gr.Checkbox(
                        value=settings.video.prefer_stream_copy,
                        label="Prefer stream copy when the cut allows it",
                    )
                    with gr.Row():
                        scene_threshold = gr.Slider(
                            5, 60, value=settings.video.scene_threshold, step=1,
                            label="Scene sensitivity",
                        )
                        silence_threshold_db = gr.Slider(
                            -60, -10, value=settings.video.silence_threshold_db, step=1,
                            label="Silence level (dB)",
                        )
                        silence_min_duration = gr.Slider(
                            0.1, 3.0, value=settings.video.silence_min_duration, step=0.1,
                            label="Shortest pause to cut on (s)",
                        )

                with gr.Tab("AI"):
                    enable_ai = gr.Checkbox(
                        value=settings.ai.enable_ai,
                        label="Enable AI features (everything else works without them)",
                    )
                    with gr.Row():
                        whisper_model = gr.Dropdown(
                            _WHISPER_MODELS, value=settings.ai.whisper_model, label="Whisper model"
                        )
                        whisper_compute_type = gr.Dropdown(
                            _COMPUTE_TYPES,
                            value=settings.ai.whisper_compute_type,
                            label="Compute type",
                        )
                        whisper_device = gr.Dropdown(
                            _DEVICES, value=settings.ai.whisper_device, label="Device"
                        )
                    with gr.Row():
                        whisper_beam_size = gr.Slider(
                            1, 5, value=settings.ai.whisper_beam_size, step=1, label="Beam size"
                        )
                        whisper_language = gr.Textbox(
                            value=settings.ai.whisper_language,
                            label="Force a language (blank = detect)",
                        )
                        whisper_vad_filter = gr.Checkbox(
                            value=settings.ai.whisper_vad_filter, label="Skip silence (VAD)"
                        )
                    with gr.Row():
                        ollama_host = gr.Textbox(
                            value=settings.ai.ollama_host, label="Ollama host"
                        )
                        ollama_model = gr.Textbox(
                            value=settings.ai.ollama_model, label="Ollama model"
                        )
                    with gr.Row():
                        ollama_temperature = gr.Slider(
                            0.0, 1.0, value=settings.ai.ollama_temperature, step=0.05,
                            label="Temperature",
                        )
                        ollama_num_ctx = gr.Slider(
                            1024, 16384, value=settings.ai.ollama_num_ctx, step=512,
                            label="Context window",
                        )
                        ollama_timeout_s = gr.Slider(
                            30, 600, value=settings.ai.ollama_timeout_s, step=10,
                            label="Timeout (s)",
                        )
                    auto_start_ollama = gr.Checkbox(
                        value=settings.ai.auto_start_ollama,
                        label="Start Ollama automatically when needed",
                    )

                with gr.Tab("Server"):
                    with gr.Row():
                        host = gr.Textbox(value=settings.server.host, label="Bind address")
                        port = gr.Number(value=settings.server.port, label="Port", precision=0)
                    open_browser = gr.Checkbox(
                        value=settings.server.open_browser, label="Open a browser on start"
                    )
                    max_upload_mb = gr.Slider(
                        256, 16384, value=settings.server.max_upload_mb, step=256,
                        label="Maximum upload size (MB)",
                    )
                    gr.HTML(
                        banner(
                            "Sharing is permanently off and telemetry does not exist. "
                            "DripCut binds to localhost and speaks to nothing but Ollama.",
                            level="info",
                            title="Privacy",
                        )
                    )

            with gr.Row():
                save = gr.Button(
                    "Save settings",
                    variant="primary",
                    elem_classes=["dc-btn", "dc-btn-primary"],
                    elem_id="dc-primary-settings",
                )
                reload_button = gr.Button(
                    "Reload from disk", elem_classes=["dc-btn"], elem_id="dc-settings-reload"
                )
                confirm_reset = gr.Checkbox(value=False, label="Yes, restore defaults")
                reset = gr.Button(
                    "Reset to defaults",
                    elem_classes=["dc-btn", "dc-btn-danger"],
                    elem_id="dc-settings-reset",
                )

            current = gr.HTML(self._current())

            self._fields = [
                output_dir, ffmpeg_path, ffprobe_path, log_level,
                theme, default_page, reduce_motion, show_status_bar, recent_limit,
                hardware_accel, crf, preset, max_workers, proxy_height, prefer_stream_copy,
                scene_threshold, silence_threshold_db, silence_min_duration,
                enable_ai, whisper_model, whisper_compute_type, whisper_device,
                whisper_beam_size, whisper_language, whisper_vad_filter,
                ollama_host, ollama_model, ollama_temperature, ollama_num_ctx,
                ollama_timeout_s, auto_start_ollama,
                host, port, open_browser, max_upload_mb,
            ]

            save.click(self._save, inputs=self._fields, outputs=[current, message])
            reload_button.click(self._reload, outputs=[*self._fields, current, message])
            reset.click(
                self._reset, inputs=confirm_reset, outputs=[*self._fields, current, message]
            )
        return column

    # ----------------------------------------------------------------- panels

    def _current(self) -> str:
        """A table of the values actually in memory right now."""
        if self._ctx is None:
            return ""
        settings = self._ctx.settings
        rows = [
            ("Config file", str(self._ctx.paths.config_file)),
            ("Output", str(settings.output_path)),
            ("Theme", settings.ui.theme),
            ("Server", f"{settings.server.host}:{settings.server.port}"),
            ("Workers", settings.video.max_workers),
            ("Hardware encoding", "on" if settings.video.hardware_accel else "off"),
            ("AI", "on" if settings.ai.enable_ai else "off"),
            ("Whisper", settings.ai.whisper_model),
            ("Ollama", f"{settings.ai.ollama_model} @ {settings.ai.ollama_host}"),
            ("Log level", settings.log_level),
            ("Disabled plugins", ", ".join(settings.disabled_plugins) or "none"),
        ]
        return card(table(["Setting", "Value"], rows), title="In effect now")

    def _values(self) -> list[Any]:
        """Current settings as a list matching ``self._fields`` order."""
        settings = self._ctx.settings if self._ctx else None
        if settings is None:
            return []
        return [
            str(settings.output_path), settings.ffmpeg_path, settings.ffprobe_path,
            settings.log_level,
            settings.ui.theme, settings.ui.default_page, settings.ui.reduce_motion,
            settings.ui.show_status_bar, settings.ui.recent_limit,
            settings.video.hardware_accel, settings.video.crf, settings.video.preset,
            settings.video.max_workers, settings.video.proxy_height,
            settings.video.prefer_stream_copy, settings.video.scene_threshold,
            settings.video.silence_threshold_db, settings.video.silence_min_duration,
            settings.ai.enable_ai, settings.ai.whisper_model, settings.ai.whisper_compute_type,
            settings.ai.whisper_device, settings.ai.whisper_beam_size,
            settings.ai.whisper_language, settings.ai.whisper_vad_filter,
            settings.ai.ollama_host, settings.ai.ollama_model, settings.ai.ollama_temperature,
            settings.ai.ollama_num_ctx, settings.ai.ollama_timeout_s,
            settings.ai.auto_start_ollama,
            settings.server.host, settings.server.port, settings.server.open_browser,
            settings.server.max_upload_mb,
        ]

    # ---------------------------------------------------------------- actions

    def _save(self, *values: Any) -> tuple[str, str]:
        """Apply the form to the live settings, validate, then write to disk."""
        if self._ctx is None:
            return "", banner("Not ready yet.", level="error")
        settings = self._ctx.settings
        (
            output_dir, ffmpeg_path, ffprobe_path, log_level,
            theme, default_page, reduce_motion, show_status_bar, recent_limit,
            hardware_accel, crf, preset, max_workers, proxy_height, prefer_stream_copy,
            scene_threshold, silence_threshold_db, silence_min_duration,
            enable_ai, whisper_model, whisper_compute_type, whisper_device,
            whisper_beam_size, whisper_language, whisper_vad_filter,
            ollama_host, ollama_model, ollama_temperature, ollama_num_ctx,
            ollama_timeout_s, auto_start_ollama,
            host, port, open_browser, max_upload_mb,
        ) = values

        settings.output_dir = str(output_dir).strip() or settings.output_dir
        settings.ffmpeg_path = str(ffmpeg_path).strip() or "ffmpeg"
        settings.ffprobe_path = str(ffprobe_path).strip() or "ffprobe"
        settings.log_level = str(log_level)

        settings.ui.theme = str(theme)
        settings.ui.default_page = str(default_page)
        settings.ui.reduce_motion = bool(reduce_motion)
        settings.ui.show_status_bar = bool(show_status_bar)
        settings.ui.recent_limit = int(recent_limit)

        settings.video.hardware_accel = bool(hardware_accel)
        settings.video.crf = int(crf)
        settings.video.preset = str(preset)
        settings.video.max_workers = int(max_workers)
        settings.video.proxy_height = int(proxy_height)
        settings.video.prefer_stream_copy = bool(prefer_stream_copy)
        settings.video.scene_threshold = float(scene_threshold)
        settings.video.silence_threshold_db = float(silence_threshold_db)
        settings.video.silence_min_duration = float(silence_min_duration)

        settings.ai.enable_ai = bool(enable_ai)
        settings.ai.whisper_model = str(whisper_model)
        settings.ai.whisper_compute_type = str(whisper_compute_type)
        settings.ai.whisper_device = str(whisper_device)
        settings.ai.whisper_beam_size = int(whisper_beam_size)
        settings.ai.whisper_language = str(whisper_language).strip()
        settings.ai.whisper_vad_filter = bool(whisper_vad_filter)
        settings.ai.ollama_host = str(ollama_host).strip()
        settings.ai.ollama_model = str(ollama_model).strip()
        settings.ai.ollama_temperature = float(ollama_temperature)
        settings.ai.ollama_num_ctx = int(ollama_num_ctx)
        settings.ai.ollama_timeout_s = int(ollama_timeout_s)
        settings.ai.auto_start_ollama = bool(auto_start_ollama)

        settings.server.host = str(host).strip() or "127.0.0.1"
        settings.server.port = int(port)
        settings.server.open_browser = bool(open_browser)
        settings.server.max_upload_mb = int(max_upload_mb)

        written, error = safe_call(save_settings, settings, self._ctx.paths.config_file)
        if error:
            return self._current(), error
        return self._current(), banner(
            f"Saved to {written}. Changes to {_RESTART_FIELDS} take effect after a restart; "
            "everything else applies immediately.",
            level="success",
            title="Settings saved",
        )

    def _reload(self) -> tuple[Any, ...]:
        """Discard in-memory edits and re-read the file."""
        if self._ctx is None:
            return *[gr.skip() for _ in self._fields], "", banner("Not ready yet.", level="error")
        fresh, error = safe_call(load_settings, self._ctx.paths.config_file)
        if error or fresh is None:
            return *[gr.skip() for _ in self._fields], self._current(), error
        self._apply(fresh)
        return *self._values(), self._current(), banner(
            "Reloaded from disk.", level="info", title="Settings"
        )

    def _reset(self, confirmed: bool) -> tuple[Any, ...]:
        """Restore factory defaults, once confirmed."""
        if self._ctx is None:
            return *[gr.skip() for _ in self._fields], "", banner("Not ready yet.", level="error")
        if not confirmed:
            return (
                *[gr.skip() for _ in self._fields],
                self._current(),
                banner(
                    "Tick the confirmation box to restore defaults.",
                    level="warning",
                    title="Confirm first",
                ),
            )
        fresh, error = safe_call(reset_settings, self._ctx.paths.config_file)
        if error or fresh is None:
            return *[gr.skip() for _ in self._fields], self._current(), error
        self._apply(fresh)
        return *self._values(), self._current(), banner(
            "Settings restored to defaults. Restart to pick up server changes.",
            level="success",
            title="Reset",
        )

    def _apply(self, fresh: Any) -> None:
        """Copy a freshly loaded Settings onto the live instance.

        The container handed the same object to every service, so it is mutated in
        place rather than replaced -- swapping the reference would leave services
        holding the old one.
        """
        live = self._ctx.settings if self._ctx else None
        if live is None:
            return
        for section in ("server", "ai", "video", "ui"):
            source, target = getattr(fresh, section), getattr(live, section)
            for field in target.__slots__:
                setattr(target, field, getattr(source, field))
        for field in ("output_dir", "ffmpeg_path", "ffprobe_path", "log_level", "telemetry"):
            setattr(live, field, getattr(fresh, field))
        live.enabled_plugins = list(fresh.enabled_plugins)
        live.disabled_plugins = list(fresh.disabled_plugins)

    def commands(self) -> list[dict[str, str]]:
        """Navigation plus the save and reset actions."""
        return [
            *super().commands(),
            {
                "label": "Save settings",
                "group": "Settings",
                "target": "dc-primary-settings",
                "keywords": "apply write config",
            },
            {
                "label": "Reload settings from disk",
                "group": "Settings",
                "target": "dc-settings-reload",
                "keywords": "revert discard",
            },
        ]
