"""Backends that type text into the focused window, with automatic fallback."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import subprocess
from typing import Callable


class SinkError(RuntimeError):
    pass


class KeysUnsupported(SinkError):
    pass


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "").lower()


def desktop_name() -> str:
    return os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def _run(args: list[str], stdin: str | None = None) -> None:
    try:
        proc = subprocess.run(
            args,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise SinkError(f"{args[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SinkError(f"{args[0]} timed out") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise SinkError(detail[-1] if detail else f"{args[0]} exited with {proc.returncode}")


def _split_combo(combo: str) -> tuple[list[str], str]:
    parts = combo.split("+")
    return parts[:-1], parts[-1]


class TextSink:
    name = "base"
    label = "Base"
    types_directly = True

    def send_text(self, text: str) -> None:
        raise NotImplementedError

    def send_key(self, key: str, count: int = 1) -> None:
        raise KeysUnsupported(f"{self.label} cannot press keys")


class WtypeSink(TextSink):
    name = "wtype"
    label = "wtype (Wayland)"

    def send_text(self, text: str) -> None:
        _run(["wtype", "-"], stdin=text)

    def send_key(self, key: str, count: int = 1) -> None:
        modifiers, base = _split_combo(key)
        args = ["wtype"]
        for _ in range(max(count, 1)):
            args += [x for m in modifiers for x in ("-M", m)]
            args += ["-k", base]
            args += [x for m in reversed(modifiers) for x in ("-m", m)]
        _run(args)


class XdotoolSink(TextSink):
    name = "xdotool"
    label = "xdotool (X11)"

    def send_text(self, text: str) -> None:
        _run(["xdotool", "type", "--delay", "1", "--file", "-"], stdin=text)

    def send_key(self, key: str, count: int = 1) -> None:
        _run(["xdotool", "key", "--delay", "4", "--repeat", str(max(count, 1)), key])


# Linux input event codes used by ydotool.
_YDOTOOL_CODES = {
    "ctrl": 29,
    "shift": 42,
    "alt": 56,
    "super": 125,
    "Return": 28,
    "BackSpace": 14,
    "Tab": 15,
    "Escape": 1,
    "a": 30,
    "z": 44,
    "v": 47,
}


class YdotoolSink(TextSink):
    name = "ydotool"
    label = "ydotool (any desktop)"

    def send_text(self, text: str) -> None:
        _run(["ydotool", "type", "--key-delay", "2", "--", text])

    def send_key(self, key: str, count: int = 1) -> None:
        modifiers, base = _split_combo(key)
        try:
            codes = [_YDOTOOL_CODES[m] for m in modifiers] + [_YDOTOOL_CODES[base]]
        except KeyError as exc:
            raise KeysUnsupported(f"ydotool has no mapping for {key}") from exc
        sequence: list[str] = []
        for _ in range(max(count, 1)):
            sequence += [f"{c}:1" for c in codes]
            sequence += [f"{c}:0" for c in reversed(codes)]
        _run(["ydotool", "key", *sequence])


class ClipboardSink(TextSink):
    name = "clipboard"
    label = "Clipboard (paste with Ctrl+V)"
    types_directly = False

    def __init__(self) -> None:
        self._wayland = session_type() == "wayland"

    def send_text(self, text: str) -> None:
        if self._wayland and _command_exists("wl-copy"):
            _run(["wl-copy", "--", text])
        elif _command_exists("xclip"):
            _run(["xclip", "-selection", "clipboard"], stdin=text)
        elif _command_exists("xsel"):
            _run(["xsel", "--clipboard", "--input"], stdin=text)
        else:
            raise SinkError("No clipboard tool found. Install wl-clipboard or xclip.")


_SINKS: dict[str, type[TextSink]] = {
    "wtype": WtypeSink,
    "xdotool": XdotoolSink,
    "ydotool": YdotoolSink,
    "clipboard": ClipboardSink,
}


def candidate_backends() -> list[str]:
    """Best-first list of backends worth trying on this desktop."""
    wayland = session_type() == "wayland"
    desktop = desktop_name()
    order: list[str] = []
    if wayland:
        # GNOME's compositor does not implement the virtual keyboard protocol wtype needs.
        if "gnome" not in desktop and _command_exists("wtype"):
            order.append("wtype")
        if _command_exists("ydotool"):
            order.append("ydotool")
    else:
        if _command_exists("xdotool"):
            order.append("xdotool")
        if _command_exists("ydotool"):
            order.append("ydotool")
    order.append("clipboard")
    return order


SwitchCallback = Callable[[TextSink, str], None]


class FallbackSink(TextSink):
    """Tries each backend in turn and sticks with the first one that works."""

    def __init__(self, sinks: list[TextSink], on_switch: SwitchCallback | None = None) -> None:
        if not sinks:
            raise ValueError("At least one sink is required")
        self.sinks = sinks
        self.index = 0
        self.on_switch = on_switch

    @property
    def current(self) -> TextSink:
        return self.sinks[self.index]

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.current.name

    @property
    def label(self) -> str:  # type: ignore[override]
        return self.current.label

    @property
    def types_directly(self) -> bool:  # type: ignore[override]
        return self.current.types_directly

    def _advance(self, error: Exception) -> bool:
        if self.index + 1 >= len(self.sinks):
            return False
        self.index += 1
        if self.on_switch is not None:
            self.on_switch(self.current, str(error))
        return True

    def send_text(self, text: str) -> None:
        while True:
            try:
                self.current.send_text(text)
                return
            except SinkError as exc:
                if not self._advance(exc):
                    raise

    def send_key(self, key: str, count: int = 1) -> None:
        while True:
            try:
                self.current.send_key(key, count)
                return
            except KeysUnsupported:
                raise
            except SinkError as exc:
                if not self._advance(exc):
                    raise


@dataclass(slots=True)
class SinkSelection:
    sink: FallbackSink
    reason: str


def build_sink(backend: str, on_switch: SwitchCallback | None = None) -> SinkSelection:
    backend = backend.lower().strip()

    if backend == "auto":
        names = candidate_backends()
        reason = f"auto-detected for {session_type() or 'unknown'} session"
    elif backend in _SINKS:
        names = [backend] if backend == "clipboard" else [backend, "clipboard"]
        reason = "chosen in settings"
    else:
        raise SinkError(f"Unsupported input backend: {backend}")

    sinks = [_SINKS[name]() for name in names]
    return SinkSelection(FallbackSink(sinks, on_switch=on_switch), reason)
