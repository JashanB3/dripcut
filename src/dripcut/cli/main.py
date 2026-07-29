"""Command-line entry point.

``dripcut`` with no arguments launches the app; every other capability is a
subcommand. Parsing lives here and nothing else does: the subcommand functions in
:mod:`dripcut.cli.commands` receive a parsed namespace and return an exit code, so
they stay testable without touching ``sys.argv``.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, NoReturn

from dripcut import APP_NAME, APP_TAGLINE, __version__
from dripcut.cli import commands
from dripcut.core.errors import DripCutError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rich.console import Console

__all__ = ["build_parser", "main", "print_banner"]

_LOGO = r"""
 ___      _         ___     _
|   \ _ _(_)_ __   / __|  _| |_
| |) | '_| | '_ \ | (_| || |  _|
|___/|_| |_| .__/  \___\_,_|\__|
           |_|
"""


def print_banner(console: Console, *, compact: bool = False) -> None:
    """Print the startup banner.

    Args:
        console: Rich console to draw on.
        compact: One-line form, used by short-running subcommands.
    """
    from rich.text import Text  # noqa: PLC0415

    if compact:
        line = Text()
        line.append(APP_NAME, style="bold cyan")
        line.append(f" {__version__}  ", style="bright_black")
        line.append(APP_TAGLINE, style="bright_black")
        console.print(line)
        return

    logo = Text(_LOGO.strip("\n"), style="bold cyan")
    console.print()
    console.print(logo)
    console.print(
        Text(f"  {APP_TAGLINE}  ", style="bright_black").append(
            f"v{__version__}", style="bright_black"
        )
    )
    console.print()


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argument parser."""
    parser = argparse.ArgumentParser(
        prog="dripcut",
        description=f"{APP_NAME} \u2014 {APP_TAGLINE}",
        epilog="Run 'dripcut <command> --help' for details on any command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{APP_NAME} {__version__}",
        help="print the version and exit",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="console log level for this run",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="suppress the startup banner",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # ---------------------------------------------------------------------- up
    up = subparsers.add_parser(
        "up",
        help="launch the DripCut application (default)",
        description="Start the local server and open the interface in a browser.",
    )
    up.add_argument("--host", help="bind address (default 127.0.0.1)")
    up.add_argument("--port", type=int, help="port to listen on (default 7999)")
    up.add_argument("--theme", choices=["dark", "light"], help="start in this theme")
    up.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window"
    )
    up.add_argument(
        "--skip-checks", action="store_true", help="skip the preflight environment check"
    )
    up.set_defaults(func=commands.cmd_up, banner="full")

    # ------------------------------------------------------------------ doctor
    doctor = subparsers.add_parser(
        "doctor",
        help="check the environment and report problems",
        description="Verify Python, FFmpeg, hardware acceleration, AI services, "
        "folders, permissions and free space.",
    )
    doctor.add_argument(
        "--quick", action="store_true", help="skip the slower Ollama model queries"
    )
    doctor.add_argument("--json", action="store_true", help="machine-readable output")
    doctor.set_defaults(func=commands.cmd_doctor, banner="none")

    # -------------------------------------------------------------------- info
    info = subparsers.add_parser(
        "info",
        help="show environment paths, or inspect a media file",
        description="With no argument, print the resolved configuration. "
        "With a file, print its media properties.",
    )
    info.add_argument("source", nargs="?", help="media file to inspect")
    info.add_argument("--json", action="store_true", help="machine-readable output")
    info.set_defaults(func=commands.cmd_info, banner="none")

    # ------------------------------------------------------------------- split
    split = subparsers.add_parser(
        "split",
        help="split a video into clips",
        description="Plan and render a split using any of the built-in modes.",
    )
    split.add_argument("source", help="video file to split")
    split.add_argument(
        "--mode",
        choices=commands.SPLIT_MODES,
        default="fixed",
        help="split strategy (default fixed)",
    )
    split.add_argument("--length", type=float, help="clip length in seconds (fixed mode)")
    split.add_argument("--overlap", type=float, help="overlap between clips in seconds")
    split.add_argument(
        "--timestamps", help="comma-separated cut points, e.g. '0:30,1:15,2:40'"
    )
    split.add_argument(
        "--ranges", help="explicit ranges, e.g. '0:10-0:25,1:00-1:30'"
    )
    split.add_argument(
        "--threshold",
        type=float,
        help="scene sensitivity, or silence level in dB, depending on mode",
    )
    split.add_argument("--max-clips", type=int, help="stop after this many clips")
    split.add_argument(
        "--focus",
        choices=["auto", "hooks", "funny", "educational", "story", "quotes"],
        help="what the AI should look for (ai_highlight mode)",
    )
    split.add_argument("-o", "--output", help="destination folder")
    split.add_argument(
        "--container", default="mp4", choices=["mp4", "mov", "mkv", "webm"], help="output format"
    )
    split.add_argument(
        "--quality",
        choices=commands.QUALITIES,
        default="balanced",
        help="encode quality (default balanced)",
    )
    split.add_argument(
        "--fast",
        action="store_true",
        help="cut on keyframes without re-encoding (much faster, less precise)",
    )
    split.add_argument(
        "--dry-run", action="store_true", help="show the plan without rendering"
    )
    split.set_defaults(func=commands.cmd_split, banner="compact")

    # -------------------------------------------------------------- transcribe
    transcribe = subparsers.add_parser(
        "transcribe",
        help="transcribe audio and write subtitles",
        description="Run Faster Whisper locally and optionally write a subtitle file.",
    )
    transcribe.add_argument("source", help="media file to transcribe")
    transcribe.add_argument(
        "--format",
        choices=commands.SUBTITLE_FORMATS,
        default="srt",
        help="subtitle format to write, or 'none' to transcribe only",
    )
    transcribe.add_argument(
        "--style", default="Clean", help="caption preset to use for styled formats"
    )
    transcribe.add_argument("-o", "--output", help="output file path (without suffix)")
    transcribe.add_argument(
        "--force", action="store_true", help="ignore the transcript cache"
    )
    transcribe.add_argument(
        "--show",
        type=int,
        nargs="?",
        const=12,
        default=0,
        metavar="N",
        help="print the first N caption lines",
    )
    transcribe.set_defaults(func=commands.cmd_transcribe, banner="compact")

    # ------------------------------------------------------------------ export
    export = subparsers.add_parser(
        "export",
        help="export a file using a named preset",
        description="Render one file through the export queue using a built-in preset.",
    )
    export.add_argument("source", help="media file to export")
    export.add_argument(
        "--preset",
        choices=commands.PRESET_NAMES,
        default="Source quality",
        help="export preset",
    )
    export.add_argument("-o", "--output", help="destination folder")
    export.add_argument("--name", help="output file name (without suffix)")
    export.add_argument("--start", type=float, help="trim start, in seconds")
    export.add_argument("--end", type=float, help="trim end, in seconds")
    export.set_defaults(func=commands.cmd_export, banner="compact")

    # ----------------------------------------------------------------- plugins
    plugins = subparsers.add_parser(
        "plugins",
        help="list, enable or disable plugins",
        description="Plugins add tools, split modes and caption styles.",
    )
    plugins.add_argument("--enable", metavar="ID", help="enable a plugin by id")
    plugins.add_argument("--disable", metavar="ID", help="disable a plugin by id")
    plugins.set_defaults(func=commands.cmd_plugins, banner="none")

    # ------------------------------------------------------------------ config
    config = subparsers.add_parser(
        "config",
        help="show or change settings",
        description="Print the effective configuration, or change individual keys.",
    )
    config.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="set a dotted key, e.g. --set server.port=8080 (repeatable)",
    )
    config.add_argument("--reset", action="store_true", help="restore factory defaults")
    config.add_argument("--path", action="store_true", help="print the settings file path")
    config.set_defaults(func=commands.cmd_config, banner="none")

    # ----------------------------------------------------------------- version
    version = subparsers.add_parser("version", help="print the version")
    version.add_argument("--json", action="store_true", help="machine-readable output")
    version.set_defaults(func=commands.cmd_version, banner="none")

    return parser


def _apply_defaults(namespace: argparse.Namespace) -> None:
    """Fill in attributes that only some subcommands declare.

    ``commands`` reads shared overrides (``--host``, ``--theme`` and friends) off a
    single namespace regardless of which subcommand ran, so absent attributes are
    normalised to ``None`` here rather than guarded at every read site.
    """
    for name in ("host", "port", "theme", "output", "no_browser", "json"):
        if not hasattr(namespace, name):
            setattr(namespace, name, None)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run a subcommand.

    Args:
        argv: Argument list, defaulting to ``sys.argv[1:]``.

    Returns:
        A process exit code.
    """
    from rich.console import Console  # noqa: PLC0415

    parser = build_parser()
    args = parser.parse_args(argv)

    # Bare `dripcut` means `dripcut up`.
    if getattr(args, "func", None) is None:
        args = parser.parse_args([*(argv if argv is not None else sys.argv[1:]), "up"])

    _apply_defaults(args)
    console = Console(highlight=False)

    style = getattr(args, "banner", "none")
    if not args.no_banner and style != "none":
        print_banner(console, compact=style == "compact")

    try:
        return int(args.func(args))
    except DripCutError as error:
        commands._report_error(console, error)  # noqa: SLF001 - same package
        return 1
    except KeyboardInterrupt:
        console.print("\n[bright_black]cancelled[/bright_black]")
        return 130
    except BrokenPipeError:  # pragma: no cover - `dripcut info | head`
        return 0
    except Exception as error:  # noqa: BLE001 - last resort, never show a raw traceback
        from dripcut.core.paths import app_paths  # noqa: PLC0415

        console.print(f"\n[red]\u2716 Unexpected error:[/red] {error}")
        console.print(
            f"  [bright_black]details in {app_paths().logs / 'dripcut.log'}[/bright_black]"
        )
        console.print(
            "  [bright_black]re-run with --log-level DEBUG for more[/bright_black]"
        )
        from dripcut.core.logging import get_logger  # noqa: PLC0415

        get_logger("cli").exception("unhandled error in %s", getattr(args, "command", "cli"))
        return 1


def run() -> NoReturn:
    """Console-script wrapper that exits the process."""
    raise SystemExit(main())


if __name__ == "__main__":  # pragma: no cover - module execution
    run()
