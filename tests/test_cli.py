"""CLI: argument parsing, diagnostics, and the non-interactive subcommands."""

from __future__ import annotations

import json

import pytest

from dripcut.cli.doctor import Doctor, Status, environment_table_rows, run_checks
from dripcut.cli.main import build_parser


def test_parser_exposes_every_command() -> None:
    parser = build_parser()
    actions = [a for a in parser._actions if a.dest == "command"]
    assert actions
    commands = set(actions[0].choices)
    assert {
        "up", "doctor", "info", "split", "transcribe", "export", "plugins", "config", "version",
    } <= commands


def test_bare_invocation_has_no_command() -> None:
    assert getattr(build_parser().parse_args([]), "func", None) is None


def test_split_defaults() -> None:
    args = build_parser().parse_args(["split", "video.mp4"])
    assert args.mode == "fixed" and args.quality == "balanced"
    assert args.dry_run is False


@pytest.mark.parametrize(
    "mode", ["fixed", "scene", "silence", "timestamps", "chapters", "ai_highlight"]
)
def test_every_split_mode_parses(mode: str) -> None:
    assert build_parser().parse_args(["split", "v.mp4", "--mode", mode]).mode == mode


def test_unknown_mode_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["split", "v.mp4", "--mode", "teleport"])


def test_transcribe_show_has_a_const() -> None:
    assert build_parser().parse_args(["transcribe", "v.mp4", "--show"]).show == 12
    assert build_parser().parse_args(["transcribe", "v.mp4"]).show == 0


def test_export_preset_choices_are_real() -> None:
    from dripcut.engines.export.presets import EXPORT_PRESETS

    args = build_parser().parse_args(["export", "v.mp4", "--preset", "Source quality"])
    assert args.preset in EXPORT_PRESETS


def test_config_set_is_repeatable() -> None:
    args = build_parser().parse_args(
        ["config", "--set", "server.port=8080", "--set", "ui.theme=light"]
    )
    assert len(args.set) == 2


def test_up_flags() -> None:
    args = build_parser().parse_args(["up", "--port", "9000", "--no-browser", "--skip-checks"])
    assert args.port == 9000 and args.no_browser and args.skip_checks


# ------------------------------------------------------------------------ doctor


def test_doctor_runs_and_covers_every_group(settings, paths) -> None:
    checks = run_checks(settings, paths, deep=False)
    assert checks
    assert {"Runtime", "Media tools", "Storage", "Libraries"} <= {c.group for c in checks}


def test_doctor_reports_the_python_version(settings, paths) -> None:
    python = next(c for c in run_checks(settings, paths, deep=False) if c.name == "Python")
    assert python.status is Status.OK


def test_doctor_creates_missing_folders(settings, paths) -> None:
    folders = next(
        c for c in run_checks(settings, paths, deep=False) if c.name == "Application folders"
    )
    assert folders.status is Status.OK
    assert paths.projects.is_dir() and paths.cache.is_dir()


def test_every_problem_carries_a_hint(settings, paths) -> None:
    """A failure without a remediation step is not useful at 2am."""
    for check in run_checks(settings, paths, deep=False):
        if check.status in {Status.FAIL, Status.WARN}:
            assert check.hint, f"{check.name} reported a problem with no hint"


def test_doctor_detects_a_missing_binary(settings, paths) -> None:
    settings.ffmpeg_path = "definitely-not-a-real-binary"
    ffmpeg = next(c for c in run_checks(settings, paths, deep=False) if c.name == "FFmpeg")
    assert ffmpeg.status is Status.FAIL and "brew install ffmpeg" in ffmpeg.hint


def test_disabled_ai_is_skipped_not_failed(settings, paths) -> None:
    settings.ai.enable_ai = False
    ai = [c for c in run_checks(settings, paths, deep=False) if c.group == "AI"]
    assert ai and all(c.status is Status.SKIP for c in ai)


def test_status_glyphs_and_colours_exist() -> None:
    for status in Status:
        assert status.glyph and status.colour and status.label


def test_doctor_object_is_reusable(settings, paths) -> None:
    doctor = Doctor(settings=settings, paths=paths, deep=False)
    assert len(doctor.run()) == len(doctor.run())


def test_environment_rows_are_pairs(settings, paths) -> None:
    rows = environment_table_rows(settings, paths)
    assert rows and all(len(row) == 2 for row in rows)


# ---------------------------------------------------------------------- commands


def test_version_prints_json(capsys) -> None:
    from argparse import Namespace

    from dripcut.cli.commands import cmd_version

    assert cmd_version(Namespace(json=True)) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "DripCut"


def test_config_path_prints_the_file(capsys, paths) -> None:
    from argparse import Namespace

    from dripcut.cli.commands import cmd_config

    args = Namespace(set=None, reset=False, path=True, command="config", log_level=None)
    assert cmd_config(args) == 0
    assert "settings.json" in capsys.readouterr().out


def test_config_dump_is_valid_json(capsys, paths) -> None:
    from argparse import Namespace

    from dripcut.cli.commands import cmd_config

    args = Namespace(set=None, reset=False, path=False, command="config", log_level=None)
    assert cmd_config(args) == 0
    assert json.loads(capsys.readouterr().out)["server"]["port"] == 7999


def test_config_set_rejects_a_bad_pair(paths) -> None:
    from argparse import Namespace

    from dripcut.cli.commands import cmd_config
    from dripcut.core.errors import ValidationError

    args = Namespace(set=["nonsense"], reset=False, path=False, command="config", log_level=None)
    with pytest.raises(ValidationError):
        cmd_config(args)


def test_config_set_rejects_an_unknown_key(paths) -> None:
    from argparse import Namespace

    from dripcut.cli.commands import cmd_config
    from dripcut.core.errors import ValidationError

    args = Namespace(
        set=["server.invented=1"], reset=False, path=False, command="config", log_level=None
    )
    with pytest.raises(ValidationError):
        cmd_config(args)
