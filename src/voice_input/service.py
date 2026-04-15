from __future__ import annotations

import asyncio
import signal
import threading

from .config import AppConfig, load_config
from .ipc import CommandServer
from .notifier import DesktopNotifier
from .speech import StreamingSpeechRecognizer
from .typing_backends import SinkSelection, build_sink, normalize_text


class VoiceInputDaemon:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.active = False
        self.partial_text = ""
        self.lock = threading.Lock()
        self.notifier = DesktopNotifier(enabled=config.service.notifications)
        self.sink_selection: SinkSelection = build_sink(
            config.input.backend,
            notifier=self.notifier,
        )
        self.recognizer = StreamingSpeechRecognizer(
            config=config.speech,
            on_partial=self._handle_partial,
            on_final=self._handle_final,
        )
        self.server = CommandServer(config.service.socket_path, self._handle_command)
        self.shutdown_event = asyncio.Event()

    async def start(self) -> None:
        self.recognizer.start()
        await self.server.start()
        self.notifier.show(
            "Voice Input",
            f"Daemon ready using {self.sink_selection.sink.name}",
        )

    async def close(self) -> None:
        self.recognizer.close()
        await self.server.close()

    def set_active(self, active: bool) -> None:
        with self.lock:
            self.active = active
            self.partial_text = ""
            self.recognizer.set_active(active)

        state = "Listening" if active else "Stopped"
        self.notifier.show("Voice Input", state)

    def _handle_partial(self, text: str) -> None:
        with self.lock:
            self.partial_text = text

    def _handle_final(self, text: str) -> None:
        normalized = normalize_text(text, append_space=self.config.input.append_space)
        if not normalized:
            return
        try:
            self.sink_selection.sink.send(normalized)
        except Exception as exc:  # pragma: no cover - runtime integration failure
            self.notifier.show("Voice Input", f"Text injection failed: {exc}")

    async def _handle_command(self, payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action", ""))

        if action == "toggle":
            self.set_active(not self.active)
        elif action == "start":
            self.set_active(True)
        elif action == "stop":
            self.set_active(False)
        elif action == "status":
            pass
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}

        return {
            "ok": True,
            "active": self.active,
            "partial": self.partial_text,
            "backend": self.sink_selection.sink.name,
            "backend_reason": self.sink_selection.reason,
            "socket_path": self.config.service.socket_path,
            "model_path": self.config.speech.model_path,
        }

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.shutdown_event.set)

        await self.shutdown_event.wait()


async def run_daemon(config_path: str | None = None) -> None:
    daemon = VoiceInputDaemon(load_config(config_path))
    await daemon.start()
    try:
        await daemon.run_forever()
    finally:
        await daemon.close()
