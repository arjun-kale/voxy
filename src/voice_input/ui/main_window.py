from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QWidget

from . import icons
from .pages import CommandsPage, HealthPage, HistoryPage, HomePage, Page, SettingsPage, VocabularyPage
from .theme import current
from .widgets import StatusDot, hbox, label, vbox

if TYPE_CHECKING:
    from .app import Controller


NAV = [
    ("home", "Home", "home", HomePage),
    ("history", "History", "clock", HistoryPage),
    ("vocabulary", "Vocabulary", "book", VocabularyPage),
    ("commands", "Voice commands", "command", CommandsPage),
    ("settings", "Settings", "sliders", SettingsPage),
    ("health", "Health check", "activity", HealthPage),
]

STATE_TEXT = {
    "ready": ("Ready", "success", False),
    "listening": ("Listening", "listening", True),
    "loading": ("Loading model", "warning", True),
    "needs_model": ("Setup needed", "warning", False),
    "error": ("Needs attention", "danger", False),
}


class MainWindow(QMainWindow):
    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Voxy")
        self.setWindowIcon(icons.app_icon())
        self.resize(1040, 720)
        self.setMinimumSize(860, 600)
        p = current()

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = vbox(spacing=4, margins=(16, 22, 16, 18))
        logo = label()
        logo.setPixmap(icons.app_pixmap("idle", 30))
        side.addLayout(hbox(logo, label("Voxy", "Brand"), None, spacing=10))
        side.addSpacing(22)

        self.stack = QStackedWidget()
        self.pages: dict[str, Page] = {}
        self.buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, title, icon_name, cls in NAV:
            page = cls(controller)
            self.pages[key] = page
            self.stack.addWidget(page)
            nav = QPushButton(f"  {title}")
            nav.setObjectName("NavButton")
            nav.setCheckable(True)
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.setIcon(icons.icon(icon_name, p.muted, 18))
            nav.setIconSize(QSize(18, 18))
            nav.clicked.connect(lambda _c=False, k=key: self.show_page(k))
            group.addButton(nav)
            self.buttons[key] = nav
            side.addWidget(nav)
        side.addStretch(1)

        status = QFrame()
        status.setObjectName("CardFlat")
        self.dot = StatusDot()
        self.status_label = label("", None)
        self.status_label.setStyleSheet("font-weight: 600;")
        self.backend_label = label("", "Faint")
        status_layout = vbox(hbox(self.dot, self.status_label, None, spacing=6), self.backend_label, spacing=2, margins=(12, 10, 12, 10))
        status.setLayout(status_layout)
        side.addWidget(status)
        sidebar.setLayout(side)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        controller.bridge.state.connect(lambda _s: self.update_status())
        controller.bridge.backend.connect(lambda _b: self.update_status())
        self.update_status()
        self.show_page("home")

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            key = "home"
        self.buttons[key].setChecked(True)
        page = self.pages[key]
        page.refresh()
        self.stack.setCurrentWidget(page)
        p = current()
        for name, nav in self.buttons.items():
            icon_name = next(i for k, _t, i, _c in NAV if k == name)
            nav.setIcon(icons.icon(icon_name, p.accent if name == key else p.muted, 18))

    def current_page(self) -> str:
        for key, page in self.pages.items():
            if self.stack.currentWidget() is page:
                return key
        return "home"

    def update_status(self) -> None:
        p = current()
        text, color_name, pulse = STATE_TEXT.get(self.controller.engine.state, ("Ready", "success", False))
        self.dot.set(getattr(p, color_name), pulse)
        self.status_label.setText(text)
        sink = self.controller.engine.selection.sink
        self.backend_label.setText("Pastes via clipboard" if not sink.types_directly else f"Types with {sink.name}")

    def closeEvent(self, event) -> None:
        # Closing the window keeps Voxy running in the background.
        event.ignore()
        self.hide()
        self.controller.window_hidden()
