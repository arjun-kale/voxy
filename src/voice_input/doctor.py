"""Environment checks used by `voxy doctor` and the Health page."""

from __future__ import annotations

from dataclasses import dataclass
import shutil

from .config import AppConfig
from .models import describe_model
from .speech import list_input_devices, model_is_valid
from .typing_backends import candidate_backends, desktop_name, session_type


OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(slots=True)
class Check:
    title: str
    status: str
    detail: str
    fix: str = ""


def portaudio_available() -> bool:
    try:
        import sounddevice  # noqa: F401
    except OSError:
        return False
    return True


def _install_hint(package: str) -> str:
    if shutil.which("apt"):
        return f"sudo apt install {package}"
    if shutil.which("dnf"):
        return f"sudo dnf install {package}"
    if shutil.which("pacman"):
        return f"sudo pacman -S {package}"
    return f"Install {package} with your package manager"


def run_checks(config: AppConfig) -> list[Check]:
    checks: list[Check] = []

    model = config.speech.model_path
    if model_is_valid(model):
        checks.append(Check("Speech model", OK, describe_model(model)))
    else:
        checks.append(
            Check(
                "Speech model",
                FAIL,
                "No speech model is installed yet.",
                "Open Voxy → Settings → Language, or run `voice-input models download`.",
            )
        )

    devices = list_input_devices()
    if devices:
        checks.append(Check("Microphone", OK, f"{len(devices)} input device(s) found"))
    elif portaudio_available():
        checks.append(
            Check(
                "Microphone",
                FAIL,
                "No microphone detected.",
                "Plug in a microphone or headset, or check your system Sound settings.",
            )
        )
    elif shutil.which("arecord"):
        checks.append(Check("Microphone", WARN, "Using arecord; PortAudio was not found.", _install_hint("libportaudio2")))
    else:
        checks.append(Check("Microphone", FAIL, "No way to record audio.", _install_hint("libportaudio2")))

    session = session_type() or "unknown"
    desktop = desktop_name() or "unknown desktop"
    backends = candidate_backends()
    best = backends[0]
    if best == "clipboard":
        if session == "wayland":
            fix = (
                "Install ydotool and start its service (sudo systemctl enable --now ydotool)"
                if "gnome" in desktop
                else _install_hint("wtype")
            )
        else:
            fix = _install_hint("xdotool")
        checks.append(
            Check(
                "Typing",
                WARN,
                f"Text will be copied to the clipboard on {session} ({desktop}); you paste with Ctrl+V.",
                fix,
            )
        )
    else:
        checks.append(Check("Typing", OK, f"Types directly with {best} on {session} ({desktop})"))

    if session == "wayland" and not shutil.which("wl-copy"):
        checks.append(Check("Clipboard", WARN, "wl-copy is missing, so the clipboard fallback cannot work.", _install_hint("wl-clipboard")))
    elif session != "wayland" and not (shutil.which("xclip") or shutil.which("xsel")):
        checks.append(Check("Clipboard", WARN, "xclip is missing, so the clipboard fallback cannot work.", _install_hint("xclip")))
    else:
        checks.append(Check("Clipboard", OK, "Clipboard fallback available"))

    if any(shutil.which(p) for p in ("pw-play", "paplay", "aplay")):
        checks.append(Check("Sound cues", OK, "Start and stop chimes can play"))
    else:
        checks.append(Check("Sound cues", WARN, "No audio player found, so chimes are silent.", _install_hint("pulseaudio-utils")))

    return checks
