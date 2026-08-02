"""Simple product settings."""

from __future__ import annotations

from typing import Any

import gradio as gr

from dripcut.core.config import load_settings, reset_settings, save_settings
from dripcut.ui.components.widgets import banner, card, table
from dripcut.ui.pages.base import Page, PageContext, safe_call

__all__ = ["SettingsPage"]

_PAGE_LABELS = {
    "dashboard": "Home",
    "workspace": "Edit Tools",
    "split": "Make Clips",
    "ai_studio": "AI Clips",
    "subtitles": "Captions",
    "batch": "Bulk Edit",
    "exports": "Downloads",
    "projects": "My Edits",
    "settings": "Preferences",
}


class SettingsPage(Page):
    """Small set of preferences users actually need."""

    key = "settings"
    label = "Preferences"
    icon = "\u2699"
    group = "Account"
    title = "Preferences"
    subtitle = "Choose the default look and clip format that fit your workflow."

    def __init__(self) -> None:
        self._ctx: PageContext | None = None

    def build(self, ctx: PageContext, *, visible: bool) -> gr.Column:
        """Compose the simplified settings form."""
        self._ctx = ctx
        settings = ctx.settings
        with gr.Column(visible=visible, elem_classes=["dc-page"]) as column:
            message = gr.HTML()
            with gr.Row():
                with gr.Column(scale=2):
                    theme = gr.Radio(["light", "dark"], value=settings.ui.theme, label="Theme")
                    default_page = gr.Dropdown(
                        [
                            ("Home", "dashboard"),
                            ("Edit Tools", "workspace"),
                            ("Make Clips", "split"),
                            ("AI Clips", "ai_studio"),
                            ("Captions", "subtitles"),
                            ("Bulk Edit", "batch"),
                            ("Downloads", "exports"),
                            ("My Edits", "projects"),
                            ("Preferences", "settings"),
                        ],
                        value=settings.ui.default_page,
                        label="Open this page first",
                    )
                with gr.Column(scale=2):
                    split_output_format = gr.Dropdown(
                        [("Landscape", "landscape"), ("Portrait", "portrait"), ("Square", "square")],
                        value=settings.ui.split_output_format,
                        label="Default output format",
                    )
                    split_portrait_mode = gr.Dropdown(
                        [
                            ("AI Tracking", "ai_tracking"),
                            ("Center Crop", "center_crop"),
                            ("Blur Background", "blur_background"),
                        ],
                        value=settings.ui.split_portrait_mode,
                        label="Portrait mode",
                    )

            with gr.Row():
                save = gr.Button(
                    "Save",
                    variant="primary",
                    elem_classes=["dc-btn", "dc-btn-primary"],
                    elem_id="dc-primary-settings",
                )
                reload_button = gr.Button(
                    "Reload", elem_classes=["dc-btn"], elem_id="dc-settings-reload"
                )
                confirm_reset = gr.Checkbox(value=False, label="Restore defaults")
                reset = gr.Button(
                    "Reset",
                    elem_classes=["dc-btn", "dc-btn-danger"],
                    elem_id="dc-settings-reset",
                )

            current = gr.HTML(self._current())
            self._fields = [theme, default_page, split_output_format, split_portrait_mode]

            save.click(self._save, inputs=self._fields, outputs=[current, message])
            theme.change(
                lambda value: value,
                inputs=theme,
                outputs=theme,
                js="(value)=>{const root=document.querySelector('.dripcut')||document.body;if(root){root.classList.add('dripcut');root.setAttribute('data-theme',value);}return value;}",
            )
            reload_button.click(self._reload, outputs=[*self._fields, current, message])
            reset.click(
                self._reset, inputs=confirm_reset, outputs=[*self._fields, current, message]
            )
        return column

    # ----------------------------------------------------------------- panels

    def _current(self) -> str:
        """A short summary of current preferences."""
        if self._ctx is None:
            return ""
        settings = self._ctx.settings
        rows = [
            ("Theme", settings.ui.theme.title()),
            ("Start page", _page_label(settings.ui.default_page)),
            ("Output format", settings.ui.split_output_format.title()),
            ("Portrait mode", settings.ui.split_portrait_mode.replace("_", " ").title()),
        ]
        return card(table(["Preference", "Value"], rows), title="Current preferences")

    def _values(self) -> list[Any]:
        settings = self._ctx.settings if self._ctx else None
        if settings is None:
            return []
        return [
            settings.ui.theme,
            settings.ui.default_page,
            settings.ui.split_output_format,
            settings.ui.split_portrait_mode,
        ]

    # ---------------------------------------------------------------- actions

    def _save(self, *values: Any) -> tuple[str, str]:
        """Apply and persist the visible preferences."""
        if self._ctx is None:
            return "", banner("Not ready yet.", level="error")
        theme, default_page, split_output_format, split_portrait_mode = values
        settings = self._ctx.settings
        settings.ui.theme = str(theme)
        settings.ui.default_page = str(default_page)
        settings.ui.split_output_format = str(split_output_format)
        settings.ui.split_portrait_mode = str(split_portrait_mode)

        _, error = safe_call(save_settings, settings, self._ctx.paths.config_file)
        if error:
            return self._current(), error
        return self._current(), banner(
            "Saved. Theme changes are applied from the header toggle immediately; page defaults apply on restart.",
            level="success",
            title="Settings saved",
        )

    def _reload(self) -> tuple[Any, ...]:
        """Discard visible edits and re-read settings."""
        if self._ctx is None:
            return *[gr.skip() for _ in self._fields], "", banner("Not ready yet.", level="error")
        fresh, error = safe_call(load_settings, self._ctx.paths.config_file)
        if error or fresh is None:
            return *[gr.skip() for _ in self._fields], self._current(), error
        self._apply(fresh)
        return *self._values(), self._current(), banner(
            "Reloaded preferences.", level="info", title="Settings"
        )

    def _reset(self, confirmed: bool) -> tuple[Any, ...]:
        """Restore defaults after confirmation."""
        if self._ctx is None:
            return *[gr.skip() for _ in self._fields], "", banner("Not ready yet.", level="error")
        if not confirmed:
            return (
                *[gr.skip() for _ in self._fields],
                self._current(),
                banner("Tick Restore defaults first.", level="warning", title="Confirm reset"),
            )
        fresh, error = safe_call(reset_settings, self._ctx.paths.config_file)
        if error or fresh is None:
            return *[gr.skip() for _ in self._fields], self._current(), error
        self._apply(fresh)
        return *self._values(), self._current(), banner(
            "Default preferences restored.", level="success", title="Reset"
        )

    def _apply(self, fresh: Any) -> None:
        """Copy a loaded Settings object onto the live settings instance."""
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
        """Navigation plus settings actions."""
        return [
            *super().commands(),
            {
                "label": "Save settings",
                "group": "Settings",
                "target": "dc-primary-settings",
                "keywords": "apply preferences theme output",
            },
            {
                "label": "Reload settings",
                "group": "Settings",
                "target": "dc-settings-reload",
                "keywords": "revert discard",
            },
        ]


def _page_label(key: str) -> str:
    """Human label for an internal page key."""
    return _PAGE_LABELS.get(str(key), str(key).replace("_", " ").title())
