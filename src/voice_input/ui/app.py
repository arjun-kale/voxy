"""Desktop app entry point: tray, overlay, main window and setup wizard."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import desktop
from ..config import AppConfig, load_config, save_config
from ..engine import VoiceEngine
from ..ipc import AlreadyRunningError, CommandServer, daemon_running, send_command
from ..models import DownloadCancelled, ModelInfo, download_model
from ..service import make_command_handler
from . import icons
from .bridge import EngineBridge
from .theme import apply_app_font, build_palette, set_current, stylesheet


def _choose_platform() -> None:
    # Wayland does not let apps place or keep windows on top, which the floating
    # bar needs. XWayland does, so prefer it unless the user chose otherwise.
    if os.environ.get("QT_QPA_PLATFORM") or os.environ.get("VOXY_NATIVE_WAYLAND"):
        return
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def run_app(config_path: str | None = None, background: bool = False) -> int:
    config = load_config(config_path)
    if daemon_running(config.service.socket_path):
        asyncio.run(send_command(config.service.socket_path, "show"))
        print("Voxy is already running; bringing it to the front.")
        return 0

    _choose_platform()

    QApplication.setApplicationName("Voxy")
    QApplication.setDesktopFileName("voxy")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    controller = Controller(app, config)
    try:
        controller.start_ipc()
    except AlreadyRunningError as exc:
        print(exc, file=sys.stderr)
        return 1
    controller.boot(background=background)

    # Quit cleanly on logout or `kill`. Qt blocks Python signal handlers while
    # idle, so wake the interpreter regularly to let them run.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: app.quit())
    heartbeat = QTimer()
    heartbeat.start(300)
    heartbeat.timeout.connect(lambda: None)

    code = app.exec()
    controller.shutdown()
    return code


class DownloadTask(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info: ModelInfo) -> None:
        super().__init__()
        self.info = info
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"voxy-download-{info.id}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        try:
            path = download_model(self.info, progress=self.progress.emit, cancel=self._cancel)
        except DownloadCancelled:
            self.failed.emit("cancelled")
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.done.emit(str(path))


class Controller(QObject):
    """Owns the engine and every window; pages talk to Voxy through it."""

    def __init__(self, app: QApplication, config: AppConfig) -> None:
        super().__init__()
        self.app = app
        self.config = config
        self.engine = VoiceEngine(config)
        self.bridge = EngineBridge(self.engine)
        self.downloads: dict[str, DownloadTask] = {}
        self.window = None
        self.wizard = None
        self.overlay = None
        self.tray: QSystemTrayIcon | None = None
        self._told_about_tray = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: CommandServer | None = None

        apply_app_font()
        self.apply_theme(rebuild=False)
        app.setWindowIcon(icons.app_icon())


    def start_ipc(self) -> None:
        ready = threading.Event()
        errors: list[BaseException] = []
        extra = {
            "show": lambda: self.bridge.show_window.emit("home"),
            "settings": lambda: self.bridge.show_window.emit("settings"),
            "history": lambda: self.bridge.show_window.emit("history"),
        }

        def serve() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._server = CommandServer(self.config.service.socket_path, make_command_handler(self.engine, extra))
            try:
                loop.run_until_complete(self._server.start())
            except BaseException as exc:
                errors.append(exc)
                ready.set()
                return
            ready.set()
            loop.run_forever()
            loop.run_until_complete(self._server.close())
            loop.close()

        threading.Thread(target=serve, name="voxy-ipc", daemon=True).start()
        ready.wait(timeout=5)
        if errors:
            raise errors[0]

    def boot(self, background: bool) -> None:
        from .overlay import Overlay

        self.overlay = Overlay(self.config.appearance, on_stop=lambda: self.engine.set_listening(False))
        b = self.bridge
        b.listening.connect(self._on_listening)
        b.level.connect(self.overlay.on_level)
        b.partial.connect(self.overlay.on_partial)
        b.typed.connect(self.overlay.on_typed)
        b.countdown.connect(self.overlay.on_countdown)
        b.notice.connect(self._on_notice)
        b.state.connect(self._on_state)
        b.show_window.connect(self.show_page)

        self._build_tray()
        self.engine.start()
        self._on_state(self.engine.state)

        if not self.config.app.onboarded or self.engine.state == "needs_model":
            self.open_onboarding()
        elif not background or self.tray is None:
            self.show_page("home")

    def shutdown(self) -> None:
        for task in self.downloads.values():
            task.cancel()
        self.engine.close()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def quit(self) -> None:
        self.app.quit()


    def save(self) -> None:
        save_config(self.config)
        self.engine.reload(self.config)
        if self.overlay is not None:
            self.overlay.apply_appearance(self.config.appearance)

    def apply_theme(self, rebuild: bool = True) -> None:
        palette = build_palette(self.config.appearance.theme, self.config.appearance.accent)
        set_current(palette)
        self.app.setStyleSheet(stylesheet(palette))
        if rebuild and self.window is not None:
            # Icons are painted in palette colours, so rebuild the window in place.
            page = self.window.current_page()
            geometry = self.window.geometry()
            self.window.deleteLater()
            self.window = None
            self.show_page(page)
            self.window.setGeometry(geometry)

    def use_model(self, path: str) -> None:
        self.config.speech.model_path = path
        self.save()

    def download(self, info: ModelInfo) -> DownloadTask:
        existing = self.downloads.get(info.id)
        if existing is not None:
            return existing
        task = DownloadTask(info)
        self.downloads[info.id] = task

        def finished(path: str) -> None:
            self.downloads.pop(info.id, None)
            self.use_model(path)
            self._toast(f"{info.language} model installed.")

        def failed(message: str) -> None:
            self.downloads.pop(info.id, None)
            if message != "cancelled":
                self._toast(f"Download failed: {message}", warning=True)

        task.done.connect(finished)
        task.failed.connect(failed)
        task.start()
        return task

    def refresh_shortcut(self) -> None:
        if self.tray is not None:
            self._update_tray()


    def show_page(self, page: str = "home") -> None:
        from .main_window import MainWindow

        if self.wizard is not None and self.wizard.isVisible():
            self.wizard.raise_()
            self.wizard.activateWindow()
            return
        if self.window is None:
            self.window = MainWindow(self)
        self.window.show_page(page)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_onboarding(self) -> None:
        from .onboarding import Onboarding

        if self.wizard is None:
            self.wizard = Onboarding(self)
            self.wizard.finished_setup.connect(lambda: self.show_page("home"))
            self.wizard.finished.connect(self._wizard_closed)
        self.wizard.show()
        self.wizard.raise_()
        self.wizard.activateWindow()

    def _wizard_closed(self, _result: int) -> None:
        self.wizard.deleteLater()
        self.wizard = None
        if self.window is None or not self.window.isVisible():
            if self.tray is None or not self.config.app.onboarded:
                self.show_page("home")

    def window_hidden(self) -> None:
        if self.tray is not None and not self._told_about_tray:
            self._told_about_tray = True
            keys = desktop.shortcut_label(self.config.shortcut.toggle)
            self.tray.showMessage("Voxy is still here", f"Press {keys} to dictate. Find Voxy in the tray.", icons.app_icon(), 4000)

    def toggle_or_setup(self) -> None:
        if self.engine.state == "needs_model":
            self.open_onboarding()
        else:
            self.engine.toggle()

    def type_again(self, text: str) -> None:
        if self.window is not None:
            self.window.showMinimized()
        # Give the previous app a moment to regain focus before typing.
        QTimer.singleShot(600, lambda: self.engine.type_text(text + (" " if self.config.input.append_space else "")))

    def delete_history(self, ts: float) -> None:
        self.engine.history.remove(ts)
        if self.window is not None:
            self.window.pages["history"].refresh()


    def _on_listening(self, payload: dict) -> None:
        if payload.get("active"):
            if self.engine.state == "loading":
                self.overlay.show_loading("Loading speech model…")
            else:
                self.overlay.show_listening()
        else:
            self.overlay.show_done()
        self._update_tray()

    def _on_state(self, state: str) -> None:
        if state == "listening" and self.overlay is not None and self.overlay.mode == "loading":
            self.overlay.show_listening()
        self._update_tray()

    def _on_notice(self, payload: dict) -> None:
        level = str(payload.get("level", "info"))
        message = str(payload.get("message", ""))
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.show_notice(message, level)
        elif level != "info" or self.engine.listening is False:
            self._toast(message, warning=level != "info")

    def _toast(self, message: str, warning: bool = False) -> None:
        if self.overlay is not None and self.config.appearance.overlay:
            self.overlay.show_notice(message, "warning" if warning else "info")
        elif self.tray is not None:
            self.tray.showMessage("Voxy", message, icons.app_icon("warning" if warning else "idle"), 4000)


    def _build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(icons.app_icon(), self.app)
        menu = QMenu()
        self._status_action = QAction("Voxy", menu)
        self._status_action.setEnabled(False)
        self._toggle_action = QAction("Start dictation", menu)
        self._toggle_action.triggered.connect(self.toggle_or_setup)
        menu.addAction(self._status_action)
        menu.addSeparator()
        menu.addAction(self._toggle_action)
        menu.addSeparator()
        for text, page in (("Open Voxy", "home"), ("History", "history"), ("Settings", "settings")):
            action = QAction(text, menu)
            action.triggered.connect(lambda _c=False, p=page: self.show_page(p))
            menu.addAction(action)
        menu.addSeparator()
        quit_action = QAction("Quit Voxy", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self._menu = menu
        self.tray = tray
        self._update_tray()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_or_setup()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window is not None and self.window.isVisible() and self.window.isActiveWindow():
                self.window.hide()
            else:
                self.show_page("home")

    def _update_tray(self) -> None:
        if self.tray is None:
            return
        state = self.engine.state
        icon_state = {"listening": "listening", "loading": "busy", "needs_model": "warning", "error": "warning"}.get(state, "idle")
        self.tray.setIcon(icons.app_icon(icon_state))
        keys = desktop.shortcut_label(self.config.shortcut.toggle)
        status = {
            "listening": "Listening…",
            "loading": "Loading speech model…",
            "needs_model": "Setup needed",
            "error": "Needs attention",
        }.get(state, "Ready")
        self._status_action.setText(f"Voxy: {status}")
        if state == "needs_model":
            self._toggle_action.setText("Finish setup…")
        else:
            self._toggle_action.setText(f"{'Stop' if self.engine.listening else 'Start'} dictation    {keys}")
        stats = self.engine.history.stats()
        self.tray.setToolTip(f"Voxy: {status}\n{stats.today_words:,} words today")

