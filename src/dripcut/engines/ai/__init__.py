"""Local AI: Whisper for speech, Ollama for language. No network egress."""

from __future__ import annotations

from dripcut.engines.ai.analysis import AnalysisEngine, Highlight, Hook
from dripcut.engines.ai.llm import OllamaClient
from dripcut.engines.ai.transcription import TranscriptionEngine

__all__ = ["AnalysisEngine", "Highlight", "Hook", "OllamaClient", "TranscriptionEngine"]
