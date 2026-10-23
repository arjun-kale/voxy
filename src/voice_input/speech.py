from __future__ import annotations

import json
import math
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .config import SpeechConfig


TextCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
StateCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


class ModelMissingError(FileNotFoundError):
    pass


def rms_level(chunk: bytes) -> float:
    """Loudness of a 16-bit mono chunk mapped to 0..1 on a perceptual (dB) scale."""
    if len(chunk) % 2:
        chunk = chunk[:-1]
    if not chunk:
        return 0.0
    samples = memoryview(chunk).cast("h")
    step = max(1, len(samples) // 400)
    picked = samples[::step]
    total = 0
    for value in picked:
        total += value * value
    rms = math.sqrt(total / len(picked)) / 32768.0
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(rms)
    return max(0.0, min(1.0, (db + 55.0) / 50.0))


def model_is_valid(path: str | Path) -> bool:
    p = Path(path)
    return p.is_dir() and ((p / "am").is_dir() or (p / "final.mdl").exists() or (p / "conf").is_dir())


class StreamingSpeechRecognizer:
    """Owns the microphone and the Vosk model on a background thread.

    The microphone is only opened while dictating (or while the mic test runs),
    so the desktop's "microphone in use" indicator tells the truth.
    """

    def __init__(
        self,
        config: SpeechConfig,
        on_partial: TextCallback,
        on_final: TextCallback,
        on_level: LevelCallback | None = None,
        on_state: StateCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:
        self.config = config
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_level = on_level or (lambda _level: None)
        self.on_state = on_state or (lambda _state: None)
        self.on_error = on_error or (lambda _message: None)

        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=64)
        self._active = threading.Event()
        self._monitor = threading.Event()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self.backend = "unknown"


    def start(self) -> None:
        if not model_is_valid(self.config.model_path):
            raise ModelMissingError(
                f"Vosk model not found at {self.config.model_path}. "
                "Run `voice-input models download` or open the Voxy app."
            )
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="voxy-speech", daemon=True)
        self._thread.start()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def set_active(self, active: bool) -> None:
        if active:
            self._active.set()
        else:
            self._active.clear()
            self.on_partial("")
        self._wake.set()

    def set_monitor(self, monitor: bool) -> None:
        if monitor:
            self._monitor.set()
        else:
            self._monitor.clear()
        self._wake.set()

    def close(self) -> None:
        self._stop.set()
        self._active.clear()
        self._monitor.clear()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None


    def _wanted(self) -> bool:
        return self._active.is_set() or self._monitor.is_set()

    def _run(self) -> None:
        self.on_state("loading")
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            model = Model(self.config.model_path)
        except Exception as exc:  # pragma: no cover - depends on the model on disk
            self.on_state("error")
            self.on_error(f"Could not load the speech model: {exc}")
            return

        self._ready.set()
        self.on_state("ready")
        failures = 0

        while not self._stop.is_set():
            if not self._wanted():
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                continue

            try:
                self._listen(model, KaldiRecognizer)
                failures = 0
            except Exception as exc:
                failures += 1
                self.on_level(0.0)
                self.on_error(f"Microphone problem: {exc}")
                if failures >= 3:
                    self._active.clear()
                    self._monitor.clear()
                    self.on_state("mic_failed")
                    failures = 0
                self._stop.wait(timeout=min(2.0, 0.5 * failures))

    def _listen(self, model: object, recognizer_cls: type) -> None:
        recognizer = recognizer_cls(model, self.config.sample_rate)
        was_active = False
        self._drain_queue()

        with self._build_audio_source() as source:
            self.on_state("mic_open")
            while not self._stop.is_set() and self._wanted():
                active = self._active.is_set()
                if active and not was_active:
                    recognizer = recognizer_cls(model, self.config.sample_rate)
                elif was_active and not active:
                    self._flush(recognizer)
                was_active = active

                chunk = source.read()
                if chunk is None:
                    continue
                self.on_level(rms_level(chunk))
                if not active:
                    continue

                if recognizer.AcceptWaveform(chunk):
                    self._emit_final(recognizer.Result())
                else:
                    partial = json.loads(recognizer.PartialResult()).get("partial", "")
                    self.on_partial(partial.strip())

            if was_active:
                self._flush(recognizer)

        self.on_level(0.0)
        self.on_state("mic_closed")

    def _flush(self, recognizer: object) -> None:
        # Words spoken right before "stop" would otherwise be lost.
        self._emit_final(recognizer.FinalResult())  # type: ignore[attr-defined]

    def _emit_final(self, raw: str) -> None:
        transcript = json.loads(raw).get("text", "").strip()
        self.on_partial("")
        if transcript:
            self.on_final(transcript)

    def _drain_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                return

    def _build_audio_source(self) -> "_AudioSource":
        try:
            return _SoundDeviceSource(self)
        except Exception:
            return _ArecordSource(self)

    def _push_audio(self, chunk: bytes) -> None:
        try:
            self._audio_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                pass
            self._audio_queue.put_nowait(chunk)


class _AudioSource:
    def __enter__(self) -> "_AudioSource":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes | None:
        raise NotImplementedError


class _SoundDeviceSource(_AudioSource):
    def __init__(self, recognizer: StreamingSpeechRecognizer) -> None:
        import sounddevice as sd

        self.recognizer = recognizer
        self.stream = sd.RawInputStream(
            samplerate=recognizer.config.sample_rate,
            blocksize=recognizer.config.blocksize,
            device=recognizer.config.device,
            dtype="int16",
            channels=1,
            callback=self._audio_callback,
        )
        recognizer.backend = "sounddevice"

    def __enter__(self) -> "_SoundDeviceSource":
        self.stream.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stream.stop()
        self.stream.close()

    def _audio_callback(self, indata: bytes, frames: int, time_info: object, status: object) -> None:
        # An overflow flag still comes with usable audio, so keep it rather than lose words.
        del frames, time_info, status
        self.recognizer._push_audio(bytes(indata))

    def read(self) -> bytes | None:
        try:
            return self.recognizer._audio_queue.get(timeout=0.2)
        except queue.Empty:
            return None


class _ArecordSource(_AudioSource):
    def __init__(self, recognizer: StreamingSpeechRecognizer) -> None:
        self.recognizer = recognizer
        self.chunk_bytes = recognizer.config.blocksize * 2
        self.proc: subprocess.Popen[bytes] | None = None

        if shutil.which("arecord") is None:
            raise RuntimeError("No audio capture backend is available. Install PortAudio or arecord.")
        recognizer.backend = "arecord"

    def __enter__(self) -> "_ArecordSource":
        self.proc = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-c", "1", "-r", str(self.recognizer.config.sample_rate), "-t", "raw"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)

    def read(self) -> bytes | None:
        if self.proc is None or self.proc.stdout is None:
            return None
        chunk = self.proc.stdout.read1(self.chunk_bytes)
        if not chunk:
            if self.proc.poll() is not None:
                raise RuntimeError("arecord stopped unexpectedly")
            return None
        return chunk


def list_input_devices() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return []
    result = []
    for index, device in enumerate(devices):
        if device.get("max_input_channels", 0) > 0:
            result.append((index, str(device.get("name", f"Device {index}"))))
    return result
