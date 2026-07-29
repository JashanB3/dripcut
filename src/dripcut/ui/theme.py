"""DripCut's visual identity.

Direction: a colour-grading suite at 2am. Deep blue-black panels, one cool
indigo-to-violet accent used sparingly, and mint reserved exclusively for
"something finished". The signature is typographic: every time value in the app is
set in a monospaced face with tabular figures, so numbers line up column-wise down
a list of clips the way they do on a timeline ruler.

Only system faces are used - the app must look identical with the network off, and
downloading a webfont on first launch would break that promise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["Palette", "DARK", "LIGHT", "build_theme", "load_css", "load_js", "css_variables"]


@dataclass(frozen=True, slots=True)
class Palette:
    """A complete set of surface, text and accent colours."""

    name: str
    base: str
    surface: str
    elevated: str
    line: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_2: str
    mint: str
    amber: str
    coral: str
    shadow: str

    def to_css(self) -> str:
        """Render as CSS custom properties."""
        return "\n".join(
            f"  --dc-{key.replace('_', '-')}: {value};"
            for key, value in {
                "base": self.base,
                "surface": self.surface,
                "elevated": self.elevated,
                "line": self.line,
                "text": self.text,
                "muted": self.muted,
                "faint": self.faint,
                "accent": self.accent,
                "accent-2": self.accent_2,
                "mint": self.mint,
                "amber": self.amber,
                "coral": self.coral,
                "shadow": self.shadow,
            }.items()
        )


DARK = Palette(
    name="dark",
    base="#0B0E17",
    surface="#131829",
    elevated="#1A2036",
    line="#26304C",
    text="#E8ECF7",
    muted="#94A0BE",
    faint="#5E6A88",
    accent="#5B8CFF",
    accent_2="#A06BFF",
    mint="#45E0B0",
    amber="#FFC24B",
    coral="#FF6B6B",
    shadow="rgba(4, 7, 16, 0.55)",
)

LIGHT = Palette(
    name="light",
    base="#EEF1F8",
    surface="#FFFFFF",
    elevated="#F6F8FD",
    line="#D8DFEE",
    text="#141A2B",
    muted="#5A6683",
    faint="#8B96B0",
    accent="#3C6BE8",
    accent_2="#8046E0",
    mint="#12A87C",
    amber="#B7761A",
    coral="#D2453F",
    shadow="rgba(20, 26, 43, 0.12)",
)


def css_variables() -> str:
    """Both palettes as CSS, switched by a ``data-theme`` attribute on the root."""
    return (
        f":root, .dripcut[data-theme='dark'] {{\n{DARK.to_css()}\n}}\n\n"
        f".dripcut[data-theme='light'] {{\n{LIGHT.to_css()}\n}}\n"
    )


def build_theme(mode: str = "dark") -> Any:
    """Build the Gradio theme object that matches the CSS palette.

    Gradio paints some chrome before our stylesheet applies, so the theme carries the
    same colours to prevent a white flash on load.
    """
    import gradio as gr  # noqa: PLC0415 - keeps the module importable without Gradio

    palette = DARK if mode == "dark" else LIGHT
    return gr.themes.Base(
        primary_hue=gr.themes.colors.indigo,
        secondary_hue=gr.themes.colors.violet,
        neutral_hue=gr.themes.colors.slate,
        font=[
            # Local faces only - DripCut never fetches a webfont.
            "system-ui",
            "-apple-system",
            "BlinkMacSystemFont",
            "Segoe UI",
            "sans-serif",
        ],
        font_mono=["ui-monospace", "SFMono-Regular", "SF Mono", "JetBrains Mono", "monospace"],
    ).set(
        body_background_fill=palette.base,
        body_text_color=palette.text,
        background_fill_primary=palette.surface,
        background_fill_secondary=palette.elevated,
        border_color_primary=palette.line,
        block_background_fill=palette.surface,
        block_border_color=palette.line,
        block_label_text_color=palette.muted,
        block_title_text_color=palette.text,
        input_background_fill=palette.elevated,
        input_border_color=palette.line,
        button_primary_background_fill=palette.accent,
        button_primary_text_color="#FFFFFF",
        button_secondary_background_fill=palette.elevated,
        button_secondary_text_color=palette.text,
        color_accent_soft=palette.elevated,
    )


def _asset(name: str) -> Path:
    """Absolute path to a bundled asset."""
    return Path(__file__).resolve().parent / "assets" / name


def load_css() -> str:
    """Palette variables plus the application stylesheet."""
    stylesheet = _asset("styles.css")
    body = stylesheet.read_text(encoding="utf-8") if stylesheet.exists() else ""
    return f"{css_variables()}\n{body}"


def load_js() -> str:
    """The client-side helper script (command palette, shortcuts, theme)."""
    script = _asset("app.js")
    return script.read_text(encoding="utf-8") if script.exists() else ""
