"""Built-in plugin: contact sheet generator.

Demonstrates the smallest useful plugin - one tool action that calls the video
engine and writes a file.
"""

from __future__ import annotations

from pathlib import Path

from dripcut.models.media import MediaInfo
from dripcut.plugins.api import Plugin, PluginContext, PluginMeta, ToolAction
from dripcut.utils.fs import ensure_dir

__all__ = ["ThumbnailGridPlugin"]


class ThumbnailGridPlugin(Plugin):
    """Builds a contact sheet of evenly spaced frames."""

    meta = PluginMeta(
        id="thumbnail_grid",
        name="Contact sheet",
        version="1.0.0",
        description="Build a grid of frames from the whole video - handy for thumbnails.",
        author="DripCut",
        tags=("images", "review"),
    )

    def __init__(self) -> None:
        self._context: PluginContext | None = None

    def register(self, context: PluginContext) -> None:
        """Store the context for later tool calls."""
        self._context = context

    def tools(self, context: PluginContext) -> list[ToolAction]:
        """Expose the contact-sheet action."""
        return [
            ToolAction(
                id="thumbnail_grid.build",
                label="Build contact sheet",
                description="A 4x4 grid of frames as one PNG.",
                icon="\u25a6",
                group="Images",
                run=self._build,
                params={"columns": 4, "rows": 4, "tile_width": 480},
            )
        ]

    def _build(
        self,
        media: MediaInfo | None,
        *,
        columns: int = 4,
        rows: int = 4,
        tile_width: int = 480,
        **_: object,
    ) -> str:
        """Render the contact sheet and return a status message."""
        if media is None or self._context is None:
            return "Import a video first."
        video = self._context.video
        if video is None:
            return "The video engine is unavailable."
        count = max(1, columns * rows)
        interval = max(0.5, media.duration / (count + 1))
        target_dir = ensure_dir(Path(self._context.output_dir) / "contact-sheets")
        target = target_dir / f"{media.stem}-sheet.png"
        video.runner.run(
            [
                "-i", str(media.path),
                "-vf",
                f"fps=1/{interval:.3f},scale={int(tile_width)}:-1:flags=lanczos,"
                f"tile={columns}x{rows}:padding=8:margin=12:color=0x0E1220",
                "-frames:v", "1", str(target),
            ],
            outputs=[target],
            stage="Contact sheet",
        )
        self._context.notify(f"Contact sheet ready: {target.name}", "success")
        return str(target)
