"""AI orchestration: transcription with caching, plus analysis helpers."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from pathlib import Path

from dripcut.core.config import Settings
from dripcut.core.errors import ModelUnavailableError, TranscriptionError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.engines.ai.analysis import AnalysisEngine, Chapter, Highlight, Hook
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.transcription import TranscriptionEngine
from dripcut.engines.ai.transcription_provider import (
    GroqTranscriptionProvider,
    LocalTranscriptionProvider,
    TranscriptionProvider,
)
from dripcut.models.transcript import Transcript
from dripcut.utils.concurrency import CancelToken, OperationCancelled
from dripcut.utils.fs import ensure_dir

__all__ = ["AIService"]

_log = get_logger("services.ai")

ProgressFn = Callable[[float, str], None]


class AIService:
    """Single entry point for every AI capability.

    Transcripts are cached on disk keyed by file identity, so re-opening a project
    or switching pages never re-runs Whisper - the slowest operation in the app.
    """

    def __init__(
        self,
        transcription: TranscriptionEngine,
        analysis: AnalysisEngine,
        llm: OllamaClient,
        events: EventBus,
        settings: Settings,
        paths: AppPaths,
        groq_transcription: GroqTranscriptionProvider | None = None,
    ) -> None:
        self.transcription = transcription
        self.analysis = analysis
        self.llm = llm
        self.events = events
        self.settings = settings
        self.paths = paths
        self.local_transcription = LocalTranscriptionProvider(transcription)
        self.groq_transcription = groq_transcription
        self._lock = threading.Lock()
        self._hashes: dict[tuple[str, int, int], str] = {}

    # ------------------------------------------------------------------- status

    @property
    def enabled(self) -> bool:
        """True when AI features are switched on in settings."""
        return self.settings.ai.enable_ai

    def status(self) -> dict[str, object]:
        """Readiness snapshot for the dashboard and ``dripcut doctor``."""
        server_up = self.llm.is_up()
        return {
            "enabled": self.enabled,
            "whisper_installed": self.transcription.available(),
            "whisper_model": self.settings.ai.whisper_model,
            "whisper_loaded": self.transcription.loaded,
            "transcription_provider_requested": self.settings.ai.transcription_provider,
            "transcription_provider_active": self.active_transcription_provider.name,
            "groq_configured": bool(
                self.groq_transcription and self.groq_transcription.available()
            ),
            "ollama_up": server_up,
            "ollama_model": self.settings.ai.ollama_model,
            "ollama_model_installed": self.llm.has_model() if server_up else False,
            "models_installed": self.llm.list_models() if server_up else [],
        }

    def prepare(self) -> bool:
        """Start Ollama if configured to, and report whether the LLM is usable."""
        if not self.enabled:
            return False
        return self.llm.ensure_server(autostart=self.settings.ai.auto_start_ollama)

    # -------------------------------------------------------------- transcription

    @property
    def active_transcription_provider(self) -> TranscriptionProvider:
        """Resolve the configured provider without exposing backend credentials."""
        requested = self.settings.ai.transcription_provider
        if requested in {"groq", "auto"}:
            if self.groq_transcription and self.groq_transcription.available():
                return self.groq_transcription
            if requested == "groq":
                _log.warning("Groq transcription is unavailable; using local Whisper")
        return self.local_transcription

    def cache_path(
        self,
        source: Path,
        provider: TranscriptionProvider | None = None,
        *,
        language: str | None = None,
    ) -> Path:
        """Where the transcript for ``source`` is cached."""
        self._sync_transcription_settings()
        selected = provider or self.active_transcription_provider
        content_hash = self._content_hash(source) if source.exists() else "unknown"
        directory = ensure_dir(self.paths.cache / "transcripts")
        language_key = (language or self.settings.ai.whisper_language or "auto").replace("/", "_")
        identity = f"{selected.name}-{selected.model}-{selected.version}-{language_key}"
        safe_identity = "".join(char if char.isalnum() or char in "-_" else "_" for char in identity)
        return directory / f"{content_hash}-{safe_identity}.json"

    def cached_transcript(
        self,
        source: Path,
        provider: TranscriptionProvider | None = None,
        *,
        language: str | None = None,
    ) -> Transcript | None:
        """Return a cached transcript for ``source``, or ``None``."""
        path = self.cache_path(Path(source), provider, language=language)
        if not path.exists():
            return None
        try:
            return Transcript.load(path)
        except Exception:  # noqa: BLE001 - a bad cache entry is not fatal
            _log.debug("ignoring unreadable transcript cache %s", path)
            return None

    def transcribe(
        self,
        source: str | Path,
        *,
        force: bool = False,
        initial_prompt: str = "",
        source_asset_id: str = "",
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript:
        """Transcribe a file, reusing the cache unless ``force`` is set."""
        media_path = Path(source).expanduser()
        self._sync_transcription_settings()
        provider = self.active_transcription_provider
        language = self.settings.ai.whisper_language
        if not force:
            cached = self.cached_transcript(media_path, provider, language=language)
            if cached is not None:
                _log.info("using cached transcript for %s", media_path.name)
                cached.metadata["cache_hit"] = True
                cached.metadata["cache_path"] = str(
                    self.cache_path(media_path, provider, language=language)
                )
                if on_progress:
                    on_progress(1.0, "Transcript loaded from cache")
                return cached

        started = time.monotonic()
        try:
            transcript = self._run_provider(
                provider,
                media_path,
                initial_prompt=initial_prompt,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
        except (ModelUnavailableError, TranscriptionError) as error:
            if not provider.remote or isinstance(error, OperationCancelled):
                raise
            _log.warning("%s transcription failed; using local Whisper", provider.name)
            provider = self.local_transcription
            if not force:
                cached = self.cached_transcript(media_path, provider, language=language)
                if cached is not None:
                    cached.metadata["cache_hit"] = True
                    cached.metadata["fallback_from"] = "groq"
                    cached.metadata["cache_path"] = str(
                        self.cache_path(media_path, provider, language=language)
                    )
                    if on_progress:
                        on_progress(1.0, "Local transcript loaded from cache")
                    return cached
            transcript = self._run_provider(
                provider,
                media_path,
                initial_prompt=initial_prompt,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
            transcript.metadata["fallback_from"] = "groq"
        transcript.source_asset_id = source_asset_id
        transcript.provider = provider.name
        transcript.model = provider.model
        transcript.metadata["cache_hit"] = False
        transcript.metadata["transcription_total_seconds"] = round(
            time.monotonic() - started, 3
        )
        cache_path = self.cache_path(media_path, provider, language=language)
        transcript.metadata["cache_path"] = str(cache_path)
        try:
            transcript.save(cache_path)
        except OSError:
            _log.debug("could not cache transcript", exc_info=True)
        self.events.publish(
            EventName.TRANSCRIPT_READY,
            path=str(media_path),
            words=transcript.word_count,
            language=transcript.language,
        )
        return transcript

    def _run_provider(
        self,
        provider: TranscriptionProvider,
        media_path: Path,
        *,
        initial_prompt: str,
        on_progress: ProgressFn | None,
        cancel_token: CancelToken | None,
    ) -> Transcript:
        if provider.remote:
            return provider.transcribe(
                media_path,
                initial_prompt=initial_prompt,
                language=self.settings.ai.whisper_language,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
        with self._lock:  # faster-whisper's loaded model is not re-entrant
            return provider.transcribe(
                media_path,
                initial_prompt=initial_prompt,
                language=self.settings.ai.whisper_language,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )

    def _content_hash(self, source: Path) -> str:
        stat = source.stat()
        key = (str(source.resolve()), stat.st_size, stat.st_mtime_ns)
        cached = self._hashes.get(key)
        if cached:
            return cached
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            while block := handle.read(4 * 1024 * 1024):
                digest.update(block)
        value = digest.hexdigest()
        self._hashes[key] = value
        return value

    # ------------------------------------------------------------------ analysis

    def find_highlights(
        self,
        transcript: Transcript,
        *,
        target_length: float = 45.0,
        max_clips: int = 8,
        focus: str = "auto",
        min_score: float = 0.35,
        cancel_token: CancelToken | None = None,
    ) -> list[Highlight]:
        """Rank the strongest moments in a transcript."""
        self.prepare()
        highlights = self.analysis.find_highlights(
            transcript,
            target_length=target_length,
            max_clips=max_clips,
            focus=focus,
            min_score=min_score,
            cancel_token=cancel_token,
        )
        self.events.publish(
            EventName.ANALYSIS_READY, kind="highlights", count=len(highlights), focus=focus
        )
        return highlights

    def find_hooks(
        self, transcript: Transcript, *, max_hooks: int = 10, cancel_token: CancelToken | None = None
    ) -> list[Hook]:
        """Find scroll-stopping opening lines."""
        self.prepare()
        return self.analysis.find_hooks(transcript, max_hooks=max_hooks, cancel_token=cancel_token)

    def suggest_titles(self, text: str, *, count: int = 5) -> list[str]:
        """Propose titles for a clip."""
        self.prepare()
        return self.analysis.suggest_titles(text, count=count)

    def summarise(self, transcript: Transcript) -> dict[str, object]:
        """Summarise a transcript."""
        self.prepare()
        return self.analysis.summarise(transcript)

    def suggest_chapters(self, transcript: Transcript, *, max_chapters: int = 8) -> list[Chapter]:
        """Propose chapter markers."""
        self.prepare()
        return self.analysis.suggest_chapters(transcript, max_chapters=max_chapters)

    def pull_model(self, name: str | None = None) -> list[str]:
        """Download an Ollama model, returning the status lines it produced.

        Raises:
            ModelUnavailableError: If the ollama command is unavailable.
        """
        if not self.enabled:
            raise ModelUnavailableError("AI features are switched off in Settings.")
        return list(self.llm.pull(name))

    # ----------------------------------------------------------------- internals

    def _sync_transcription_settings(self) -> None:
        """Push current settings onto the engine, reloading only when needed."""
        ai = self.settings.ai
        changed = (
            self.transcription.model_name != ai.whisper_model
            or self.transcription.compute_type != ai.whisper_compute_type
            or self.transcription.device != ai.whisper_device
        )
        self.transcription.model_name = ai.whisper_model
        self.transcription.compute_type = ai.whisper_compute_type
        self.transcription.device = ai.whisper_device
        self.transcription.beam_size = ai.whisper_beam_size
        self.transcription.vad_filter = ai.whisper_vad_filter
        self.transcription.language = ai.whisper_language
        if changed:
            self.transcription.unload()
