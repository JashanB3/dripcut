"""Subtitle orchestration: generate files, burn them in, keep styles per project."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dripcut.core.config import Settings
from dripcut.core.errors import ValidationError
from dripcut.core.logging import get_logger
from dripcut.engines.subtitle.generator import SubtitleEngine
from dripcut.engines.subtitle.styles import get_preset, preset_names
from dripcut.engines.video.encode import EncodeSettings, Quality
from dripcut.engines.video.engine import VideoEngine
from dripcut.models.media import MediaInfo
from dripcut.models.subtitle import CaptionStyle, SubtitleFormat
from dripcut.models.transcript import Transcript
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir

__all__ = ["SubtitleService"]

_log = get_logger("services.subtitles")

ProgressFn = Callable[[float, str], None]


class SubtitleService:
    """Writes subtitle files and burns captions into video."""

    def __init__(
        self,
        engine: SubtitleEngine,
        video: VideoEngine,
        settings: Settings,
    ) -> None:
        self.engine = engine
        self.video = video
        self.settings = settings

    def presets(self) -> list[str]:
        """Available caption preset names."""
        return preset_names()

    def preset(self, name: str) -> CaptionStyle:
        """Load a caption preset by name."""
        return get_preset(name)

    def write(
        self,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        subtitle_format: str | SubtitleFormat = SubtitleFormat.SRT,
        video_size: tuple[int, int] = (1920, 1080),
        offset: float = 0.0,
    ) -> Path:
        """Write a subtitle file for a transcript."""
        chosen = SubtitleFormat(str(subtitle_format))
        target = destination.with_suffix(chosen.suffix)
        ensure_dir(target.parent)
        written = self.engine.write(
            transcript,
            target,
            style=style,
            subtitle_format=chosen,
            video_size=video_size,
            offset=offset,
        )
        _log.info("wrote %s", written.name)
        return written

    def preview_lines(
        self, transcript: Transcript, style: CaptionStyle, *, limit: int = 12
    ) -> list[tuple[str, str]]:
        """``(timecode, text)`` rows for the caption preview list."""
        from dripcut.utils.timecode import format_timecode  # local import keeps the API tidy

        cues = self.engine.build_cues(transcript, style)[:limit]
        return [
            (f"{format_timecode(cue.start, millis=False)}", cue.text.replace("\n", " \u23ce "))
            for cue in cues
        ]

    def burn(
        self,
        media: MediaInfo,
        transcript: Transcript,
        destination: Path,
        *,
        style: CaptionStyle | None = None,
        quality: Quality = Quality.HIGH,
        offset: float = 0.0,
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Burn captions into the picture.

        ASS is always used as the intermediate format, even when the user asked for
        SRT elsewhere, because it is the only way the chosen font, outline and safe
        margins survive into the render.
        """
        if transcript.is_empty:
            raise ValidationError(
                "There is no transcript to burn yet.", hint="Run Transcribe first."
            )
        caption_style = style or CaptionStyle()
        width, height = media.video.display_resolution if media.video else (1920, 1080)
        ass_path = destination.with_suffix(".dripcut.ass")
        self.engine.write(
            transcript,
            ass_path,
            style=caption_style,
            subtitle_format=SubtitleFormat.ASS,
            video_size=(width, height),
            offset=offset,
        )
        try:
            return self.video.burn_subtitles(
                media.path,
                destination,
                ass_path,
                settings=EncodeSettings.for_container(
                    destination.suffix.lstrip(".") or "mp4", quality=quality
                ),
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
        finally:
            ass_path.unlink(missing_ok=True)

    def attach(
        self,
        media: MediaInfo,
        subtitles: Path,
        destination: Path,
        *,
        language: str = "eng",
        cancel_token: CancelToken | None = None,
    ) -> Path:
        """Mux subtitles as a switchable track instead of burning them."""
        return self.video.attach_subtitles(
            media.path, destination, subtitles, language=language, cancel_token=cancel_token
        )
