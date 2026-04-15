from __future__ import annotations

import json
import shutil
import queue
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .config import SpeechConfig


PartialCallback = Callable[[str], None]
FinalCallback = Callable[[str], None]


class StreamingSpeechRecognizer:
    def __init__(
        self,
        config: SpeechConfig,
        on_partial: PartialCallback,
        on_final: FinalCallback,
    ) -> None:
        self.config = config
        self.on_partial = on_partial
        self.on_final = on_final

        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
        self._active = threading.Event()
        self._stop = threading.Event()
        self._reset = threading.Event()
        self._thread: threading.Thread | None = None
        self.backend = "unknown"

    def start(self) -> None:
        model_path = Path(self.config.model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {model_path}. Update config.toml first."
            )

        if self._thread is not None:
            return

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_active(self, active: bool) -> None:
        if active:
            self._clear_audio_queue()
            self._reset.set()
            self._active.set()
        else:
            self._active.clear()
            self._clear_audio_queue()
            self.on_partial("")

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _clear_audio_queue(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                return

    def _run(self) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model = Model(self.config.model_path)
        recognizer = KaldiRecognizer(model, self.config.sample_rate)
        source = self._build_audio_source()

        with source:
            while not self._stop.is_set():
                chunk = source.read()
                if chunk is None:
                    continue

                if self._reset.is_set():
                    recognizer = KaldiRecognizer(model, self.config.sample_rate)
                    self._reset.clear()

                if recognizer.AcceptWaveform(chunk):
                    result = json.loads(recognizer.Result())
                    transcript = result.get("text", "").strip()
                    if transcript:
                        self.on_final(transcript)
                        self.on_partial("")
                else:
                    result = json.loads(recognizer.PartialResult())
                    self.on_partial(result.get("partial", "").strip())

    def _build_audio_source(self) -> "_AudioSource":
        try:
            import sounddevice  # noqa: F401
        except Exception:
            return _ArecordSource(self)

        try:
            return _SoundDeviceSource(self)
        except OSError:
            return _ArecordSource(self)

    def _push_audio(self, chunk: bytes) -> None:
        if not self._active.is_set():
            return
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
        self.sd = sd
        self.stream = self.sd.RawInputStream(
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

    def _audio_callback(
        self,
        indata: bytes,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        del frames, time_info
        if status:
            return
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
            raise RuntimeError(
                "No audio capture backend is available. Install PortAudio or arecord."
            )

        recognizer.backend = "arecord"

    def __enter__(self) -> "_ArecordSource":
        self.proc = subprocess.Popen(
            [
                "arecord",
                "-q",
                "-f",
                "S16_LE",
                "-c",
                "1",
                "-r",
                str(self.recognizer.config.sample_rate),
                "-t",
                "raw",
            ],
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
        if not self.recognizer._active.is_set():
            try:
                self.proc.stdout.read1(self.chunk_bytes)
            except Exception:
                return None
            return None

        chunk = self.proc.stdout.read1(self.chunk_bytes)
        if not chunk:
            return None
        return chunk
