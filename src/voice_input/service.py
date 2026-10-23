from __future__ import annotations

import asyncio
import signal
from typing import Callable

from .config import AppConfig, load_config
from .engine import VoiceEngine
from .ipc import CommandServer
from .notifier import DesktopNotifier


ExtraActions = dict[str, Callable[[], None]]


def make_command_handler(engine: VoiceEngine, extra: ExtraActions | None = None):
    extra = extra or {}

    async def handle(payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action", ""))
        if action == "toggle":
            engine.toggle()
        elif action == "start":
            engine.set_listening(True)
        elif action == "stop":
            engine.set_listening(False)
        elif action == "status":
            pass
        elif action in extra:
            extra[action]()
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}
        return engine.status()

    return handle


def attach_notifications(engine: VoiceEngine, notifier: DesktopNotifier) -> None:
    def on_event(event: str, payload: object) -> None:
        if event == "listening":
            active = payload["active"]  # type: ignore[index]
            notifier.show("Voxy", "Listening…" if active else "Stopped")
        elif event == "notice":
            notifier.show("Voxy", payload["message"])  # type: ignore[index]
        elif event == "state" and payload == "needs_model":
            notifier.show("Voxy", "No speech model yet. Run `voice-input models download`.")

    engine.subscribe(on_event)


async def run_daemon(config_path: str | None = None, config: AppConfig | None = None) -> None:
    config = config or load_config(config_path)
    engine = VoiceEngine(config)
    if config.service.notifications:
        attach_notifications(engine, DesktopNotifier())

    server = CommandServer(config.service.socket_path, make_command_handler(engine))
    engine.start()
    await server.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    try:
        await stop.wait()
    finally:
        engine.close()
        await server.close()
