"""Environment diagnostics.

``dripcut doctor`` and the launcher preflight both run these checks. They are
deliberately independent of the service container: doctor has to work when the
environment is broken, which is exactly when the container would fail to build.

Every check answers three questions -- what was tested, what was found, and what
to do about it. A check that cannot say what to do about a failure is not much
use at 2am, so :attr:`Check.hint` is mandatory for anything worse than OK.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from dripcut import __version__
from dripcut.core.config import Settings
from dripcut.core.paths import AppPaths
from dripcut.utils.fs import free_space_gb

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rich.console import Console

__all__ = ["Check", "Doctor", "Status", "render_report", "run_checks"]

MIN_PYTHON = (3, 10)
RECOMMENDED_FREE_GB = 5.0
MIN_FREE_GB = 1.0

# Optional runtime libraries. Missing ones disable a feature; they never stop the app.
OPTIONAL_IMPORTS: tuple[tuple[str, str, str], ...] = (
    ("gradio", "Gradio", "the desktop interface"),
    ("scenedetect", "PySceneDetect", "scene-detection split mode"),
    ("cv2", "OpenCV", "frame analysis helpers"),
    ("pysubs2", "pysubs2", "high-fidelity subtitle writing"),
    ("numpy", "NumPy", "audio and frame maths"),
    ("PIL", "Pillow", "thumbnail and contact-sheet rendering"),
)


class Status(StrEnum):
    """Outcome of a single check."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @property
    def glyph(self) -> str:
        """Single-character status marker."""
        return {"ok": "\u2714", "warn": "\u25b2", "fail": "\u2716", "skip": "\u2500"}[self.value]

    @property
    def colour(self) -> str:
        """Rich colour name for this status."""
        return {"ok": "green", "warn": "yellow", "fail": "red", "skip": "bright_black"}[self.value]

    @property
    def label(self) -> str:
        """Short word shown in the status column."""
        return {"ok": "OK", "warn": "WARN", "fail": "FAIL", "skip": "n/a"}[self.value]


@dataclass(slots=True)
class Check:
    """One diagnostic result.

    Attributes:
        name: Short name of what was tested.
        status: Outcome.
        detail: What was actually found, in human words.
        hint: What to do about it. Required unless the status is OK or SKIP.
        group: Section heading used when rendering.
    """

    name: str
    status: Status
    detail: str = ""
    hint: str = ""
    group: str = "System"

    @property
    def blocking(self) -> bool:
        """True when this failure prevents the app from running at all."""
        return self.status is Status.FAIL


@dataclass(slots=True)
class Doctor:
    """Runs every environment check.

    Args:
        settings: Loaded settings (for binary paths, models, and the output folder).
        paths: Resolved application paths.
        deep: Also probe the Ollama model list and load-test nothing heavier.
    """

    settings: Settings
    paths: AppPaths
    deep: bool = True
    checks: list[Check] = field(default_factory=list)

    def run(self) -> list[Check]:
        """Execute all checks and return them in display order."""
        self.checks = [
            *self._runtime_checks(),
            *self._ffmpeg_checks(),
            *self._acceleration_checks(),
            *self._ai_checks(),
            *self._storage_checks(),
            *self._optional_checks(),
        ]
        return self.checks

    # ------------------------------------------------------------------ runtime

    def _runtime_checks(self) -> Iterator[Check]:
        """Python interpreter and platform."""
        current = sys.version_info[:3]
        if current >= MIN_PYTHON:
            yield Check(
                "Python",
                Status.OK,
                f"{'.'.join(map(str, current))} ({platform.python_implementation()})",
                group="Runtime",
            )
        else:
            wanted = ".".join(map(str, MIN_PYTHON))
            yield Check(
                "Python",
                Status.FAIL,
                f"{'.'.join(map(str, current))} is too old",
                f"DripCut needs Python {wanted} or newer. Rebuild the virtualenv with a "
                f"newer interpreter: python{wanted} -m venv .venv",
                group="Runtime",
            )

        machine = platform.machine()
        system = platform.system()
        yield Check(
            "Platform",
            Status.OK,
            f"{system} {platform.release()} on {machine}",
            group="Runtime",
        )
        yield Check("DripCut", Status.OK, f"version {__version__}", group="Runtime")

    # ------------------------------------------------------------------- ffmpeg

    def _ffmpeg_checks(self) -> Iterator[Check]:
        """FFmpeg and FFprobe presence and version."""
        for label, configured in (
            ("FFmpeg", self.settings.ffmpeg_path),
            ("FFprobe", self.settings.ffprobe_path),
        ):
            resolved = shutil.which(configured) or (
                configured if Path(configured).is_file() else None
            )
            if resolved is None:
                yield Check(
                    label,
                    Status.FAIL,
                    f"{configured!r} not found on PATH",
                    "Install it with: brew install ffmpeg   "
                    "(or set ffmpeg_path/ffprobe_path in settings.json)",
                    group="Media tools",
                )
                continue
            version = _binary_version(resolved)
            yield Check(
                label,
                Status.OK if version else Status.WARN,
                version or f"found at {resolved} but did not report a version",
                "" if version else "The binary may be corrupt. Reinstall FFmpeg.",
                group="Media tools",
            )

    def _acceleration_checks(self) -> Iterator[Check]:
        """Hardware encoder availability (VideoToolbox on Apple Silicon)."""
        if not shutil.which(self.settings.ffmpeg_path):
            yield Check(
                "VideoToolbox",
                Status.SKIP,
                "cannot test without FFmpeg",
                group="Media tools",
            )
            return

        encoders = _list_encoders(self.settings.ffmpeg_path)
        is_macos = platform.system() == "Darwin"
        hw = sorted(name for name in encoders if "videotoolbox" in name)

        if hw:
            enabled = self.settings.video.hardware_accel
            yield Check(
                "VideoToolbox",
                Status.OK if enabled else Status.WARN,
                f"{', '.join(hw)}" + ("" if enabled else " available but disabled in settings"),
                ""
                if enabled
                else "Set video.hardware_accel to true for much faster exports on Apple Silicon.",
                group="Media tools",
            )
        elif is_macos:
            yield Check(
                "VideoToolbox",
                Status.WARN,
                "no VideoToolbox encoders in this FFmpeg build",
                "Exports will use libx264 and be noticeably slower. A Homebrew FFmpeg "
                "build includes VideoToolbox: brew reinstall ffmpeg",
                group="Media tools",
            )
        else:
            software = sorted(n for n in encoders if n in {"libx264", "libx265", "libvpx-vp9"})
            yield Check(
                "VideoToolbox",
                Status.SKIP,
                f"macOS only; using {', '.join(software) or 'software encoders'}",
                group="Media tools",
            )

        if not encoders:
            return
        missing = {"libx264", "aac"} - encoders
        if missing:
            yield Check(
                "Core encoders",
                Status.WARN,
                f"missing {', '.join(sorted(missing))}",
                "This FFmpeg build is unusually minimal. Some exports will fail; "
                "reinstall with: brew reinstall ffmpeg",
                group="Media tools",
            )
        else:
            yield Check(
                "Core encoders",
                Status.OK,
                f"{len(encoders)} encoders available (libx264, aac present)",
                group="Media tools",
            )

    # ----------------------------------------------------------------------- ai

    def _ai_checks(self) -> Iterator[Check]:
        """Faster-Whisper and Ollama readiness."""
        if not self.settings.ai.enable_ai:
            yield Check(
                "AI features",
                Status.SKIP,
                "disabled in settings (ai.enable_ai = false)",
                group="AI",
            )
            return

        try:
            import faster_whisper  # noqa: PLC0415

            installed_version = getattr(faster_whisper, "__version__", "installed")
            yield Check(
                "Faster Whisper",
                Status.OK,
                f"{installed_version}, model '{self.settings.ai.whisper_model}'",
                group="AI",
            )
        except ImportError:
            yield Check(
                "Faster Whisper",
                Status.WARN,
                "not installed",
                "Transcription and AI highlights will be unavailable. "
                "Install with: pip install faster-whisper",
                group="AI",
            )
        else:
            cached = _whisper_cached(self.paths.models, self.settings.ai.whisper_model)
            yield Check(
                "Whisper model",
                Status.OK if cached else Status.WARN,
                "downloaded" if cached else "not downloaded yet",
                ""
                if cached
                else "The model downloads automatically on first transcription "
                f"(~{_model_size_hint(self.settings.ai.whisper_model)}). "
                "Run it once while you have a connection.",
                group="AI",
            )

        yield from self._ollama_checks()

    def _ollama_checks(self) -> Iterator[Check]:
        """Ollama server reachability and model availability."""
        from dripcut.engines.ai.llm import OllamaClient  # noqa: PLC0415

        client = OllamaClient(
            self.settings.ai.ollama_host,
            model=self.settings.ai.ollama_model,
            timeout=8,
        )
        host = self.settings.ai.ollama_host
        if not client.is_up():
            binary = shutil.which("ollama")
            yield Check(
                "Ollama server",
                Status.WARN,
                f"not reachable at {host}",
                "Start it with: ollama serve"
                if binary
                else "Install Ollama from https://ollama.com, then: ollama pull "
                f"{self.settings.ai.ollama_model}",
                group="AI",
            )
            return

        yield Check("Ollama server", Status.OK, f"reachable at {host}", group="AI")
        if not self.deep:
            return

        wanted = self.settings.ai.ollama_model
        try:
            models = client.list_models()
        except Exception as exc:  # noqa: BLE001 - doctor never raises
            yield Check(
                "Ollama model",
                Status.WARN,
                f"could not list models: {exc}",
                f"Check the server logs, then: ollama pull {wanted}",
                group="AI",
            )
            return

        if client.has_model():
            yield Check(
                "Ollama model",
                Status.OK,
                f"'{wanted}' installed ({len(models)} model(s) total)",
                group="AI",
            )
        else:
            available = ", ".join(models[:4]) or "none"
            yield Check(
                "Ollama model",
                Status.WARN,
                f"'{wanted}' not installed (have: {available})",
                f"Pull it with: ollama pull {wanted}",
                group="AI",
            )

    # ------------------------------------------------------------------ storage

    def _storage_checks(self) -> Iterator[Check]:
        """Application folders, write permissions, and free space."""
        try:
            self.paths.create_all()
        except OSError as exc:
            yield Check(
                "Application folders",
                Status.FAIL,
                f"could not create {self.paths.home}: {exc.strerror or exc}",
                "Check the permissions on the parent directory, or point DRIPCUT_HOME "
                "somewhere writable.",
                group="Storage",
            )
            return

        required = {
            "home": self.paths.home,
            "logs": self.paths.logs,
            "projects": self.paths.projects,
            "cache": self.paths.cache,
            "models": self.paths.models,
            "plugins": self.paths.plugins,
            "temp": self.paths.temp,
            "output": self.settings.output_path,
        }
        missing = [name for name, path in required.items() if not path.is_dir()]
        if missing:
            yield Check(
                "Application folders",
                Status.FAIL,
                f"missing: {', '.join(missing)}",
                "Something removed them mid-run. Re-run doctor; if it persists, check "
                "DRIPCUT_HOME and DRIPCUT_OUTPUT.",
                group="Storage",
            )
        else:
            yield Check(
                "Application folders",
                Status.OK,
                f"{len(required)} folders present under {_tilde(self.paths.home)}",
                group="Storage",
            )

        for label, target in (
            ("Config writable", self.paths.home),
            ("Output writable", self.settings.output_path),
            ("Temp writable", self.paths.temp),
        ):
            error = _write_probe(target)
            if error is None:
                yield Check(label, Status.OK, _tilde(target), group="Storage")
            else:
                yield Check(
                    label,
                    Status.FAIL,
                    f"{_tilde(target)}: {error}",
                    "Fix the folder permissions, or choose another location "
                    "(DRIPCUT_OUTPUT for exports).",
                    group="Storage",
                )

        free = free_space_gb(self.settings.output_path)
        if free >= RECOMMENDED_FREE_GB:
            status, hint = Status.OK, ""
        elif free >= MIN_FREE_GB:
            status = Status.WARN
            hint = (
                "Video exports are large. Free some space before rendering long "
                "sources or batches."
            )
        else:
            status = Status.FAIL
            hint = "Renders will fail part-way through. Free at least 1 GB."
        yield Check(
            "Free space",
            status,
            f"{free:.1f} GB available on the output volume",
            hint,
            group="Storage",
        )

    # ----------------------------------------------------------------- optional

    def _optional_checks(self) -> Iterator[Check]:
        """Optional Python libraries, reported once as a single row each."""
        for module, label, purpose in OPTIONAL_IMPORTS:
            try:
                __import__(module)
            except ImportError:
                critical = module == "gradio"
                target = '-e ".[dev]"' if critical else module
                yield Check(
                    label,
                    Status.FAIL if critical else Status.WARN,
                    f"not installed \u2014 {purpose} unavailable",
                    f"Install with: pip install {target}",
                    group="Libraries",
                )
            else:
                yield Check(label, Status.OK, purpose, group="Libraries")


# --------------------------------------------------------------------- helpers


def _binary_version(binary: str) -> str:
    """First-line version string from an FFmpeg-family binary, or ``""``."""
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (result.stdout or result.stderr or "").strip().splitlines()
    if not first:
        return ""
    words = first[0].split()
    return " ".join(words[:3]) if len(words) >= 3 else first[0]


def _list_encoders(binary: str) -> set[str]:
    """Encoder names reported by ``ffmpeg -hide_banner -encoders``."""
    path = shutil.which(binary) or binary
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    names: set[str] = set()
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return names


def _whisper_cached(models_dir: Path, model_name: str) -> bool:
    """True when a Faster-Whisper model appears to be on disk already."""
    needle = model_name.replace("/", "--").lower()
    for root in (models_dir, Path.home() / ".cache" / "huggingface" / "hub"):
        if not root.is_dir():
            continue
        try:
            for entry in root.iterdir():
                if needle in entry.name.lower() and any(entry.rglob("*.bin")):
                    return True
                if needle in entry.name.lower() and any(entry.rglob("model.safetensors")):
                    return True
        except OSError:
            continue
    return False


def _model_size_hint(model_name: str) -> str:
    """Rough download size for a Whisper model name."""
    return {
        "tiny": "75 MB",
        "base": "145 MB",
        "small": "480 MB",
        "medium": "1.5 GB",
        "large-v2": "3 GB",
        "large-v3": "3 GB",
    }.get(model_name.lower(), "a few hundred MB")


def _write_probe(directory: Path) -> str | None:
    """Try to create and delete a file in ``directory``; return an error or ``None``."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return exc.strerror or str(exc)
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".dripcut-probe-", delete=True):
            pass
    except OSError as exc:
        return exc.strerror or str(exc)
    return None


def _tilde(path: Path) -> str:
    """Shorten a path with ``~`` for display."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def run_checks(settings: Settings, paths: AppPaths, *, deep: bool = True) -> list[Check]:
    """Convenience wrapper: build a :class:`Doctor` and run it."""
    return Doctor(settings=settings, paths=paths, deep=deep).run()


def render_report(
    checks: list[Check],
    console: Console,
    *,
    show_hints: bool = True,
    verbose: bool = True,
) -> int:
    """Print the diagnostic report.

    Args:
        checks: Results from :func:`run_checks`.
        console: Rich console to print to.
        show_hints: Print the remediation panel for warnings and failures.
        verbose: Print the full per-check table (off for launcher preflight).

    Returns:
        ``0`` when nothing is blocking, ``1`` when at least one check failed.
    """
    from rich.panel import Panel  # noqa: PLC0415
    from rich.table import Table  # noqa: PLC0415
    from rich.text import Text  # noqa: PLC0415

    failures = [c for c in checks if c.status is Status.FAIL]
    warnings = [c for c in checks if c.status is Status.WARN]

    if verbose:
        current_group = ""
        table = Table(
            box=None,
            pad_edge=False,
            show_header=False,
            expand=False,
            padding=(0, 1),
        )
        table.add_column("status", width=6, no_wrap=True)
        table.add_column("name", style="bold", width=20, no_wrap=True)
        table.add_column("detail", overflow="fold")

        for check in checks:
            if check.group != current_group:
                current_group = check.group
                table.add_row("", "", "")
                table.add_row("", Text(current_group.upper(), style="bold bright_black"), "")
            table.add_row(
                Text(f"{check.status.glyph} {check.status.label}", style=check.status.colour),
                check.name,
                Text(check.detail, style="bright_black" if check.status is Status.SKIP else ""),
            )
        console.print(table)

    counts = {
        "ok": sum(1 for c in checks if c.status is Status.OK),
        "warn": len(warnings),
        "fail": len(failures),
        "skip": sum(1 for c in checks if c.status is Status.SKIP),
    }
    summary = Text()
    summary.append(f"{counts['ok']} passed", style="green")
    summary.append("  \u00b7  ")
    summary.append(f"{counts['warn']} warnings", style="yellow" if warnings else "bright_black")
    summary.append("  \u00b7  ")
    summary.append(f"{counts['fail']} failed", style="red" if failures else "bright_black")
    if counts["skip"]:
        summary.append("  \u00b7  ")
        summary.append(f"{counts['skip']} not applicable", style="bright_black")

    if failures:
        verdict, border = "Not ready to run", "red"
    elif warnings:
        verdict, border = "Ready, with some features unavailable", "yellow"
    else:
        verdict, border = "Everything checks out", "green"

    console.print()
    console.print(Panel(summary, title=verdict, border_style=border, expand=False, padding=(0, 2)))

    if show_hints and (failures or warnings):
        console.print()
        for check in (*failures, *warnings):
            if not check.hint:
                continue
            marker = Text(check.status.glyph, style=check.status.colour)
            console.print(marker, Text(check.name, style="bold"), Text(check.hint))
    return 1 if failures else 0


def environment_table_rows(settings: Settings, paths: AppPaths) -> list[tuple[str, str]]:
    """Label/value rows describing the environment, for ``dripcut info``."""
    return [
        ("DripCut", __version__),
        ("Python", ".".join(map(str, sys.version_info[:3]))),
        ("Platform", f"{platform.system()} {platform.release()} ({platform.machine()})"),
        ("Home", str(paths.home)),
        ("Output", str(settings.output_path)),
        ("Cache", str(paths.cache)),
        ("Logs", str(paths.logs)),
        ("Config", str(paths.config_file)),
        ("Server", f"http://{settings.server.host}:{settings.server.port}"),
        ("Whisper model", settings.ai.whisper_model),
        ("Ollama model", f"{settings.ai.ollama_model} @ {settings.ai.ollama_host}"),
        ("Workers", str(settings.video.max_workers)),
        ("Hardware accel", "on" if settings.video.hardware_accel else "off"),
        ("Free space", f"{free_space_gb(settings.output_path):.1f} GB"),
        ("PATH ffmpeg", shutil.which(settings.ffmpeg_path) or "not found"),
        ("Process", f"pid {os.getpid()}"),
    ]
