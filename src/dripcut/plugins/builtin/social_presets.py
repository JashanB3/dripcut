"""Built-in plugin: extra caption presets tuned for social platforms."""

from __future__ import annotations

from dripcut.models.subtitle import CaptionStyle
from dripcut.plugins.api import Plugin, PluginContext, PluginMeta

__all__ = ["SocialPresetsPlugin"]


class SocialPresetsPlugin(Plugin):
    """Adds caption looks sized for vertical video."""

    meta = PluginMeta(
        id="social_presets",
        name="Social caption pack",
        version="1.0.0",
        description="Caption styles sized and positioned for vertical feeds.",
        author="DripCut",
        tags=("captions",),
    )

    def caption_styles(self, context: PluginContext) -> dict[str, CaptionStyle]:
        """Contribute three vertical-video caption presets."""
        return {
            "Vertical bold": CaptionStyle(
                name="Vertical bold",
                font_name="Helvetica",
                font_size=72,
                bold=True,
                uppercase=True,
                primary_color="#FFFFFF",
                outline_color="#000000",
                outline_width=6.0,
                margin_v=420,
                max_chars=18,
                max_lines=3,
            ),
            "Vertical plate": CaptionStyle(
                name="Vertical plate",
                font_name="Helvetica Neue",
                font_size=58,
                bold=True,
                primary_color="#FFFFFF",
                back_color="#111524",
                box_opacity=0.8,
                outline_width=0.0,
                margin_v=360,
                max_chars=22,
                max_lines=3,
            ),
            "Vertical mint": CaptionStyle(
                name="Vertical mint",
                font_name="Avenir Next",
                font_size=64,
                bold=True,
                uppercase=True,
                primary_color="#7DF9D5",
                outline_color="#04121A",
                outline_width=5.0,
                margin_v=400,
                max_chars=18,
                max_lines=3,
                letter_spacing=0.8,
            ),
        }
