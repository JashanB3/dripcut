"""Built-in plugin: loudness measurement and normalisation."""

from __future__ import annotations

from pathlib import Path

from dripcut.models.media import MediaInfo
from dripcut.plugins.api import Plugin, PluginContext, PluginMeta, ToolAction
from dripcut.utils.fs import ensure_dir

__all__ = ["LoudnessPlugin"]


class LoudnessPlugin(Plugin):
    """Measures EBU R128 loudness and can normalise to a platform target."""

    meta = PluginMeta(
        id="loudness",
        name="Loudness tools",
        version="1.0.0",
        description="Measure LUFS and normalise audio for social platforms.",
        author="DripCut",
        tags=("audio",),
    )

    def __init__(self) -> None:
        self._context: PluginContext | None = None

    def register(self, context: PluginContext) -> None:
        """Store the context."""
        self._context = context

    def tools(self, context: PluginContext) -> list[ToolAction]:
        """Expose measure and normalise actions."""
        return [
            ToolAction(
                id="loudness.measure",
                label="Measure loudness",
                description="Report integrated LUFS and true peak.",
                icon="\u2591",
                group="Audio",
                run=self._measure,
            ),
            ToolAction(
                id="loudness.normalise",
                label="Normalise to -14 LUFS",
                description="Write a copy at the loudness most feeds expect.",
                icon="\u2592",
                group="Audio",
                run=self._normalise,
                params={"target_lufs": -14.0},
            ),
        ]

    def _measure(self, media: MediaInfo | None, **_: object) -> str:
        """Return a human summary of the loudness measurement."""
        if media is None or self._context is None:
            return "Import a video first."
        video = self._context.video
        readings = video.loudness(media.path)
        if not readings.get("lufs"):
            return "No audio to measure."
        return (
            f"{readings['lufs']:.1f} LUFS integrated, "
            f"true peak {readings['true_peak']:.1f} dBTP, range {readings['lra']:.1f} LU"
        )

    def _normalise(self, media: MediaInfo | None, *, target_lufs: float = -14.0, **_: object) -> str:
        """Write a loudness-normalised copy."""
        if media is None or self._context is None:
            return "Import a video first."
        video = self._context.video
        target_dir = ensure_dir(Path(self._context.output_dir) / "normalised")
        target = target_dir / f"{media.stem}-{abs(int(target_lufs))}lufs.mp4"
        output = video.normalise_audio(media.path, target, target_lufs=target_lufs)
        self._context.notify(f"Normalised audio written: {output.name}", "success")
        return str(output)
