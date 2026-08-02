"""FFmpeg process runner with progress reporting and hard cancellation.

Design notes
------------
* ``-progress pipe:1`` gives key=value lines on stdout, so progress parsing never
  has to scrape the human-readable stderr banner.
* stderr is drained on a background thread into a bounded buffer. Without this
  FFmpeg deadlocks on long filter graphs once the OS pipe fills.
* Cancellation sends SIGTERM, waits briefly, then SIGKILL, and deletes the
  partial output so a cancelled export never leaves a corrupt file behind.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from dripcut.core.errors import DependencyError, FFmpegError
from dripcut.core.logging import get_logger
from dripcut.utils.concurrency import CancelToken, OperationCancelled, Throttle

__all__ = ["FFmpegRunner", "ProgressCallback", "FFmpegResult"]

ProgressCallback = Callable[[float, str], None]

_log = get_logger("engines.ffmpeg.runner")
_STDERR_LINES = 60
_VIDEO_ENCODER_FALLBACKS = {
    "h264_videotoolbox": "libx264",
    "hevc_videotoolbox": "libx265",
    "h264_nvenc": "libx264",
    "hevc_nvenc": "libx265",
}


@dataclass(frozen=True, slots=True)
class FFmpegResult:
    """Outcome of a completed FFmpeg invocation."""

    command: list[str]
    returncode: int
    stderr_tail: str
    outputs: tuple[Path, ...] = ()


class FFmpegRunner:
    """Runs FFmpeg commands. One instance is shared by every engine."""

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        *,
        hardware_accel: bool = True,
        overwrite: bool = True,
    ) -> None:
        """
        Args:
            ffmpeg_path: Executable name or absolute path.
            hardware_accel: Allow platform hardware encoders where callers ask for them.
            overwrite: Pass ``-y`` so re-running a render replaces its output.
        """
        self.ffmpeg_path = ffmpeg_path
        self.hardware_accel = hardware_accel
        self.overwrite = overwrite
        self._encoders: frozenset[str] | None = None
        self._filters: frozenset[str] | None = None

    # ---------------------------------------------------------------- availability

    def resolve_binary(self) -> str:
        """Return the absolute FFmpeg path.

        Raises:
            DependencyError: If FFmpeg is not on ``PATH``.
        """
        found = shutil.which(self.ffmpeg_path)
        if not found:
            raise DependencyError(
                "FFmpeg was not found.",
                hint="Install it with `brew install ffmpeg`, then run `dripcut doctor`.",
            )
        return found

    def version(self) -> str:
        """First line of ``ffmpeg -version``, or an empty string when unavailable."""
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.resolve_binary(), "-version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return proc.stdout.splitlines()[0] if proc.stdout else ""
        except (DependencyError, OSError, subprocess.SubprocessError, IndexError):
            return ""

    def available_encoders(self) -> frozenset[str]:
        """Names of every encoder this FFmpeg build exposes (cached)."""
        if self._encoders is not None:
            return self._encoders
        names: set[str] = set()
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.resolve_binary(), "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            for line in proc.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] and not line.startswith(("Encoders:", " -", "---")):
                    names.add(parts[1])
        except (DependencyError, OSError, subprocess.SubprocessError):
            _log.debug("could not enumerate encoders", exc_info=True)
        self._encoders = frozenset(names)
        return self._encoders

    def has_encoder(self, name: str) -> bool:
        """True when ``name`` can be used as ``-c:v``/``-c:a``."""
        encoders = self.available_encoders()
        return name in encoders if encoders else True

    def available_filters(self) -> frozenset[str]:
        """Names of every filter this FFmpeg build exposes (cached)."""
        if self._filters is not None:
            return self._filters
        names: set[str] = set()
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.resolve_binary(), "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            for line in proc.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] and not line.startswith(("Filters:", " -", "---")):
                    names.add(parts[1])
        except (DependencyError, OSError, subprocess.SubprocessError):
            _log.debug("could not enumerate filters", exc_info=True)
        self._filters = frozenset(names)
        return self._filters

    def has_filter(self, name: str) -> bool:
        """True when ``name`` can be used in ``-vf``/``-filter_complex``."""
        filters = self.available_filters()
        return name in filters if filters else True

    def pick_video_encoder(self, codec: str, *, hardware: bool | None = None) -> str:
        """Choose the best encoder for a logical codec name.

        Apple builds usually expose VideoToolbox; AWS GPU workers usually expose
        NVIDIA NVENC. Prefer whichever the local FFmpeg build reports, then fall
        back to portable software encoders.
        """
        use_hw = self.hardware_accel if hardware is None else hardware
        table = {
            "h264": (("h264_videotoolbox", "h264_nvenc"), "libx264"),
            "hevc": (("hevc_videotoolbox", "hevc_nvenc"), "libx265"),
            "h265": (("hevc_videotoolbox", "hevc_nvenc"), "libx265"),
            "vp9": ((), "libvpx-vp9"),
            "av1": ((), "libsvtav1"),
            "prores": ((), "prores_ks"),
        }
        hw_names, sw_name = table.get(codec.lower(), ((), codec))
        if use_hw:
            for hw_name in hw_names:
                if self.has_encoder(hw_name):
                    return hw_name
        if sw_name and self.has_encoder(sw_name):
            return sw_name
        return "libx264"

    # ---------------------------------------------------------------------- running

    def run(
        self,
        args: Sequence[str],
        *,
        duration: float | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_token: CancelToken | None = None,
        outputs: Sequence[Path] = (),
        stage: str = "Rendering",
        capture_stdout: bool = False,
    ) -> FFmpegResult:
        """Execute an FFmpeg command.

        Args:
            args: Arguments *after* the executable (no ``-y``, no ``-progress``).
            duration: Expected output duration in seconds; enables percentage
                progress. When ``None``, progress is reported as ``-1``.
            on_progress: Called as ``(fraction, stage)``, throttled to ~4 Hz.
            cancel_token: Cooperative cancellation.
            outputs: Files this command writes; removed if it fails or is cancelled.
            stage: Label forwarded to ``on_progress``.
            capture_stdout: Keep stdout instead of using it for progress (used by
                commands such as ``silencedetect`` that write data to stdout).

        Returns:
            :class:`FFmpegResult` on success.

        Raises:
            FFmpegError: On a non-zero exit.
            OperationCancelled: When cancellation was requested.
        """
        binary = self.resolve_binary()
        command = [binary, "-hide_banner", "-nostdin", "-loglevel", "error"]
        if self.overwrite:
            command.append("-y")
        if not capture_stdout:
            command += ["-progress", "pipe:1", "-nostats"]
        command += [str(arg) for arg in args]

        _log.debug("ffmpeg %s", " ".join(command[1:]))
        throttle = Throttle(0.25)
        stderr_buffer: deque[str] = deque(maxlen=_STDERR_LINES)
        stdout_buffer: list[str] = []

        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:  # pragma: no cover - depends on the host
            raise FFmpegError("FFmpeg could not be started.", command=command, hint=str(exc)) from exc

        stderr_thread = threading.Thread(
            target=self._drain, args=(process.stderr, stderr_buffer), daemon=True
        )
        stderr_thread.start()

        cancelled = False
        try:
            if capture_stdout:
                stdout_buffer.append(process.stdout.read() if process.stdout else "")
                if cancel_token and cancel_token.cancelled:
                    cancelled = True
            else:
                cancelled = self._pump_progress(
                    process, duration, on_progress, cancel_token, throttle, stage
                )
            if cancelled:
                self._terminate(process)
            process.wait(timeout=None if not cancelled else 10)
        except KeyboardInterrupt:  # pragma: no cover - interactive only
            self._terminate(process)
            raise
        finally:
            stderr_thread.join(timeout=2)

        stderr_tail = "\n".join(stderr_buffer).strip()

        if cancelled or (cancel_token is not None and cancel_token.cancelled):
            self._cleanup(outputs)
            raise OperationCancelled("FFmpeg cancelled")

        if process.returncode != 0:
            self._cleanup(outputs)
            retry_args = self._software_fallback_args(args)
            if self.hardware_accel and retry_args is not None:
                fallback_encoder = self._encoder_name_from_args(retry_args)
                if fallback_encoder:
                    _log.warning(
                        "hardware encoder failed; retrying with %s", fallback_encoder
                    )
                    return self.run(
                        retry_args,
                        duration=duration,
                        on_progress=on_progress,
                        cancel_token=cancel_token,
                        outputs=outputs,
                        stage=stage,
                        capture_stdout=capture_stdout,
                    )
            raise FFmpegError(
                "FFmpeg could not finish this render.",
                command=command,
                stderr_tail=stderr_tail,
                returncode=process.returncode,
                hint=_hint_from_stderr(stderr_tail),
            )

        if on_progress:
            on_progress(1.0, stage)
        return FFmpegResult(
            command=command,
            returncode=0,
            stderr_tail=stderr_tail if not capture_stdout else "".join(stdout_buffer),
            outputs=tuple(outputs),
        )

    def probe_stderr(
        self, args: Sequence[str], *, timeout: int = 900
    ) -> str:
        """Run a null-output analysis pass and return its stderr.

        Filters such as ``silencedetect`` and ``blackdetect`` report findings on
        stderr with no output file; this helper exists so those callers do not have
        to reimplement process handling.
        """
        binary = self.resolve_binary()
        command = [binary, "-hide_banner", "-nostdin", *[str(a) for a in args]]
        _log.debug("ffmpeg analysis %s", " ".join(command[1:]))
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                command, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise FFmpegError(
                "Analysis took too long and was stopped.",
                command=command,
                hint="Try a shorter section of the file.",
            ) from exc
        if proc.returncode != 0 and not proc.stderr:
            raise FFmpegError(
                "FFmpeg analysis failed.", command=command, returncode=proc.returncode
            )
        return proc.stderr

    # ----------------------------------------------------------------- internals

    def _pump_progress(
        self,
        process: subprocess.Popen[str],
        duration: float | None,
        on_progress: ProgressCallback | None,
        cancel_token: CancelToken | None,
        throttle: Throttle,
        stage: str,
    ) -> bool:
        """Read ``-progress`` output until the process ends. Returns True if cancelled."""
        if process.stdout is None:  # pragma: no cover - defensive
            return False
        for line in process.stdout:
            if cancel_token is not None and cancel_token.cancelled:
                return True
            key, _, value = line.strip().partition("=")
            if key not in {"out_time_us", "out_time_ms", "progress"} or not on_progress:
                continue
            if key == "progress" and value == "end":
                continue
            if not duration or duration <= 0:
                if throttle.ready():
                    on_progress(-1.0, stage)
                continue
            try:
                micros = float(value)
            except ValueError:
                continue
            seconds = micros / 1_000_000 if key == "out_time_us" else micros / 1_000
            if throttle.ready():
                on_progress(max(0.0, min(0.99, seconds / duration)), stage)
        return False

    @staticmethod
    def _drain(stream: object, buffer: deque[str]) -> None:
        """Collect stderr lines without blocking the encoder."""
        if stream is None:  # pragma: no cover - defensive
            return
        for line in stream:  # type: ignore[attr-defined]
            text = line.rstrip()
            if text:
                buffer.append(text)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        """SIGTERM then SIGKILL - FFmpeg occasionally ignores the first."""
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:  # pragma: no cover - rare
            process.kill()

    @staticmethod
    def _cleanup(outputs: Sequence[Path]) -> None:
        """Delete partial outputs so failures never masquerade as results."""
        for path in outputs:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
            except OSError:  # pragma: no cover - best effort
                _log.debug("could not remove partial output %s", path)

    @staticmethod
    def _encoder_name_from_args(args: Sequence[str]) -> str | None:
        """Return the concrete ``-c:v`` value from an FFmpeg argument list."""
        tokens = list(args)
        for index, token in enumerate(tokens[:-1]):
            if token == "-c:v":
                return tokens[index + 1]
        return None

    @staticmethod
    def _software_fallback_args(args: Sequence[str]) -> list[str] | None:
        """Swap a hardware video encoder for its software fallback if present."""
        tokens = list(args)
        for index, token in enumerate(tokens[:-1]):
            if token != "-c:v":
                continue
            encoder = tokens[index + 1]
            fallback = _VIDEO_ENCODER_FALLBACKS.get(encoder)
            if fallback is None:
                return None
            tokens[index + 1] = fallback
            return _strip_hardware_encoder_options(tokens)
        return None


def _strip_hardware_encoder_options(tokens: list[str]) -> list[str]:
    """Remove hardware-only output flags before retrying with software."""
    cleaned: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token in {"-allow_sw", "-q:v", "-cq:v"}:
            skip_next = True
            continue
        if token == "-preset":
            skip_next = True
            continue
        cleaned.append(token)
    return cleaned


def _hint_from_stderr(stderr: str) -> str | None:
    """Translate common FFmpeg failures into an actionable sentence."""
    text = stderr.lower()
    if "no such file or directory" in text:
        return "The source file moved or was renamed. Re-import it."
    if "permission denied" in text:
        return "DripCut cannot write to that folder. Pick a different output folder."
    if "invalid data found" in text:
        return "The file looks damaged. Try remuxing it with Convert first."
    if "unknown encoder" in text:
        return "This FFmpeg build lacks that encoder. Switch the codec in Settings."
    if "no such filter" in text and "subtitles" in text:
        return "This FFmpeg build cannot burn subtitles. Install an FFmpeg build with libass, or render without captions."
    if "no such filter" in text and "drawtext" in text:
        return "This FFmpeg build cannot draw text. Install an FFmpeg build with freetype support."
    if "height not divisible by 2" in text or "width not divisible by 2" in text:
        return "Use an even width and height - most codecs require it."
    if "no space left" in text:
        return "The disk is full. Free some space and run the job again."
    return None
