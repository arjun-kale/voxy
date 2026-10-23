"""Integration with the Linux desktop: launcher, autostart and global shortcut."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from .typing_backends import desktop_name


ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#9B7BFF"/>
      <stop offset="1" stop-color="#5B3DF5"/>
    </linearGradient>
  </defs>
  <rect x="16" y="16" width="224" height="224" rx="60" fill="url(#bg)"/>
  <g fill="#fff">
    <rect x="58" y="108" width="20" height="40" rx="10"/>
    <rect x="90" y="84" width="20" height="88" rx="10"/>
    <rect x="122" y="60" width="20" height="136" rx="10"/>
    <rect x="154" y="88" width="20" height="80" rx="10"/>
    <rect x="186" y="112" width="20" height="32" rx="10"/>
  </g>
</svg>
"""

GNOME_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_KEY_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/voxy/"


def _xdg(name: str, fallback: str) -> Path:
    return Path(os.environ.get(name) or Path.home() / fallback)


def cli_path() -> str:
    """Absolute path of the voice-input command, preferring the active venv."""
    beside = Path(sys.executable).parent / "voice-input"
    if beside.exists():
        return str(beside)
    found = shutil.which("voice-input")
    return found or f"{sys.executable} -m voice_input"


def _quoted_cli() -> str:
    path = cli_path()
    return path if " -m " in path else shlex.quote(path)


def icon_path() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "icons/hicolor/scalable/apps/voxy.svg"


def _desktop_entry(args: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Voxy\n"
        "GenericName=Voice Typing\n"
        "Comment=Type with your voice, privately and offline\n"
        f"Exec={_quoted_cli()} {args}\n"
        "Icon=voxy\n"
        "Terminal=false\n"
        "Categories=Utility;Accessibility;\n"
        "Keywords=voice;dictation;speech;microphone;typing;\n"
        "StartupNotify=false\n"
    )


def install_launcher() -> Path:
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_text(ICON_SVG)
    entry = _xdg("XDG_DATA_HOME", ".local/share") / "applications" / "voxy.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(_desktop_entry("app"))
    return entry


def autostart_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / "voxy.desktop"


def autostart_enabled() -> bool:
    return autostart_path().exists()


def set_autostart(enabled: bool) -> None:
    path = autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_desktop_entry("app --background") + "X-GNOME-Autostart-enabled=true\n")
    else:
        path.unlink(missing_ok=True)


_QT_TO_GTK = {"ctrl": "<Control>", "alt": "<Alt>", "shift": "<Shift>", "meta": "<Super>", "super": "<Super>"}
_GTK_LABELS = {"Control": "Ctrl", "Primary": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Super": "Super"}


def qt_to_gtk(sequence: str) -> str:
    """'Ctrl+Alt+Space' → '<Control><Alt>space'."""
    parts = [p for p in sequence.split("+") if p]
    if not parts:
        return ""
    *mods, key = parts
    prefix = "".join(_QT_TO_GTK.get(m.strip().lower(), "") for m in mods)
    key = key.strip()
    return prefix + (key.lower() if len(key) > 1 or key.isalpha() else key)


def shortcut_label(accel: str) -> str:
    """'<Control><Alt>space' → 'Ctrl + Alt + Space'."""
    parts: list[str] = []
    rest = accel
    while rest.startswith("<") and ">" in rest:
        name, rest = rest[1:].split(">", 1)
        parts.append(_GTK_LABELS.get(name, name))
    if rest:
        parts.append(rest.capitalize() if len(rest) > 1 else rest.upper())
    return " + ".join(parts)


def can_register_shortcut() -> bool:
    return "gnome" in desktop_name() or "unity" in desktop_name() or "budgie" in desktop_name()


def _gsettings(*args: str) -> str:
    proc = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5, check=True)
    return proc.stdout.strip()


def register_shortcut(accel: str) -> tuple[bool, str]:
    """Binds the shortcut to `voice-input toggle`. Returns (success, message)."""
    if not shutil.which("gsettings"):
        return False, manual_shortcut_help(accel)
    try:
        raw = _gsettings("get", GNOME_SCHEMA, "custom-keybindings")
        current = ast.literal_eval(raw.removeprefix("@as ").strip() or "[]")
        if GNOME_KEY_PATH not in current:
            current.append(GNOME_KEY_PATH)
            _gsettings("set", GNOME_SCHEMA, "custom-keybindings", str(current))
        schema = f"{GNOME_SCHEMA}.custom-keybinding:{GNOME_KEY_PATH}"
        _gsettings("set", schema, "name", "Voxy dictation")
        _gsettings("set", schema, "command", f"{cli_path()} toggle")
        _gsettings("set", schema, "binding", accel)
    except (subprocess.SubprocessError, OSError, ValueError, SyntaxError) as exc:
        return False, f"Could not set the shortcut automatically ({exc}).\n\n" + manual_shortcut_help(accel)
    return True, f"Press {shortcut_label(accel)} anywhere to start or stop dictation."


def manual_shortcut_help(accel: str) -> str:
    return (
        "Open your system Settings → Keyboard → Custom Shortcuts and add:\n"
        f"  Name: Voxy dictation\n"
        f"  Command: {cli_path()} toggle\n"
        f"  Shortcut: {shortcut_label(accel)}"
    )
