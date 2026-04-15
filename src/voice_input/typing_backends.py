from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from .notifier import DesktopNotifier


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "").lower()


def normalize_text(text: str, append_space: bool = True) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""

    replacements = [
        (" question mark", "?"),
        (" exclamation mark", "!"),
        (" full stop", "."),
        (" period", "."),
        (" comma", ","),
        (" new line", "\n"),
    ]

    normalized = f" {cleaned} "
    for source, target in replacements:
        normalized = normalized.replace(source + " ", target + " ")

    normalized = normalized.strip()
    if append_space and normalized and not normalized.endswith(("\n", " ")):
        normalized += " "
    return normalized


class TextSink:
    name = "base"

    def send(self, text: str) -> None:
        raise NotImplementedError


class WtypeSink(TextSink):
    name = "wtype"

    def send(self, text: str) -> None:
        subprocess.run(["wtype", text], check=True)


class XdotoolSink(TextSink):
    name = "xdotool"

    def send(self, text: str) -> None:
        subprocess.run(["xdotool", "type", "--delay", "1", text], check=True)


class ClipboardSink(TextSink):
    name = "clipboard"

    def __init__(self, notifier: DesktopNotifier | None = None) -> None:
        self.notifier = notifier
        self._wayland = _session_type() == "wayland"
        self._wl_copy = shutil.which("wl-copy")
        self._xclip = shutil.which("xclip")

    def send(self, text: str) -> None:
        if self._wayland and self._wl_copy:
            subprocess.run(["wl-copy"], input=text, text=True, check=True)
        elif self._xclip:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                check=True,
            )
        else:
            raise RuntimeError(
                "No clipboard backend is available. Install wl-clipboard or xclip."
            )

        if self.notifier is not None:
            self.notifier.show("Voice Input", "Transcript copied to clipboard")


@dataclass(slots=True)
class SinkSelection:
    sink: TextSink
    reason: str


def build_sink(backend: str, notifier: DesktopNotifier | None = None) -> SinkSelection:
    backend = backend.lower()
    session = _session_type()

    if backend == "wtype":
        if not _command_exists("wtype"):
            raise RuntimeError("Configured backend 'wtype' is not installed.")
        return SinkSelection(WtypeSink(), "configured backend")

    if backend == "xdotool":
        if not _command_exists("xdotool"):
            raise RuntimeError("Configured backend 'xdotool' is not installed.")
        return SinkSelection(XdotoolSink(), "configured backend")

    if backend == "clipboard":
        return SinkSelection(ClipboardSink(notifier), "configured backend")

    if backend != "auto":
        raise RuntimeError(f"Unsupported input backend: {backend}")

    if session == "wayland" and _command_exists("wtype"):
        return SinkSelection(WtypeSink(), "auto-detected Wayland typing via wtype")

    if session != "wayland" and _command_exists("xdotool"):
        return SinkSelection(XdotoolSink(), "auto-detected X11 typing via xdotool")

    return SinkSelection(
        ClipboardSink(notifier),
        "clipboard fallback because no direct typing tool is installed",
    )
