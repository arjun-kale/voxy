from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
import os
import tomllib


APP_NAME = "Voxy"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "voice-input"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "voice-input"


def models_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "vosk"


def default_config_path() -> Path:
    return config_dir() / "config.toml"


def _default_socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return str(Path(runtime_dir) / "voice-input.sock")
    return f"/tmp/voice-input-{os.getuid()}.sock"


@dataclass(slots=True)
class SpeechConfig:
    model_path: str = str(models_dir() / "vosk-model-small-en-us-0.15")
    sample_rate: int = 16000
    # 100 ms blocks: lower latency for recognition and the level meter.
    blocksize: int = 1600
    device: int | None = None


@dataclass(slots=True)
class InputConfig:
    backend: str = "auto"
    append_space: bool = True


@dataclass(slots=True)
class TextConfig:
    auto_capitalize: bool = True
    spoken_punctuation: bool = True
    remove_fillers: bool = True
    voice_commands: bool = True
    replacements: dict[str, str] = field(default_factory=dict)
    snippets: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class BehaviorConfig:
    sounds: bool = True
    auto_stop_seconds: int = 20
    history: bool = True
    history_limit: int = 1000


@dataclass(slots=True)
class AppearanceConfig:
    theme: str = "system"
    accent: str = "#7C5CFF"
    overlay: bool = True
    overlay_position: str = "bottom"
    live_text: bool = True


@dataclass(slots=True)
class ServiceConfig:
    socket_path: str = field(default_factory=_default_socket_path)
    notifications: bool = True


@dataclass(slots=True)
class ShortcutConfig:
    toggle: str = "<Control><Alt>space"


@dataclass(slots=True)
class AppStateConfig:
    onboarded: bool = False


@dataclass(slots=True)
class AppConfig:
    speech: SpeechConfig = field(default_factory=SpeechConfig)
    input: InputConfig = field(default_factory=InputConfig)
    text: TextConfig = field(default_factory=TextConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    shortcut: ShortcutConfig = field(default_factory=ShortcutConfig)
    app: AppStateConfig = field(default_factory=AppStateConfig)
    path: Path = field(default_factory=default_config_path)


_SECTIONS = ("speech", "input", "text", "behavior", "appearance", "service", "shortcut", "app")


def _as_optional_int(raw: object) -> int | None:
    if raw in ("", None):
        return None
    if isinstance(raw, bool):
        raise ValueError(f"Invalid integer value: {raw!r}")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    raise ValueError(f"Invalid integer value: {raw!r}")


def _coerce(current: object, raw: object, name: str) -> object:
    if name == "device":
        return _as_optional_int(raw)
    if isinstance(current, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)
    if isinstance(current, int):
        return int(raw)  # type: ignore[arg-type]
    if isinstance(current, dict):
        if not isinstance(raw, dict):
            raise ValueError(f"Expected a table for {name!r}")
        return {str(k): str(v) for k, v in raw.items()}
    return str(raw)


def _apply(section: object, data: dict[str, object]) -> None:
    for f in fields(section):  # type: ignore[arg-type]
        if f.name in data:
            current = getattr(section, f.name)
            setattr(section, f.name, _coerce(current, data[f.name], f.name))


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    config = AppConfig(path=config_path)

    if config_path.exists():
        data = tomllib.loads(config_path.read_text())
        for name in _SECTIONS:
            raw = data.get(name)
            if isinstance(raw, dict):
                _apply(getattr(config, name), raw)

    config.speech.model_path = str(Path(config.speech.model_path).expanduser())
    if config.service.socket_path in ("", None):
        config.service.socket_path = _default_socket_path()
    else:
        config.service.socket_path = str(Path(config.service.socket_path).expanduser())
    return config


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value is None:
        return '""'
    text = str(value)
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def dump_config(config: AppConfig) -> str:
    lines: list[str] = ["# Voxy settings. Edit here or from the Settings window.", ""]
    nested: list[tuple[str, dict[str, str]]] = []

    for name in _SECTIONS:
        section = getattr(config, name)
        lines.append(f"[{name}]")
        for f in fields(section):
            value = getattr(section, f.name)
            if isinstance(value, dict):
                nested.append((f"{name}.{f.name}", value))
                continue
            lines.append(f"{f.name} = {_toml_value(value)}")
        lines.append("")

    for table, values in nested:
        lines.append(f"[{table}]")
        for key, value in values.items():
            lines.append(f"{_toml_value(key)} = {_toml_value(value)}")
        lines.append("")

    return "\n".join(lines)


def save_config(config: AppConfig) -> None:
    config.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.path.with_suffix(".toml.tmp")
    tmp.write_text(dump_config(config))
    tmp.replace(config.path)
