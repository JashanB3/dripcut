"""Typed, persisted application settings.

Settings are a plain dataclass tree serialised to ``settings.json``. Unknown keys
in an existing file are ignored rather than fatal, so downgrading DripCut never
bricks a user's configuration. Environment variables prefixed ``DRIPCUT_`` win
over the file, which is how CI and the launcher inject overrides.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from dripcut.core.errors import ValidationError
from dripcut.core.paths import app_paths

__all__ = [
    "Settings",
    "ServerSettings",
    "AISettings",
    "VideoSettings",
    "UISettings",
    "load_settings",
    "save_settings",
    "reset_settings",
]

ThemeName = Literal["dark", "light"]
WhisperModelName = Literal["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium"]
ComputeType = Literal["int8", "int8_float16", "float16", "float32"]


@dataclass(slots=True)
class ServerSettings:
    """Local web server used to present the UI."""

    host: str = "127.0.0.1"
    port: int = 7999
    open_browser: bool = True
    share: bool = False  # deliberately off: DripCut never phones home
    max_upload_mb: int = 8192


@dataclass(slots=True)
class AISettings:
    """Local model configuration. Nothing here reaches the network."""

    whisper_model: WhisperModelName = "small"
    whisper_compute_type: ComputeType = "int8"
    whisper_device: str = "auto"
    whisper_beam_size: int = 1
    whisper_vad_filter: bool = True
    whisper_language: str = "auto"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_s: int = 180
    ollama_num_ctx: int = 4096
    ollama_temperature: float = 0.25
    auto_start_ollama: bool = True
    enable_ai: bool = True


@dataclass(slots=True)
class VideoSettings:
    """Rendering defaults applied when a job does not override them."""

    hardware_accel: bool = True  # h264_videotoolbox on Apple silicon
    video_codec: str = "h264"
    audio_codec: str = "aac"
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "192k"
    prefer_stream_copy: bool = True
    max_workers: int = 2  # 8 GB M1: two FFmpeg processes is the sweet spot
    scene_threshold: float = 27.0
    silence_threshold_db: float = -32.0
    silence_min_duration: float = 0.6
    proxy_height: int = 480


@dataclass(slots=True)
class UISettings:
    """Presentation preferences."""

    theme: ThemeName = "dark"
    accent: str = "indigo"
    reduce_motion: bool = False
    show_status_bar: bool = True
    default_page: str = "dashboard"
    recent_limit: int = 12


@dataclass(slots=True)
class Settings:
    """Root settings object handed to every service through the container."""

    server: ServerSettings = field(default_factory=ServerSettings)
    ai: AISettings = field(default_factory=AISettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    ui: UISettings = field(default_factory=UISettings)
    output_dir: str = ""
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    log_level: str = "INFO"
    telemetry: bool = False  # hard-wired off; present so its absence is explicit
    enabled_plugins: list[str] = field(default_factory=list)
    disabled_plugins: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.output_dir:
            self.output_dir = str(app_paths().output)

    @property
    def output_path(self) -> Path:
        """Resolved default export directory."""
        return Path(self.output_dir).expanduser()

    def validate(self) -> None:
        """Raise :class:`ValidationError` when a value would break a render."""
        if not 1024 <= self.server.port <= 65535:
            raise ValidationError("Server port must be between 1024 and 65535.")
        if not 0 <= self.video.crf <= 51:
            raise ValidationError("CRF must be between 0 (lossless) and 51 (worst).")
        if self.video.max_workers < 1:
            raise ValidationError("At least one worker is required.")
        if self.video.silence_threshold_db > 0:
            raise ValidationError("Silence threshold is measured in dBFS and must be negative.")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to plain JSON-compatible types."""
        return asdict(self)


def _coerce(target_type: Any, value: Any) -> Any:
    """Best-effort coercion of a JSON value into the annotated dataclass type."""
    if get_origin(target_type) is Literal:
        allowed = get_args(target_type)
        return value if value in allowed else allowed[0]
    if target_type is bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is str:
        return str(value)
    if get_origin(target_type) is list:
        return list(value) if isinstance(value, (list, tuple)) else []
    return value


def _hydrate(cls: type, data: dict[str, Any]) -> Any:
    """Build a dataclass from a dict, ignoring unknown keys and unusable values.

    ``from __future__ import annotations`` turns dataclass field types into
    strings, so annotations are resolved with :func:`get_type_hints` before any
    coercion happens.
    """
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        annotated = hints.get(f.name, Any)
        if is_dataclass(annotated) and isinstance(raw, dict):
            kwargs[f.name] = _hydrate(annotated, raw)  # type: ignore[arg-type]
            continue
        try:
            kwargs[f.name] = _coerce(annotated, raw)
        except (TypeError, ValueError):
            continue
    return cls(**kwargs)


_ENV_MAP: dict[str, tuple[str, ...]] = {
    "DRIPCUT_PORT": ("server", "port"),
    "DRIPCUT_HOST": ("server", "host"),
    "DRIPCUT_THEME": ("ui", "theme"),
    "DRIPCUT_WHISPER_MODEL": ("ai", "whisper_model"),
    "DRIPCUT_OLLAMA_MODEL": ("ai", "ollama_model"),
    "DRIPCUT_OLLAMA_HOST": ("ai", "ollama_host"),
    "DRIPCUT_LOG_LEVEL": ("log_level",),
    "DRIPCUT_MAX_WORKERS": ("video", "max_workers"),
    "DRIPCUT_OUTPUT": ("output_dir",),
}


def _apply_env(settings: Settings) -> Settings:
    """Overlay ``DRIPCUT_*`` environment variables on top of file settings."""
    for env_name, path in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None:
            continue
        target: Any = settings
        for part in path[:-1]:
            target = getattr(target, part)
        leaf = path[-1]
        current = getattr(target, leaf)
        try:
            setattr(target, leaf, type(current)(raw) if not isinstance(current, bool) else raw.lower() in {"1", "true", "yes"})
        except (TypeError, ValueError):
            continue
    return settings


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from disk, falling back to defaults for anything missing."""
    config_file = path or app_paths().config_file
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            settings = _hydrate(Settings, data if isinstance(data, dict) else {})
        except (json.JSONDecodeError, OSError, TypeError):
            settings = Settings()
    else:
        settings = Settings()
    settings = _apply_env(settings)
    try:
        settings.validate()
    except ValidationError:
        settings = _apply_env(Settings())
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Validate and atomically write settings to disk."""
    settings.validate()
    config_file = path or app_paths().config_file
    config_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(config_file)
    return config_file


def reset_settings(path: Path | None = None) -> Settings:
    """Replace the stored configuration with factory defaults."""
    settings = Settings()
    save_settings(settings, path)
    return settings
