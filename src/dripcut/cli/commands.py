"""Subcommand implementations.

Each function takes parsed arguments and returns a process exit code. All real
work is delegated to the service layer through the container -- nothing in this
module knows how to encode video, only how to ask for it and how to render
progress in a terminal.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dripcut import APP_NAME, __version__
from dripcut.cli.doctor import Status, environment_table_rows, render_report, run_checks
from dripcut.core.bootstrap import build_container
from dripcut.core.config import load_settings, save_settings
from dripcut.core.errors import DripCutError, ValidationError
from dripcut.core.logging import get_logger
from dripcut.core.network import pick_server_port
from dripcut.core.paths import app_paths
from dripcut.engines.export.presets import EXPORT_PRESETS, preset_names
from dripcut.engines.video.encode import Quality
from dripcut.models.clip import SplitMode
from dripcut.models.job import JobStatus
from dripcut.models.subtitle import SubtitleFormat
from dripcut.utils.concurrency import CancelToken
from dripcut.utils.fs import ensure_dir
from dripcut.utils.timecode import format_duration

if TYPE_CHECKING:  # pragma: no cover - typing only
    from argparse import Namespace

    from rich.console import Console

    from dripcut.core.container import ServiceContainer

__all__ = [
    "cmd_config",
    "cmd_doctor",
    "cmd_export",
    "cmd_info",
    "cmd_plugins",
    "cmd_split",
    "cmd_transcribe",
    "cmd_up",
    "cmd_version",
]

_log = get_logger("cli.commands")


# --------------------------------------------------------------------- plumbing


def _console(*, stderr: bool = False) -> Console:
    """A Rich console configured for DripCut output."""
    from rich.console import Console as RichConsole  # noqa: PLC0415

    return RichConsole(stderr=stderr, highlight=False, soft_wrap=False)


def _container(args: Namespace, *, load_plugins: bool = True) -> ServiceContainer:
    """Build the service container, applying command-line overrides first."""
    paths = app_paths()
    settings = load_settings(paths.config_file)
    if getattr(args, "host", None):
        settings.server.host = args.host
    if getattr(args, "port", None):
        settings.server.port = int(args.port)
    if getattr(args, "theme", None):
        settings.ui.theme = args.theme
    if getattr(args, "log_level", None):
        settings.log_level = args.log_level
    elif getattr(args, "command", "") != "up":
        # Short-running commands print their own output; log chatter only gets in
        # the way. `up` keeps INFO because its log *is* the startup splash.
        settings.log_level = "WARNING"
    if getattr(args, "no_browser", False):
        settings.server.open_browser = False
    if getattr(args, "output", None):
        settings.output_dir = str(Path(args.output).expanduser())
    settings.validate()
    return build_container(settings, paths=paths, load_plugins=load_plugins)


@contextmanager
def _progress(console: Console, description: str) -> Iterator[Callable[[float, str], None]]:
    """A Rich progress bar exposed as an ``on_progress(fraction, stage)`` callback."""
    from rich.progress import (  # noqa: PLC0415
        BarColumn,
        Progress,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=32, complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        TextColumn("[bright_black]{task.fields[stage]}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(description, total=1000, stage="")

        def report(fraction: float, stage: str = "") -> None:
            """Forward engine progress into the bar."""
            progress.update(
                task,
                completed=max(0, min(1000, int(fraction * 1000))),
                stage=stage[:44],
            )

        yield report
        progress.update(task, completed=1000, stage="done")


def _cancel_on_sigint() -> CancelToken:
    """A cancel token wired to Ctrl-C so FFmpeg shuts down cleanly."""
    import signal  # noqa: PLC0415

    token = CancelToken()

    def handler(signum: int, frame: Any) -> None:  # noqa: ARG001 - signal signature
        """Flip the token; the engines poll it and terminate FFmpeg."""
        token.cancel()

    try:
        signal.signal(signal.SIGINT, handler)
    except ValueError:  # pragma: no cover - not on the main thread
        _log.debug("could not install SIGINT handler")
    return token


def _resolve_source(value: str) -> Path:
    """Validate that a media path exists, with a useful error if it does not."""
    path = Path(value).expanduser()
    if not path.exists():
        raise ValidationError(
            f"{path} does not exist.",
            hint="Check the path, or drag the file into the terminal to paste it exactly.",
        )
    if path.is_dir():
        raise ValidationError(
            f"{path} is a folder, not a media file.",
            hint="Point at a single file, or use the Batch page in the app for folders.",
        )
    return path


def _report_error(console: Console, error: DripCutError) -> None:
    """Print a DripCut error with its remediation hint."""
    from rich.panel import Panel  # noqa: PLC0415
    from rich.text import Text  # noqa: PLC0415

    body = Text(getattr(error, "message", None) or str(error))
    if getattr(error, "hint", None):
        body.append("\n\n")
        body.append(str(error.hint), style="yellow")
    console.print(Panel(body, title=type(error).__name__, border_style="red", expand=False))


# ------------------------------------------------------------------------- up


def cmd_up(args: Namespace) -> int:
    """Run preflight, then launch the desktop application."""
    console = _console()
    paths = app_paths()
    settings = load_settings(paths.config_file)

    if not args.skip_checks:
        checks = run_checks(settings, paths, deep=False)
        blocking = [c for c in checks if c.status is Status.FAIL]
        if blocking:
            console.print()
            render_report(checks, console, verbose=True)
            console.print(
                "\n[red]Cannot start.[/red] Fix the failures above, "
                "or run [bold]dripcut doctor[/bold] for the full report."
            )
            return 1
        degraded = [c for c in checks if c.status is Status.WARN]
        if degraded:
            names = ", ".join(c.name for c in degraded)
            console.print(f"[yellow]\u25b2[/yellow] Starting with limitations: {names}")
            console.print("  [bright_black]run 'dripcut doctor' for details[/bright_black]")

    container = _container(args)
    settings = container.settings

    resolved_port = pick_server_port(settings.server.host, settings.server.port)
    if resolved_port != settings.server.port:
        console.print(
            f"[yellow]\u25b2[/yellow] Port {settings.server.port} is busy; using {resolved_port} instead"
        )
        settings.server.port = resolved_port

    if settings.ai.enable_ai and settings.ai.auto_start_ollama:
        console.print("[bright_black]\u00b7 preparing AI services\u2026[/bright_black]")
        try:
            container.ai.prepare()
        except DripCutError as exc:
            console.print(f"[yellow]\u25b2[/yellow] AI unavailable: {exc}")

    url = f"http://{settings.server.host}:{settings.server.port}"
    console.print(f"[bright_black]\u00b7 plugins:[/bright_black] {len(container.plugins.records())}")
    console.print(f"[bright_black]\u00b7 output: [/bright_black] {settings.output_path}")
    console.print(f"\n  [bold cyan]{APP_NAME}[/bold cyan] is running at [bold]{url}[/bold]")
    console.print("  [bright_black]press Ctrl-C to stop[/bright_black]\n")

    try:
        from dripcut.ui.app import launch  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        if "gradio" in str(exc):
            console.print(
                "[red]\u2716[/red] Gradio is not installed.\n"
                "  Install the app dependencies: [bold]pip install -e .[/bold]"
            )
            return 1
        raise

    if settings.server.open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        launch(container)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        console.print("\n[bright_black]shutting down\u2026[/bright_black]")
    finally:
        queue = container.try_resolve("queue")
        if queue is not None:
            queue.shutdown()
        container.plugins.shutdown()
    return 0


# --------------------------------------------------------------------- doctor


def cmd_doctor(args: Namespace) -> int:
    """Run environment diagnostics."""
    console = _console()
    paths = app_paths()
    settings = load_settings(paths.config_file)
    checks = run_checks(settings, paths, deep=not args.quick)

    if args.json:
        payload = [
            {
                "name": c.name,
                "group": c.group,
                "status": c.status.value,
                "detail": c.detail,
                "hint": c.hint,
            }
            for c in checks
        ]
        print(json.dumps({"checks": payload}, indent=2))
        return 1 if any(c.status is Status.FAIL for c in checks) else 0

    console.print()
    console.print(f"[bold cyan]{APP_NAME}[/bold cyan] [bright_black]doctor[/bright_black]")
    return render_report(checks, console, verbose=True)


# ----------------------------------------------------------------------- info


def cmd_info(args: Namespace) -> int:
    """Show environment information, or inspect a media file."""
    from rich.table import Table  # noqa: PLC0415

    console = _console()
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column("label", style="bright_black", no_wrap=True)
    table.add_column("value", style="bold")

    if args.source:
        container = _container(args, load_plugins=False)
        media = container.media.import_file(_resolve_source(args.source))
        if args.json:
            print(json.dumps(dict(media.summary_rows()), indent=2))
            return 0
        for label, value in media.summary_rows():
            table.add_row(label, value)
        if media.chapters:
            table.add_row("Chapters", str(len(media.chapters)))
        console.print()
        console.print(table)
        return 0

    settings = load_settings(app_paths().config_file)
    rows = environment_table_rows(settings, app_paths())
    if args.json:
        print(json.dumps(dict(rows), indent=2))
        return 0
    for label, value in rows:
        table.add_row(label, value)
    console.print()
    console.print(table)
    return 0


# ---------------------------------------------------------------------- split


def cmd_split(args: Namespace) -> int:
    """Plan and render a split without opening the UI."""
    from rich.table import Table  # noqa: PLC0415

    console = _console()
    source = _resolve_source(args.source)
    container = _container(args, load_plugins=False)
    token = _cancel_on_sigint()

    media = container.media.import_file(source)
    console.print(
        f"\n[bold]{media.name}[/bold] [bright_black]{media.timecode_label} \u00b7 "
        f"{media.size_label}[/bright_black]"
    )

    mode = SplitMode(args.mode)
    parameters: dict[str, Any] = {}
    if args.length is not None:
        parameters["clip_length"] = float(args.length)
    if args.overlap is not None:
        parameters["overlap"] = float(args.overlap)
    if args.timestamps:
        parameters["timestamps"] = args.timestamps
    if args.ranges:
        parameters["ranges"] = args.ranges
    if args.threshold is not None:
        parameters["threshold"] = float(args.threshold)
        parameters["threshold_db"] = float(args.threshold)
    if args.max_clips is not None:
        parameters["max_clips"] = int(args.max_clips)
    if args.focus:
        parameters["focus"] = args.focus

    with _progress(console, f"planning ({mode.value})") as report:
        plan = container.split.plan(
            media, mode, parameters, on_progress=report, cancel_token=token
        )

    if plan.count == 0:
        console.print("[yellow]\u25b2[/yellow] No clips were found with these settings.")
        return 1

    table = Table(box=None, padding=(0, 2))
    table.add_column("#", style="bright_black", justify="right", no_wrap=True)
    table.add_column("range", style="cyan", no_wrap=True)
    table.add_column("length", justify="right", no_wrap=True)
    table.add_column("title", overflow="fold")
    for segment in plan.segments:
        table.add_row(
            str(segment.index),
            segment.timecode_range,
            format_duration(segment.duration),
            segment.display_title(media.stem),
        )
    console.print()
    console.print(table)
    console.print(
        f"\n[bold]{plan.count}[/bold] clips \u00b7 total "
        f"{format_duration(plan.total_duration)} \u00b7 average "
        f"{format_duration(plan.average_duration)}"
    )

    if args.dry_run:
        console.print("\n[bright_black]dry run \u2014 nothing was written[/bright_black]")
        return 0

    destination = ensure_dir(
        Path(args.output).expanduser() if args.output else container.settings.output_path / media.stem
    )
    console.print(f"\n[bright_black]writing to {destination}[/bright_black]")
    with _progress(console, "rendering") as report:
        outputs = container.split.render(
            plan,
            destination,
            container=args.container,
            quality=Quality(args.quality),
            accurate=not args.fast,
            on_progress=report,
            cancel_token=token,
        )
    console.print(f"\n[green]\u2714[/green] wrote {len(outputs)} clips to {destination}")
    return 0


# ----------------------------------------------------------------- transcribe


def cmd_transcribe(args: Namespace) -> int:
    """Transcribe a file and optionally write subtitles."""
    console = _console()
    source = _resolve_source(args.source)
    container = _container(args, load_plugins=False)
    token = _cancel_on_sigint()

    status = container.ai.status()
    if not status["whisper_installed"]:
        raise ValidationError(
            "Faster Whisper is not installed.",
            hint="Install it with: pip install faster-whisper",
        )

    media = container.media.import_file(source)
    if not media.has_audio:
        raise ValidationError(
            f"{media.name} has no audio track.",
            hint="Transcription needs audio. Check the file, or use a different source.",
        )

    console.print(
        f"\n[bold]{media.name}[/bold] [bright_black]{media.timecode_label} \u00b7 "
        f"whisper '{status['whisper_model']}'[/bright_black]"
    )
    with _progress(console, "transcribing") as report:
        transcript = container.ai.transcribe(
            source, force=args.force, on_progress=report, cancel_token=token
        )

    console.print(
        f"\n[green]\u2714[/green] {transcript.word_count} words \u00b7 "
        f"{len(transcript.segments)} segments \u00b7 language "
        f"[bold]{transcript.language or 'unknown'}[/bold]"
    )

    if args.format == "none":
        if args.show:
            console.print()
            for line in transcript.numbered_lines()[: args.show]:
                console.print(f"[bright_black]{line}[/bright_black]")
        return 0

    destination = (
        Path(args.output).expanduser()
        if args.output
        else container.settings.output_path / f"{media.stem}"
    )
    ensure_dir(destination.parent)
    written = container.subtitles.write(
        transcript,
        destination,
        style=container.subtitles.preset(args.style),
        subtitle_format=SubtitleFormat(args.format),
        video_size=media.video.display_resolution if media.video else (1920, 1080),
    )
    console.print(f"[green]\u2714[/green] wrote {written}")

    if args.show:
        console.print()
        for timecode, text in container.subtitles.preview_lines(
            transcript, container.subtitles.preset(args.style), limit=args.show
        ):
            console.print(f"[cyan]{timecode}[/cyan]  {text}")
    return 0


# --------------------------------------------------------------------- export


def cmd_export(args: Namespace) -> int:
    """Export a file using a named preset, through the job queue."""
    console = _console()
    source = _resolve_source(args.source)
    container = _container(args, load_plugins=False)
    queue = container.resolve("queue")

    media = container.media.import_file(source)
    preset = EXPORT_PRESETS[args.preset]
    console.print(
        f"\n[bold]{media.name}[/bold] \u2192 [cyan]{args.preset}[/cyan] "
        f"[bright_black]{preset.description}[/bright_black]"
    )

    job = container.export.queue_preset_export(
        media,
        args.preset,
        folder=args.output,
        name=args.name,
        start=args.start,
        end=args.end,
    )

    with _progress(console, "exporting") as report:
        while job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            report(job.progress, job.stage)
            time.sleep(0.2)
        report(1.0 if job.status is JobStatus.SUCCEEDED else job.progress, job.stage)

    if job.status is JobStatus.SUCCEEDED and job.result:
        for output in job.result.outputs:
            console.print(f"[green]\u2714[/green] {output}")
        queue.shutdown(cancel_pending=False)
        return 0

    console.print(f"[red]\u2716[/red] export {job.status.value}: {job.error or 'unknown error'}")
    if job.hint:
        console.print(f"  [yellow]{job.hint}[/yellow]")
    queue.shutdown(cancel_pending=True)
    return 1


# -------------------------------------------------------------------- plugins


def cmd_plugins(args: Namespace) -> int:
    """List, enable, or disable plugins."""
    from rich.table import Table  # noqa: PLC0415

    console = _console()
    container = _container(args)
    registry = container.plugins

    if args.enable or args.disable:
        target = args.enable or args.disable
        enabled = bool(args.enable)
        record = registry.set_enabled(target, enabled)
        settings = container.settings
        disabled = set(settings.disabled_plugins)
        if enabled:
            disabled.discard(target)
        else:
            disabled.add(target)
        settings.disabled_plugins = sorted(disabled)
        save_settings(settings, container.paths.config_file)
        state = "enabled" if enabled else "disabled"
        console.print(f"[green]\u2714[/green] {record.meta.name} {state}")
        return 0

    records = registry.records()
    if not records:
        console.print("\n[bright_black]No plugins found.[/bright_black]")
        console.print(f"  Drop a .py file in {container.paths.plugins} to add one.")
        return 0

    table = Table(box=None, padding=(0, 2))
    table.add_column("state", no_wrap=True)
    table.add_column("plugin", style="bold", overflow="fold")
    table.add_column("id", style="bright_black", overflow="fold")
    table.add_column("ver", no_wrap=True)
    table.add_column("details", overflow="fold")
    for record in records:
        colour = {"active": "green", "disabled": "bright_black"}.get(record.status, "red")
        table.add_row(
            f"[{colour}]{record.status}[/{colour}]",
            record.meta.name,
            record.meta.id,
            record.meta.version,
            record.error or record.meta.description,
        )
    console.print()
    console.print(table)
    tools = registry.tools()
    if tools:
        console.print(f"\n[bright_black]{len(tools)} tool(s) contributed[/bright_black]")
    return 0


# --------------------------------------------------------------------- config


def cmd_config(args: Namespace) -> int:
    """Show, edit, or reset settings."""
    console = _console()
    paths = app_paths()

    if args.reset:
        from dripcut.core.config import reset_settings  # noqa: PLC0415

        reset_settings(paths.config_file)
        console.print(f"[green]\u2714[/green] settings reset to defaults ({paths.config_file})")
        _log.info("settings reset")
        return 0

    settings = load_settings(paths.config_file)

    if args.set:
        for assignment in args.set:
            if "=" not in assignment:
                raise ValidationError(
                    f"'{assignment}' is not a key=value pair.",
                    hint="Example: dripcut config --set server.port=8080",
                )
            key, _, raw = assignment.partition("=")
            _assign(settings, key.strip(), raw.strip())
            console.print(f"[green]\u2714[/green] {key.strip()} = {raw.strip()}")
        settings.validate()
        save_settings(settings, paths.config_file)
        return 0

    if args.path:
        print(paths.config_file)
        return 0

    print(json.dumps(settings.to_dict(), indent=2))
    return 0


def _assign(settings: Any, dotted: str, raw: str) -> None:
    """Set ``settings.a.b = value``, coercing to the existing field's type."""
    parts = dotted.split(".")
    target = settings
    for part in parts[:-1]:
        if not hasattr(target, part):
            raise ValidationError(
                f"Unknown settings section '{part}'.",
                hint="Run 'dripcut config' to see the available keys.",
            )
        target = getattr(target, part)
    leaf = parts[-1]
    if not hasattr(target, leaf):
        raise ValidationError(
            f"Unknown setting '{dotted}'.",
            hint="Run 'dripcut config' to see the available keys.",
        )
    current = getattr(target, leaf)
    try:
        if isinstance(current, bool):
            value: Any = raw.lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        elif isinstance(current, list):
            value = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            value = raw
    except ValueError as exc:
        raise ValidationError(
            f"'{raw}' is not valid for {dotted} (expected {type(current).__name__}).",
            hint="Check the value and try again.",
        ) from exc
    setattr(target, leaf, value)


# -------------------------------------------------------------------- version


def cmd_version(args: Namespace) -> int:
    """Print the version, one line, script-friendly."""
    if getattr(args, "json", False):
        print(json.dumps({"name": APP_NAME, "version": __version__}))
    else:
        print(f"{APP_NAME} {__version__}")
    return 0


# ------------------------------------------------------------------ constants


SPLIT_MODES: tuple[str, ...] = tuple(mode.value for mode in SplitMode)
QUALITIES: tuple[str, ...] = tuple(quality.value for quality in Quality)
SUBTITLE_FORMATS: tuple[str, ...] = (*(fmt.value for fmt in SubtitleFormat), "none")
PRESET_NAMES: tuple[str, ...] = tuple(preset_names())
