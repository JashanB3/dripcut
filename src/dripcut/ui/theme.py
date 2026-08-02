"""DripCut's visual identity.

Direction: a Canva-grade creator studio. White paper surfaces, a violet-to-cyan
brand gradient, generous corner radii, colourful round tool tiles and calm ink
type. The palette is deliberately close to the design language people already
know from Canva, because DripCut asks the same thing of them: pick a starting
point, drop in a file, get something postable.

Only local/system faces are used so the app still launches with no network.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "Palette",
    "DARK",
    "LIGHT",
    "build_theme",
    "brand_mark_uri",
    "load_css",
    "load_js",
    "css_variables",
]


@dataclass(frozen=True, slots=True)
class Palette:
    """A complete set of surface, text and accent colours.

    The field names are the published contract: ``styles.css`` reads each one as
    ``--dc-<name>``, so renaming a field here renames a variable everywhere.
    """

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
    # Canva-grade additions -------------------------------------------------
    accent_soft: str = "#F3EBFF"
    accent_ink: str = "#6017C4"
    rail: str = "#FFFFFF"
    hover: str = "#F2F3F5"
    brand_gradient: str = (
        "linear-gradient(135deg, #160D33 0%, #2A0A66 26%, #6F1DB5 62%, #BA2CDE 100%)"
    )
    hero_wash: str = (
        "radial-gradient(1180px 560px at 12% -10%, #E9DDFF 0%, rgba(233, 221, 255, 0) 62%),"
        " radial-gradient(980px 520px at 88% -6%, #D6F4F7 0%, rgba(214, 244, 247, 0) 60%),"
        " radial-gradient(900px 620px at 60% 108%, #FFE8F3 0%, rgba(255, 232, 243, 0) 64%)"
    )
    ring: str = "rgba(139, 61, 255, 0.28)"

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
                "accent-soft": self.accent_soft,
                "accent-ink": self.accent_ink,
                "rail": self.rail,
                "hover": self.hover,
                "brand-gradient": self.brand_gradient,
                "hero-wash": self.hero_wash,
                "ring": self.ring,
            }.items()
        )


LIGHT = Palette(
    name="light",
    base="#FFFFFF",
    surface="#FFFFFF",
    elevated="#F2F3F5",
    line="#E3E5E9",
    text="#0E1318",
    muted="#575E6B",
    faint="#8B94A3",
    accent="#7A1FD1",
    accent_2="#BA2CDE",
    mint="#00B894",
    amber="#FFB020",
    coral="#FF4D6D",
    shadow="rgba(22, 13, 51, 0.14)",
    accent_soft="#F4E9FF",
    accent_ink="#5A12A8",
    rail="#FFFFFF",
    hover="#F2F3F5",
    hero_wash=(
        "radial-gradient(1100px 520px at 6% -20%, #E3D2FF 0%, rgba(227, 210, 255, 0) 60%),"
        " radial-gradient(900px 480px at 94% -14%, #F6D8FB 0%, rgba(246, 216, 251, 0) 58%),"
        " radial-gradient(820px 540px at 54% 120%, #EFE4FF 0%, rgba(239, 228, 255, 0) 62%)"
    ),
    ring="rgba(122, 31, 209, 0.26)",
)

DARK = Palette(
    name="dark",
    base="#0B0716",
    surface="#150E26",
    elevated="#1E1533",
    line="#2E2247",
    text="#F4F0FA",
    muted="#B3A8C7",
    faint="#857A9B",
    accent="#A45CF0",
    accent_2="#D95BEC",
    mint="#2DD4A7",
    amber="#FFC64D",
    coral="#FF7A93",
    shadow="rgba(0, 0, 0, 0.52)",
    accent_soft="#2A1747",
    accent_ink="#D0A6FF",
    rail="#120C22",
    hover="#221836",
    brand_gradient=(
        "linear-gradient(135deg, #160D33 0%, #2A0A66 26%, #6F1DB5 62%, #BA2CDE 100%)"
    ),
    hero_wash=(
        "radial-gradient(1180px 560px at 10% -14%, rgba(111, 29, 181, 0.42) 0%,"
        " rgba(111, 29, 181, 0) 62%),"
        " radial-gradient(980px 520px at 90% -8%, rgba(186, 44, 222, 0.28) 0%,"
        " rgba(186, 44, 222, 0) 60%),"
        " radial-gradient(900px 620px at 58% 112%, rgba(42, 10, 102, 0.5) 0%,"
        " rgba(42, 10, 102, 0) 64%)"
    ),
    ring="rgba(164, 92, 240, 0.36)",
)


@lru_cache(maxsize=1)
def brand_mark_uri() -> str:
    """The DripCut mark as a data URI.

    Inlined rather than served so the mark paints on first frame, survives a
    Gradio version changing where static files live, and needs no allowed-paths
    entry. It is published once as a CSS variable and referenced from there, so
    the bytes appear in the payload a single time however many places use it.
    """
    mark = _asset("logo-mark.png")
    if not mark.exists():
        return ""
    encoded = base64.b64encode(mark.read_bytes()).decode("ascii")
    return f"url('data:image/png;base64,{encoded}')"


def css_variables() -> str:
    """Both palettes as CSS, switched by a ``data-theme`` attribute on the root.

    Light is the default because that is what a first-run visitor sees before
    any preference has been saved, and it is the mode the product is designed in.
    """
    shared = (
        "  --dc-radius-xs: 8px;\n"
        "  --dc-radius-sm: 12px;\n"
        "  --dc-radius: 16px;\n"
        "  --dc-radius-lg: 24px;\n"
        "  --dc-radius-xl: 32px;\n"
        "  --dc-pill: 999px;\n"
        "  --dc-lift-1: 0 1px 2px rgba(14, 19, 24, 0.06), 0 2px 8px rgba(14, 19, 24, 0.06);\n"
        "  --dc-lift-2: 0 2px 6px rgba(14, 19, 24, 0.08), 0 12px 28px rgba(14, 19, 24, 0.10);\n"
        "  --dc-lift-3: 0 8px 20px rgba(14, 19, 24, 0.10), 0 28px 60px rgba(14, 19, 24, 0.16);\n"
        "  --dc-ease: cubic-bezier(0.22, 0.61, 0.36, 1);\n"
        "  --dc-tile-1: linear-gradient(135deg, #8A21DD, #5A12A8);\n"
        "  --dc-tile-2: linear-gradient(135deg, #BA2CDE, #7A1FD1);\n"
        "  --dc-tile-3: linear-gradient(135deg, #E2489B, #A5197E);\n"
        "  --dc-tile-4: linear-gradient(135deg, #6C4BFF, #3A1C9E);\n"
        "  --dc-tile-5: linear-gradient(135deg, #2A0A66, #160D33);\n"
        "  --dc-tile-6: linear-gradient(135deg, #00B894, #04846C);\n"
        "  --dc-tile-7: linear-gradient(135deg, #FFB020, #E06A12);\n"
        "  --dc-tile-8: linear-gradient(135deg, #4B5AE0, #2A2F8F);\n"
    )
    mark = brand_mark_uri()
    if mark:
        shared += f"  --dc-logo: {mark};\n"
    return (
        f":root, .dripcut[data-theme='light'] {{\n{shared}{LIGHT.to_css()}\n}}\n\n"
        f".dripcut[data-theme='dark'] {{\n{DARK.to_css()}\n}}\n"
    )


def build_theme(mode: str = "light") -> Any:
    """Build the Gradio theme object that matches the CSS palette.

    Gradio paints some chrome before our stylesheet applies, so the theme carries
    the same colours to prevent a flash of the wrong skin on load.
    """
    import gradio as gr  # noqa: PLC0415 - keeps the module importable without Gradio

    palette = DARK if mode == "dark" else LIGHT
    return gr.themes.Base(
        primary_hue=gr.themes.colors.purple,
        secondary_hue=gr.themes.colors.cyan,
        neutral_hue=gr.themes.colors.slate,
        font=[
            "Canva Sans",
            "Inter",
            "Avenir Next",
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
        input_background_fill=palette.surface,
        input_border_color=palette.line,
        button_primary_background_fill=palette.accent,
        button_primary_text_color="#FFFFFF",
        button_secondary_background_fill=palette.elevated,
        button_secondary_text_color=palette.text,
        color_accent_soft=palette.accent_soft,
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
