"""Settings: defaults, hydration, environment overrides and persistence."""

from __future__ import annotations

import json

import pytest

from dripcut.core.config import Settings, load_settings, reset_settings, save_settings
from dripcut.core.errors import ValidationError


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 7999
    assert settings.server.share is False, "DripCut must never expose a public URL"
    assert settings.telemetry is False
    assert settings.video.max_workers == 2
    assert settings.ai.ollama_host.startswith("http://127.0.0.1")


def test_output_path_is_expanded(settings) -> None:
    assert settings.output_path.is_absolute()


def test_to_dict_round_trips(paths) -> None:
    original = Settings()
    original.ui.theme = "light"
    original.video.crf = 19
    original.ai.whisper_model = "base"
    save_settings(original, paths.config_file)

    reloaded = load_settings(paths.config_file)
    assert reloaded.ui.theme == "light"
    assert reloaded.video.crf == 19
    assert reloaded.ai.whisper_model == "base"


def test_save_is_atomic_and_valid_json(paths) -> None:
    written = save_settings(Settings(), paths.config_file)
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["server"]["port"] == 7999
    assert not list(paths.config_file.parent.glob("*.tmp")), "temp file was left behind"


def test_unknown_keys_are_ignored(paths) -> None:
    paths.config_file.write_text(
        json.dumps({"server": {"port": 8123, "nonsense": 1}, "invented": True}),
        encoding="utf-8",
    )
    assert load_settings(paths.config_file).server.port == 8123


def test_corrupt_file_falls_back_to_defaults(paths) -> None:
    paths.config_file.write_text("{not json at all", encoding="utf-8")
    assert load_settings(paths.config_file).server.port == 7999


@pytest.mark.parametrize(
    ("variable", "value", "attribute"),
    [
        ("DRIPCUT_PORT", "8080", lambda s: s.server.port),
        ("DRIPCUT_THEME", "light", lambda s: s.ui.theme),
        ("DRIPCUT_OLLAMA_MODEL", "llama3", lambda s: s.ai.ollama_model),
        ("DRIPCUT_LOG_LEVEL", "DEBUG", lambda s: s.log_level),
    ],
)
def test_environment_overrides(monkeypatch, paths, variable, value, attribute) -> None:
    monkeypatch.setenv(variable, value)
    loaded = load_settings(paths.config_file)
    expected = int(value) if value.isdigit() else value
    assert attribute(loaded) == expected


def test_validate_rejects_a_bad_port() -> None:
    settings = Settings()
    settings.server.port = 99999
    with pytest.raises(ValidationError):
        settings.validate()


def test_reset_restores_defaults(paths) -> None:
    changed = Settings()
    changed.ui.theme = "light"
    save_settings(changed, paths.config_file)
    assert reset_settings(paths.config_file).ui.theme == "dark"
