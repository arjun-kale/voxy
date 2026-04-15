from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib


def _default_socket_path() -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return str(Path(runtime_dir) / "voice-input.sock")
    return f"/tmp/voice-input-{os.getuid()}.sock"


@dataclass(slots=True)
class SpeechConfig:
    model_path: str = str(
        Path.home() / ".local" / "share" / "vosk" / "vosk-model-small-en-us-0.15"
    )
    sample_rate: int = 16000
    blocksize: int = 4000
    device: int | None = None


@dataclass(slots=True)
class InputConfig:
    backend: str = "auto"
    append_space: bool = True


@dataclass(slots=True)
class ServiceConfig:
    socket_path: str = _default_socket_path()
    notifications: bool = True


@dataclass(slots=True)
class AppConfig:
    speech: SpeechConfig
    input: InputConfig
    service: ServiceConfig


def default_config_path() -> Path:
    return Path.home() / ".config" / "voice-input" / "config.toml"


def _as_optional_int(raw: object) -> int | None:
    if raw in ("", None):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    raise ValueError(f"Invalid integer value: {raw!r}")


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()

    speech = SpeechConfig()
    input_cfg = InputConfig()
    service = ServiceConfig()

    if config_path.exists():
        data = tomllib.loads(config_path.read_text())
        speech_data = data.get("speech", {})
        input_data = data.get("input", {})
        service_data = data.get("service", {})

        speech.model_path = str(
            Path(speech_data.get("model_path", speech.model_path)).expanduser()
        )
        speech.sample_rate = int(speech_data.get("sample_rate", speech.sample_rate))
        speech.blocksize = int(speech_data.get("blocksize", speech.blocksize))
        speech.device = _as_optional_int(speech_data.get("device", speech.device))

        input_cfg.backend = str(input_data.get("backend", input_cfg.backend))
        input_cfg.append_space = bool(
            input_data.get("append_space", input_cfg.append_space)
        )

        socket_path = service_data.get("socket_path", service.socket_path)
        service.socket_path = (
            _default_socket_path()
            if socket_path in ("", None)
            else str(Path(socket_path).expanduser())
        )
        service.notifications = bool(
            service_data.get("notifications", service.notifications)
        )

    return AppConfig(speech=speech, input=input_cfg, service=service)
