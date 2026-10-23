"""Forwards engine events to the Qt main thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..engine import VoiceEngine


class EngineBridge(QObject):
    state = Signal(str)
    level = Signal(float)
    partial = Signal(str)
    typed = Signal(dict)
    command = Signal(str)
    countdown = Signal(int)
    notice = Signal(dict)
    backend = Signal(str)
    listening = Signal(dict)

    # Requests coming from the IPC socket or the tray.
    show_window = Signal(str)

    def __init__(self, engine: VoiceEngine) -> None:
        super().__init__()
        self.engine = engine
        engine.subscribe(self._relay)

    def _relay(self, event: str, payload: object) -> None:
        signal = getattr(self, event, None)
        if signal is not None:
            # Emitting from another thread is safe: Qt queues it to the receiver's thread.
            signal.emit(payload)
