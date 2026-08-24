"""Provider-neutral transcription adapters for local and hosted speech models."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol, cast

from dripcut.core.errors import ModelUnavailableError, TranscriptionError
from dripcut.core.logging import get_logger
from dripcut.engines.ai.transcription import TranscriptionEngine
from dripcut.engines.ffmpeg.runner import FFmpegRunner
from dripcut.models.transcript import Transcript, TranscriptSegment, Word
from dripcut.utils.concurrency import CancelToken, OperationCancelled

ProgressFn = Callable[[float, str], None]
_log = get_logger("engines.ai.transcription_provider")


class TranscriptionProvider(Protocol):
    """Stable boundary implemented by every speech-to-text provider."""

    name: str
    version: str
    remote: bool

    @property
    def model(self) -> str: ...

    def available(self) -> bool: ...

    def transcribe(
        self,
        source: Path,
        *,
        initial_prompt: str = "",
        language: str = "auto",
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript: ...


class LocalTranscriptionProvider:
    """Adapter preserving the existing faster-whisper implementation."""

    name = "local"
    version = "1"
    remote = False

    def __init__(self, engine: TranscriptionEngine) -> None:
        self.engine = engine

    @property
    def model(self) -> str:
        return f"whisper-{self.engine.model_name}"

    def available(self) -> bool:
        return self.engine.available()

    def transcribe(
        self,
        source: Path,
        *,
        initial_prompt: str = "",
        language: str = "auto",
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript:
        self.engine.language = language
        transcript = self.engine.transcribe(
            source,
            initial_prompt=initial_prompt,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )
        transcript.provider = self.name
        transcript.model = self.model
        return transcript


class GroqTranscriptionProvider:
    """Groq Whisper transcription with compact, provider-appropriate audio."""

    name = "groq"
    version = "1"
    remote = True

    def __init__(
        self,
        runner: FFmpegRunner,
        *,
        api_key: str | None,
        model: str = "whisper-large-v3-turbo",
    ) -> None:
        self.runner = runner
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import groq  # noqa: F401,PLC0415

            return True
        except ImportError:
            return False

    def transcribe(
        self,
        source: Path,
        *,
        initial_prompt: str = "",
        language: str = "auto",
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript:
        if not self.api_key:
            raise ModelUnavailableError(
                "Groq transcription is not configured.",
                hint="Set GROQ_API_KEY on the backend, or use the local provider.",
            )
        try:
            from groq import Groq  # noqa: PLC0415
        except ImportError as exc:
            raise ModelUnavailableError(
                "The Groq SDK is not installed.",
                hint="Install the project dependencies again.",
            ) from exc

        with TemporaryDirectory(prefix="dripcut-groq-") as workdir:
            audio_path = Path(workdir) / "speech.flac"
            if on_progress:
                on_progress(0.02, "Preparing speech audio")
            extract_started = time.monotonic()
            self._extract_audio(source, audio_path, cancel_token=cancel_token)
            extraction_seconds = time.monotonic() - extract_started
            audio_bytes = audio_path.stat().st_size
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            if on_progress:
                on_progress(0.18, "Transcribing with Groq")

            api_started = time.monotonic()
            try:
                with audio_path.open("rb") as audio:
                    request: dict[str, Any] = {
                        "file": (audio_path.name, audio.read()),
                        "model": self.model,
                        "response_format": "verbose_json",
                        "timestamp_granularities": ["word", "segment"],
                        "temperature": 0.0,
                    }
                    if initial_prompt:
                        request["prompt"] = initial_prompt
                    if language not in {"", "auto"}:
                        request["language"] = language
                    response = Groq(api_key=self.api_key).audio.transcriptions.create(**request)
            except OperationCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK failures are normalized
                raise TranscriptionError(
                    f"{source.name} could not be transcribed with Groq.",
                    hint=_safe_provider_error(exc),
                ) from exc
            api_seconds = time.monotonic() - api_started
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()

        normalization_started = time.monotonic()
        payload = _response_payload(response)
        transcript = _normalize_groq_response(source, payload, self.model)
        normalization_seconds = time.monotonic() - normalization_started
        transcript.provider = self.name
        transcript.metadata.update(
            {
                "audio_extraction_seconds": round(extraction_seconds, 3),
                "provider_api_seconds": round(api_seconds, 3),
                "transcript_normalization_seconds": round(normalization_seconds, 3),
                "audio_bytes": audio_bytes,
            }
        )
        if on_progress:
            on_progress(1.0, "Transcript ready")
        return transcript

    def _extract_audio(
        self,
        source: Path,
        destination: Path,
        *,
        cancel_token: CancelToken | None = None,
    ) -> None:
        # Groq recommends lossless FLAC, 16 kHz mono, to reduce upload size and latency.
        self.runner.run(
            [
                "-i",
                str(source),
                "-vn",
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "flac",
                str(destination),
            ],
            cancel_token=cancel_token,
            outputs=[destination],
            stage="Preparing speech audio",
        )
        if not destination.exists() or destination.stat().st_size < 1024:
            raise TranscriptionError(
                f"No audio could be read from {source.name}.",
                hint="Check that the video has an audio track.",
            )


def _response_payload(response: object) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return dict(cast(Any, response).model_dump())
    if isinstance(response, dict):
        return dict(response)
    return {
        "text": getattr(response, "text", ""),
        "language": getattr(response, "language", ""),
        "duration": getattr(response, "duration", 0.0),
        "segments": getattr(response, "segments", []) or [],
        "words": getattr(response, "words", []) or [],
    }


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return dict(cast(Any, value).model_dump())
    return {
        key: getattr(value, key)
        for key in ("text", "word", "start", "end", "no_speech_prob")
        if hasattr(value, key)
    }


def _normalize_groq_response(source: Path, payload: dict[str, Any], model: str) -> Transcript:
    raw_words = [_as_dict(item) for item in payload.get("words", []) or []]
    words = tuple(
        Word(
            text=str(item.get("word", item.get("text", ""))).strip(),
            start=float(item.get("start", 0.0)),
            end=float(item.get("end", item.get("start", 0.0))),
        )
        for item in raw_words
        if item.get("start") is not None and item.get("end") is not None
    )
    segments: list[TranscriptSegment] = []
    for index, raw in enumerate(payload.get("segments", []) or []):
        item = _as_dict(raw)
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        segment_words = tuple(word for word in words if word.end > start and word.start < end)
        segments.append(
            TranscriptSegment(
                index=index,
                start=start,
                end=end,
                text=str(item.get("text", "")).strip(),
                words=segment_words,
                no_speech_prob=float(item.get("no_speech_prob", 0.0) or 0.0),
            )
        )
    duration = float(payload.get("duration", 0.0) or 0.0)
    if not segments and str(payload.get("text", "")).strip():
        end = duration or max((word.end for word in words), default=0.0)
        segments.append(
            TranscriptSegment(
                index=0,
                start=0.0,
                end=end,
                text=str(payload["text"]).strip(),
                words=words,
            )
        )
    return Transcript(
        source=source,
        language=str(payload.get("language", "") or "auto"),
        duration=duration or max((item.end for item in segments), default=0.0),
        segments=segments,
        provider="groq",
        model=model,
        created_at=time.time(),
    )


def _safe_provider_error(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    if status == 401:
        return "Groq rejected the backend credential. Check GROQ_API_KEY."
    if status == 413:
        return "The optimized audio is too large for the Groq upload limit."
    if status == 429:
        return "Groq is rate-limiting transcription. Try again shortly."
    if status is not None:
        return f"Groq returned HTTP {status}."
    _log.debug("Groq transcription failed", exc_info=True)
    return "The Groq transcription service could not complete the request."
