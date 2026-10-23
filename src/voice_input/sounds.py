"""Start/stop sound cues, generated on first use."""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import struct
import subprocess
import wave

from .config import data_dir


_RATE = 44100

# (frequency Hz, start s, duration s) for each note.
_CHIMES: dict[str, list[tuple[float, float, float]]] = {
    "start": [(659.25, 0.0, 0.16), (987.77, 0.07, 0.22)],
    "stop": [(987.77, 0.0, 0.14), (659.25, 0.06, 0.2)],
    "error": [(330.0, 0.0, 0.18), (262.0, 0.12, 0.24)],
}


def _render(notes: list[tuple[float, float, float]], volume: float = 0.22) -> bytes:
    length = max(start + dur for _f, start, dur in notes) + 0.05
    samples = [0.0] * int(length * _RATE)
    for freq, start, dur in notes:
        offset = int(start * _RATE)
        count = int(dur * _RATE)
        for i in range(count):
            t = i / _RATE
            attack = min(1.0, t / 0.008)
            decay = math.exp(-5.5 * t / dur)
            tone = math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)
            samples[offset + i] += tone * attack * decay
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = volume * 32767 / peak
    return b"".join(struct.pack("<h", int(s * scale)) for s in samples)


def sound_path(name: str) -> Path:
    path = data_dir() / "sounds" / f"{name}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(_RATE)
            wav.writeframes(_render(_CHIMES[name]))
        tmp.replace(path)
    return path


_PLAYERS = (("pw-play",), ("paplay",), ("aplay", "-q"))


def play(name: str) -> None:
    try:
        path = sound_path(name)
    except OSError:
        return
    for player in _PLAYERS:
        if shutil.which(player[0]):
            subprocess.Popen(
                [*player, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
