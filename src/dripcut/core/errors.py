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

    code = "DRIPCUT_ERROR"
    status_code = 400
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        code: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:  # noqa: D105 - trivial
        return f"{self.message} ({self.hint})" if self.hint else self.message

    @property
    def display(self) -> str:
        """Single-line form suitable for a toast or status bar."""
        return str(self)


class ValidationError(DripCutError):
    """User input is missing or out of range."""

    code = "VALIDATION_ERROR"


class DependencyError(DripCutError):
    """A required external tool (FFmpeg, Ollama) is missing or unusable."""

    code = "DEPENDENCY_UNAVAILABLE"
    status_code = 503
    retryable = True


class MediaProbeError(DripCutError):
    """ffprobe could not describe the file."""

    code = "MEDIA_PROBE_FAILED"
    status_code = 422


class MediaDownloadError(DripCutError):
    """A remote video could not be downloaded into the temporary workspace."""

    code = "MEDIA_DOWNLOAD_FAILED"
    status_code = 502
    retryable = True


class FFmpegError(DripCutError):
    """An FFmpeg invocation exited non-zero."""

    code = "RENDER_FAILED"
    status_code = 500
    retryable = True

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

    code = "SPLIT_PLAN_INVALID"
    status_code = 422


class TranscriptionError(DripCutError):
    """Whisper failed to transcribe the media."""

    code = "TRANSCRIPTION_FAILED"
    status_code = 502
    retryable = True


class ModelUnavailableError(DependencyError):
    """A local model (Whisper weights, Ollama model) is not installed."""

    code = "MODEL_UNAVAILABLE"
    retryable = False


class AIProviderError(DripCutError):
    """A structured editorial AI request failed validation or transport."""

    code = "AI_UNAVAILABLE"
    status_code = 503
    retryable = True


class SocialProviderError(DripCutError):
    """An official social OAuth or publishing request failed safely."""

    code = "SOCIAL_PROVIDER_ERROR"
    status_code = 502
    retryable = True


class ExportError(DripCutError):
    """A queued job failed while rendering."""

    code = "EXPORT_FAILED"
    status_code = 500
    retryable = True


class PluginError(DripCutError):
    """A plugin failed to load or misbehaved during a hook."""

    code = "PLUGIN_ERROR"
    status_code = 500


class ProjectError(DripCutError):
    """A project could not be read, written or migrated."""

    code = "PROJECT_ERROR"
