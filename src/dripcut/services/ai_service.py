"""AI orchestration: transcription with caching, plus analysis helpers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from dripcut.core.config import Settings
from dripcut.core.errors import ModelUnavailableError
from dripcut.core.events import EventBus, EventName
from dripcut.core.logging import get_logger
from dripcut.core.paths import AppPaths
from dripcut.engines.ai.analysis import AnalysisEngine, Chapter, Highlight, Hook
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.transcription import TranscriptionEngine
from dripcut.models.transcript import Transcript
from dripcut.utils.concurrency import CancelToken
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
    ) -> None:
        self.transcription = transcription
        self.analysis = analysis
        self.llm = llm
        self.events = events
        self.settings = settings
        self.paths = paths
        self._lock = threading.Lock()

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

    def cache_path(self, source: Path) -> Path:
        """Where the transcript for ``source`` is cached."""
        stat = source.stat() if source.exists() else None
        stamp = f"{int(stat.st_mtime)}-{stat.st_size}" if stat else "unknown"
        directory = ensure_dir(self.paths.cache / "transcripts")
        model = self.settings.ai.whisper_model.replace(".", "_")
        return directory / f"{source.stem}-{stamp}-{model}.json"

    def cached_transcript(self, source: Path) -> Transcript | None:
        """Return a cached transcript for ``source``, or ``None``."""
        path = self.cache_path(Path(source))
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
        on_progress: ProgressFn | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Transcript:
        """Transcribe a file, reusing the cache unless ``force`` is set."""
        media_path = Path(source).expanduser()
        if not force:
            cached = self.cached_transcript(media_path)
            if cached is not None:
                _log.info("using cached transcript for %s", media_path.name)
                if on_progress:
                    on_progress(1.0, "Transcript loaded from cache")
                return cached

        self._sync_transcription_settings()
        with self._lock:  # one Whisper run at a time: the model is not re-entrant
            transcript = self.transcription.transcribe(
                media_path,
                initial_prompt=initial_prompt,
                on_progress=on_progress,
                cancel_token=cancel_token,
            )
        try:
            transcript.save(self.cache_path(media_path))
        except OSError:
            _log.debug("could not cache transcript", exc_info=True)
        self.events.publish(
            EventName.TRANSCRIPT_READY,
            path=str(media_path),
            words=transcript.word_count,
            language=transcript.language,
        )
        return transcript

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
