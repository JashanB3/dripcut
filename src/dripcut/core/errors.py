"""The DripCut exception hierarchy.

Every failure surfaced to the UI is a :class:`DripCutError` carrying a message
written for the person using the app plus an optional ``hint`` describing the fix.
Unexpected exceptions are logged with a traceback and shown as a generic failure,
so an engine bug never renders a raw stack trace inside the workspace.
"""

from __future__ import annotations

__all__ = [
    "DripCutError",
    "ValidationError",
    "DependencyError",
    "MediaProbeError",
    "MediaDownloadError",
    "FFmpegError",
    "SplitPlanError",
    "TranscriptionError",
    "ModelUnavailableError",
    "AIProviderError",
    "SocialProviderError",
    "ExportError",
    "PluginError",
    "ProjectError",
]


class DripCutError(Exception):
    """Base class for every error DripCut raises on purpose."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # noqa: D105 - trivial
        return f"{self.message} ({self.hint})" if self.hint else self.message

    @property
    def display(self) -> str:
        """Single-line form suitable for a toast or status bar."""
        return str(self)


class ValidationError(DripCutError):
    """User input is missing or out of range."""


class DependencyError(DripCutError):
    """A required external tool (FFmpeg, Ollama) is missing or unusable."""


class MediaProbeError(DripCutError):
    """ffprobe could not describe the file."""


class MediaDownloadError(DripCutError):
    """A remote video could not be downloaded into the temporary workspace."""


class FFmpegError(DripCutError):
    """An FFmpeg invocation exited non-zero."""

    def __init__(
        self,
        message: str,
        *,
        command: list[str] | None = None,
        stderr_tail: str = "",
        returncode: int | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.command = command or []
        self.stderr_tail = stderr_tail
        self.returncode = returncode


class SplitPlanError(DripCutError):
    """A split strategy could not produce any usable segment."""


class TranscriptionError(DripCutError):
    """Whisper failed to transcribe the media."""


class ModelUnavailableError(DependencyError):
    """A local model (Whisper weights, Ollama model) is not installed."""


class AIProviderError(DripCutError):
    """A structured editorial AI request failed validation or transport."""

    code = "AI_UNAVAILABLE"


class SocialProviderError(DripCutError):
    """An official social OAuth or publishing request failed safely."""

    code = "SOCIAL_PROVIDER_ERROR"


class ExportError(DripCutError):
    """A queued job failed while rendering."""


class PluginError(DripCutError):
    """A plugin failed to load or misbehaved during a hook."""


class ProjectError(DripCutError):
    """A project could not be read, written or migrated."""
