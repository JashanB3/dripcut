"""Whisper transcription via faster-whisper (CTranslate2).

Choices that matter on an 8 GB M1 Air:

* ``small`` + ``int8`` is the default: about 500 MB resident, roughly 5x faster
  than realtime, and materially better punctuation than ``base``.
* The model is loaded lazily and cached on the engine, because construction costs
  more than a short transcription.
* Audio is pre-extracted to 16 kHz mono WAV with FFmpeg. Feeding Whisper a 4K
  container makes it decode video frames it will never look at.
* VAD filtering is on by default: it skips silence, which is the single largest
  speed win on long recordings.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from tempfile import mkdtemp

from dripcut.core.errors import ModelUnavailableError, TranscriptionError
from dripcut.core.logging import get_logger
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.models.transcript import Transcript, TranscriptSegment, Word
from dripcut.utils.concurrency import CancelToken, OperationCancelled

__all__ = ["TranscriptionEngine"]

_log = get_logger("engines.ai.transcription")

ProgressFn = Callable[[float, str], None]


class TranscriptionEngine:
    """Wraps faster-whisper and keeps one loaded model per configuration."""

    def __init__(
        self,
        runner: FFmpegRunner,
        *,
        model_name: str = "small",
        compute_type: str = "int8",
        device: str = "auto",
        beam_size: int = 1,
        vad_filter: bool = True,
        language: str = "auto",
        download_root: Path | None = None,
    ) -> None:
        self.runner = runner
        self.model_name = model_name
        self.compute_type = compute_type
        self.device = device
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.language = language
        self.download_root = download_root
        self._model: object | None = None
        self._model_key: tuple[str, str, str] | None = None

    # ------------------------------------------------------------------ loading

    @property
    def loaded(self) -> bool:
        """True when a model is resident in memory."""
        return self._model is not None

    def available(self) -> bool:
        """True when faster-whisper is importable."""
        try:
            import faster_whisper  # noqa: F401,PLC0415

            return True
        except ImportError:
            return False

    def load(self) -> object:
        """Load (or reuse) the configured Whisper model.

        Raises:
            ModelUnavailableError: When faster-whisper is missing or the weights
                cannot be fetched.
        """
        key = (self.model_name, self.compute_type, self.device)
        if self._model is not None and self._model_key == key:
            return self._model
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError as exc:
            raise ModelUnavailableError(
                "faster-whisper is not installed.",
                hint="Install it with `pip install faster-whisper`.",
            ) from exc

        device = self.device
        if device == "auto":
            # CTranslate2 has no Metal backend; CPU with int8 is the fast path here.
            device = "cpu"
        _log.info("loading whisper %s (%s, %s)", self.model_name, device, self.compute_type)
        started = time.monotonic()
        try:
            self._model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=self.compute_type,
                cpu_threads=max(2, min(6, os.cpu_count() or 4)),
                download_root=str(self.download_root) if self.download_root else None,
            )
        except Exception as exc:  # noqa: BLE001 - surfaces as a friendly error
            raise ModelUnavailableError(
                f"Whisper model {self.model_name!r} could not be loaded.",
                hint="The first run downloads the weights and needs a connection once.",
            ) from exc
        self._model_key = key
        _log.info("whisper ready in %.1fs", time.monotonic() - started)
        return self._model

    def unload(self) -> None:
        """Drop the model to reclaim memory before a heavy encode."""
        self._model = None
        self._model_key = None

    # ------------------------------------------------------------- transcription

    def transcribe(
        self,
        source: Path,
        *,
        duration: float | None = None,
        word_timestamps: bool = True,
        initial_prompt: str = "",
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript:
        """Transcribe a media file.

        Args:
            source: Audio or video file.
            duration: Known duration; enables percentage progress.
            word_timestamps: Request per-word timings (needed for karaoke captions).
            initial_prompt: Domain vocabulary hint, e.g. product names.
            on_progress: ``(fraction, stage)`` callback.
            cancel_token: Cancellation token, checked between segments.

        Returns:
            A populated :class:`Transcript`.

        Raises:
            TranscriptionError: If audio extraction or decoding fails.
        """
        media_path = Path(source)
        model = self.load()
        workdir = Path(mkdtemp(prefix="dripcut-asr-"))
        audio_path = workdir / "audio.wav"
        try:
            if on_progress:
                on_progress(0.02, "Preparing audio")
            self._extract_audio(media_path, audio_path, cancel_token=cancel_token)

            if on_progress:
                on_progress(0.12, "Transcribing")
            language = None if self.language in {"auto", "", None} else self.language
            segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
                str(audio_path),
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                vad_parameters={"min_silence_duration_ms": 400} if self.vad_filter else None,
                word_timestamps=word_timestamps,
                language=language,
                initial_prompt=initial_prompt or None,
                condition_on_previous_text=False,
            )
            total = duration or float(getattr(info, "duration", 0.0)) or 0.0
            segments: list[TranscriptSegment] = []
            for index, segment in enumerate(segments_iter):
                if cancel_token is not None:
                    cancel_token.raise_if_cancelled()
                words = tuple(
                    Word(
                        text=str(word.word).strip(),
                        start=float(word.start),
                        end=float(word.end),
                        probability=float(getattr(word, "probability", 1.0) or 1.0),
                    )
                    for word in (getattr(segment, "words", None) or [])
                    if word.start is not None and word.end is not None
                )
                segments.append(
                    TranscriptSegment(
                        index=index,
                        start=float(segment.start),
                        end=float(segment.end),
                        text=str(segment.text).strip(),
                        words=words,
                        no_speech_prob=float(getattr(segment, "no_speech_prob", 0.0) or 0.0),
                    )
                )
                if on_progress and total > 0:
                    on_progress(min(0.98, 0.12 + (segment.end / total) * 0.86), "Transcribing")

            if on_progress:
                on_progress(1.0, "Transcript ready")
            return Transcript(
                source=media_path,
                language=str(getattr(info, "language", "") or self.language),
                duration=total,
                segments=segments,
                model=f"whisper-{self.model_name}",
                created_at=time.time(),
            )
        except OperationCancelled:
            raise
        except ModelUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaces as a friendly error
            raise TranscriptionError(
                f"{media_path.name} could not be transcribed.",
                hint="Try again. If transcription still fails, contact support with the job ID.",
            ) from exc
        finally:
            for leftover in workdir.glob("*"):
                leftover.unlink(missing_ok=True)
            workdir.rmdir()

    def _extract_audio(
        self, source: Path, destination: Path, *, cancel_token: CancelToken | None = None
    ) -> Path:
        """Decode to 16 kHz mono WAV - exactly what Whisper wants."""
        self.runner.run(
            [
                "-i", str(source),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(destination),
            ],
            cancel_token=cancel_token,
            outputs=[destination],
            stage="Preparing audio",
        )
        if not destination.exists() or destination.stat().st_size < 1024:
            raise TranscriptionError(
                f"No audio could be read from {source.name}.",
                hint="Check the file actually has a sound track.",
            )
        return destination
