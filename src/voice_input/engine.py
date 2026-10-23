"""Dictation engine used by both the daemon and the desktop app."""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from . import sounds
from .config import AppConfig
from .history import History
from .speech import ModelMissingError, StreamingSpeechRecognizer
from .textproc import Control, PressKey, TextProcessor, TypeText
from .typing_backends import KeysUnsupported, SinkError, SinkSelection, TextSink, build_sink


Listener = Callable[[str, object], None]

# Events emitted to listeners:
#   state      str    one of needs_model, loading, ready, listening, error
#   level      float  microphone loudness 0..1 (while the mic is open)
#   partial    str    words recognised so far in the current phrase
#   typed      dict   {"text": str, "mode": "typed" | "copied"}
#   command    str    a voice command that was run
#   countdown  int    seconds until auto-stop (0 hides the warning)
#   notice     dict   {"level": "info" | "warning" | "error", "message": str}
#   backend    str    label of the typing method now in use

VOICE_THRESHOLD = 0.32


class VoiceEngine:
    def __init__(
        self,
        config: AppConfig,
        history: History | None = None,
        *,
        recognizer_factory: Callable[..., StreamingSpeechRecognizer] = StreamingSpeechRecognizer,
        sink_factory: Callable[..., SinkSelection] = build_sink,
    ) -> None:
        self.config = config
        self.history = history or History(
            limit=config.behavior.history_limit,
            enabled=config.behavior.history,
        )
        self._recognizer_factory = recognizer_factory
        self._sink_factory = sink_factory
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()

        self.state = "loading"
        self.listening = False
        self.mic_test = False
        # In preview mode results are reported but not typed (used by the setup wizard).
        self.preview = False
        self.partial_text = ""
        self.last_error = ""
        self._last_voice = 0.0
        self._countdown = 0

        self.processor = TextProcessor(config.text, append_space=config.input.append_space)
        self._applied_backend = config.input.backend
        self._applied_speech: tuple[object, ...] = ()
        self.selection = self._build_sink()
        self.recognizer: StreamingSpeechRecognizer | None = None

        self._outbox: queue.Queue[object] = queue.Queue()
        self._output_thread = threading.Thread(target=self._output_loop, name="voxy-output", daemon=True)
        self._output_thread.start()


    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def _emit(self, event: str, payload: object = None) -> None:
        for listener in list(self._listeners):
            try:
                listener(event, payload)
            except Exception:  # pragma: no cover - a broken listener must not stop dictation
                pass

    def _notice(self, level: str, message: str) -> None:
        self._emit("notice", {"level": level, "message": message})

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self._emit("state", state)


    def _build_sink(self) -> SinkSelection:
        self._applied_backend = self.config.input.backend
        try:
            return self._sink_factory(self.config.input.backend, on_switch=self._on_sink_switch)
        except SinkError as exc:
            self._notice("warning", f"{exc}. Falling back to automatic typing.")
            return self._sink_factory("auto", on_switch=self._on_sink_switch)

    def _on_sink_switch(self, sink: TextSink, reason: str) -> None:
        self._emit("backend", sink.label)
        if sink.types_directly:
            self._notice("warning", f"Typing with {sink.label} instead ({reason}).")
        else:
            self._notice(
                "warning",
                "This desktop blocked direct typing, so Voxy will copy text to the "
                "clipboard. Press Ctrl+V to paste, or run `voice-input doctor` for a fix.",
            )

    def start(self) -> None:
        recognizer = self._recognizer_factory(
            config=self.config.speech,
            on_partial=self._on_partial,
            on_final=self._on_final,
            on_level=self._on_level,
            on_state=self._on_recognizer_state,
            on_error=self._on_recognizer_error,
        )
        with self._lock:
            self.recognizer = recognizer
            self._applied_speech = self._speech_settings()
        # Set before starting: the recogniser thread may report "ready" immediately.
        self._set_state("loading")
        try:
            recognizer.start()
        except ModelMissingError as exc:
            self.last_error = str(exc)
            self._set_state("needs_model")

    def _speech_settings(self) -> tuple[object, ...]:
        s = self.config.speech
        return (s.model_path, s.device, s.sample_rate, s.blocksize)

    def reload(self, config: AppConfig | None = None) -> None:
        """Applies new settings, restarting only what has to restart.

        Settings screens edit the config object in place, so changes are
        detected against what was last applied rather than the old object.
        """
        if config is not None:
            self.config = config

        # Update in place so a settings change mid-sentence keeps capitalisation context.
        self.processor.config = self.config.text
        self.processor.append_space = self.config.input.append_space
        self.history.enabled = self.config.behavior.history
        self.history.limit = self.config.behavior.history_limit
        if self.config.input.backend != self._applied_backend:
            self.selection = self._build_sink()
            self._emit("backend", self.selection.sink.label)

        if self._speech_settings() != self._applied_speech or self.state in ("needs_model", "error"):
            self.set_listening(False)
            self.set_mic_test(False)
            if self.recognizer is not None:
                self.recognizer.close()
            self.start()

    def close(self) -> None:
        self.set_listening(False)
        if self.recognizer is not None:
            self.recognizer.close()
        self._outbox.put(None)


    def toggle(self) -> bool:
        return self.set_listening(not self.listening)

    def set_listening(self, active: bool, reason: str = "") -> bool:
        with self._lock:
            if active and self.state in ("needs_model", "error"):
                self._notice("error", self.last_error or "Voxy is not ready yet.")
                return False
            if active == self.listening:
                return self.listening
            self.listening = active
            self.partial_text = ""
            self._last_voice = time.monotonic()
            self._countdown = 0
            if active:
                self.processor.reset()
            if self.recognizer is not None:
                self.recognizer.set_active(active)

        if self.config.behavior.sounds:
            sounds.play("start" if active else "stop")
        self._emit("countdown", 0)
        self._set_state("listening" if active else "ready" if self._recognizer_ready() else self.state)
        self._emit("listening", {"active": active, "reason": reason})
        return active

    def set_mic_test(self, active: bool) -> None:
        self.mic_test = active
        if self.recognizer is not None:
            self.recognizer.set_monitor(active)

    def _recognizer_ready(self) -> bool:
        return self.recognizer is not None and self.recognizer.ready


    def _on_recognizer_state(self, state: str) -> None:
        if state == "loading":
            self._set_state("loading")
        elif state == "ready":
            self._set_state("listening" if self.listening else "ready")
        elif state == "error":
            self._set_state("error")
        elif state == "mic_failed":
            self.set_listening(False, reason="mic")
            self._notice("error", "Voxy could not use the microphone. Check Settings → Microphone.")
            if self.config.behavior.sounds:
                sounds.play("error")

    def _on_recognizer_error(self, message: str) -> None:
        self.last_error = message
        self._notice("error", message)

    def _on_partial(self, text: str) -> None:
        self.partial_text = text
        if text:
            self._last_voice = time.monotonic()
        self._emit("partial", text)

    def _on_level(self, level: float) -> None:
        self._emit("level", level)
        if not self.listening:
            return
        now = time.monotonic()
        if level >= VOICE_THRESHOLD:
            self._last_voice = now

        limit = self.config.behavior.auto_stop_seconds
        if limit <= 0:
            return
        remaining = limit - (now - self._last_voice)
        if remaining <= 0:
            self.set_listening(False, reason="silence")
            self._notice("info", f"Stopped after {limit} seconds of silence.")
            return
        countdown = int(remaining) + 1 if remaining <= 5 else 0
        if countdown != self._countdown:
            self._countdown = countdown
            self._emit("countdown", countdown)

    def _on_final(self, raw: str) -> None:
        result = self.processor.process(raw)
        if result.actions:
            self._outbox.put((result.actions, result.display, result.command))


    def _output_loop(self) -> None:
        while True:
            item = self._outbox.get()
            if item is None:
                return
            actions, display, command = item  # type: ignore[misc]
            self._perform(actions, display, command)

    def _perform(self, actions: list[object], display: str, command: str | None) -> None:
        sink = self.selection.sink
        if self.preview:
            if any(isinstance(a, Control) and a.name == "stop" for a in actions):
                self.set_listening(False, reason="voice")
            if display:
                self._emit("typed", {"text": display, "mode": "preview"})
            if command:
                self._emit("command", command)
            return

        for action in actions:
            try:
                if isinstance(action, TypeText):
                    sink.send_text(action.text)
                elif isinstance(action, PressKey):
                    sink.send_key(action.key, action.count)
                elif isinstance(action, Control) and action.name == "stop":
                    self.set_listening(False, reason="voice")
            except KeysUnsupported:
                self._notice(
                    "warning",
                    "Voice commands that press keys need wtype, xdotool or ydotool.",
                )
            except SinkError as exc:
                self._notice("error", f"Could not type the text: {exc}")
                return

        if display:
            self.history.add(display)
            mode = "typed" if sink.types_directly else "copied"
            self._emit("typed", {"text": display, "mode": mode})
        if command:
            self._emit("command", command)

    def type_text(self, text: str) -> None:
        """Re-inserts text, e.g. from the history window."""
        self._outbox.put(([TypeText(text)], "", None))


    def status(self) -> dict[str, object]:
        stats = self.history.stats()
        return {
            "ok": True,
            "state": self.state,
            "active": self.listening,
            "partial": self.partial_text,
            "backend": self.selection.sink.name,
            "backend_label": self.selection.sink.label,
            "backend_reason": self.selection.reason,
            "socket_path": self.config.service.socket_path,
            "model_path": self.config.speech.model_path,
            "words_today": stats.today_words,
            "words_total": stats.total_words,
            "error": self.last_error if self.state in ("needs_model", "error") else "",
        }
