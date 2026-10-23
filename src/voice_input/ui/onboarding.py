"""First-run setup wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QLocale, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QKeySequenceEdit,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import desktop
from ..models import CATALOG, ModelInfo
from ..speech import list_input_devices, model_is_valid
from . import icons
from .theme import current
from .widgets import Card, KeyCaps, LevelMeter, MicButton, Spinner, ToggleSwitch, button, hbox, icon_label, label, vbox

if TYPE_CHECKING:
    from .app import Controller


def suggested_model() -> ModelInfo:
    locale = QLocale.system().name().lower().replace("_", "-")  # e.g. "en-us"
    lang = locale.split("-")[0]
    by_id = {info.id: info for info in CATALOG}
    if locale == "en-in":
        return by_id["vosk-model-small-en-in-0.4"]
    for info in CATALOG:
        if info.quality == "fast" and info.id.startswith(f"vosk-model-small-{lang}-"):
            return info
    return CATALOG[0]


class Dots(QWidget):
    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count
        self.index = 0
        self.setFixedSize(count * 22, 10)

    def set_index(self, index: int) -> None:
        self.index = index
        self.update()

    def paintEvent(self, _event: object) -> None:
        p = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        x = 0
        for i in range(self.count):
            active = i == self.index
            width = 22 if active else 8
            painter.setBrush(QColor(p.accent if i <= self.index else p.border))
            painter.drawRoundedRect(x, 1, width - 4 if active else width, 8, 4, 4)
            x += (width if active else 8) + 6


class ModelChoice(QFrame):
    clicked = Signal()

    def __init__(self, info: ModelInfo, recommended: bool) -> None:
        super().__init__()
        self.info = info
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selected = False
        flag = QLabel(info.flag)
        flag.setStyleSheet("font-size: 17pt; background: transparent;")
        name = label(info.language)
        name.setStyleSheet("font-weight: 600; background: transparent;")
        detail = "Most accurate" if info.quality == "accurate" else "Fast"
        meta = label(f"{detail} · {info.size_mb} MB" + (" · installed" if info.installed else ""), "Faint")
        meta.setStyleSheet("background: transparent;")
        row = hbox(flag, vbox(name, meta, spacing=1), None, spacing=12, margins=(14, 10, 14, 10))
        if recommended:
            row.addWidget(label("Suggested", "Badge"))
        self.setLayout(row)
        self._style()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._style()

    def _style(self) -> None:
        p = current()
        border = p.accent if self.selected else p.border
        bg = p.accent_soft if self.selected else p.surface
        self.setStyleSheet(f"ModelChoice {{ background: {bg}; border: 1.5px solid {border}; border-radius: 12px; }}")

    def mouseReleaseEvent(self, event) -> None:
        self.clicked.emit()
        super().mouseReleaseEvent(event)


class Onboarding(QDialog):
    finished_setup = Signal()

    STEPS = 6

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Welcome to Voxy")
        self.setWindowIcon(icons.app_icon())
        self.setFixedSize(780, 600)
        self.setObjectName("Root")

        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self._language())
        self.stack.addWidget(self._microphone())
        self.stack.addWidget(self._try_it())
        self.stack.addWidget(self._shortcut())
        self.stack.addWidget(self._done())

        self.dots = Dots(self.STEPS)
        self.back = button("Back", "Ghost")
        self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.next = button("Get started", "Primary", "arrow-right")
        self.next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next.setMinimumWidth(150)
        self.next.clicked.connect(self._next_clicked)
        footer = hbox(self.dots, None, self.back, self.next, spacing=10, margins=(36, 14, 28, 22))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.stack, 1)
        root.addLayout(footer)

        bridge = controller.bridge
        bridge.level.connect(self._on_level)
        bridge.state.connect(lambda _s: self._update_mic_state())
        bridge.partial.connect(self._on_partial)
        bridge.typed.connect(self._on_typed)
        bridge.listening.connect(lambda _p: self.try_mic.set_state(controller.engine.state))
        self.go(0)


    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = vbox(spacing=10, margins=(48, 40, 48, 8))
        layout.addWidget(label(title, "PageTitle"))
        if subtitle:
            layout.addWidget(label(subtitle, "PageSubtitle", wrap=True))
        layout.addSpacing(12)
        page.setLayout(layout)
        return page, layout

    def _welcome(self) -> QWidget:
        page = QWidget()
        p = current()
        logo = QLabel()
        logo.setPixmap(icons.app_pixmap("idle", 96))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = label("Type with your voice", "PageTitle")
        title.setStyleSheet("font-size: 28pt;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = label("Talk naturally and Voxy types for you, in any app.", "PageSubtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        features = hbox(spacing=12)
        for icon_name, head, text in [
            ("shield", "Private", "Your voice never leaves this computer."),
            ("zap", "Instant", "Words appear while you speak."),
            ("keyboard", "Everywhere", "Email, chat, documents, the browser…"),
        ]:
            card = Card(padding=16, spacing=6)
            card.add(icon_label(icon_name, p.accent, 22), label(head, "SectionTitle"), label(text, "Muted", wrap=True))
            features.addWidget(card)
        layout = vbox(None, logo, 10, title, sub, 26, features, None, spacing=6, margins=(48, 24, 48, 8))
        page.setLayout(layout)
        return page

    def _language(self) -> QWidget:
        page, layout = self._page("Which language do you speak?", "Voxy downloads a small speech model once. After that it works fully offline.")
        suggestion = suggested_model()
        grid = vbox(spacing=8)
        self.choices: list[ModelChoice] = []
        visible = [suggestion] + [m for m in CATALOG if m is not suggestion][:7]
        g = QGridLayout()
        g.setSpacing(8)
        for i, info in enumerate(visible):
            choice = ModelChoice(info, info is suggestion)
            choice.clicked.connect(lambda c=choice: self._select_model(c))
            self.choices.append(choice)
            g.addWidget(choice, i // 2, i % 2)
        grid.addLayout(g)
        more = QComboBox()
        more.addItem("More languages…", None)
        for info in CATALOG:
            if info not in visible:
                more.addItem(f"{info.flag}  {info.language} · {info.size_mb} MB", info.id)
        more.currentIndexChanged.connect(lambda _i: self._select_other(more.currentData()))
        folder = button("I already have a model", "Ghost", "folder")
        folder.clicked.connect(self._choose_folder)
        grid.addLayout(hbox(more, None, folder))
        layout.addLayout(grid)

        self.download_bar = QProgressBar()
        self.download_text = label("", "Muted")
        self.download_box = QWidget()
        self.download_box.setLayout(vbox(self.download_text, self.download_bar, spacing=6))
        self.download_box.hide()
        layout.addWidget(self.download_box)
        layout.addStretch(1)
        self.selected_model: ModelInfo = suggestion
        self.custom_model: str | None = None
        self._select_model(self.choices[0])
        return page

    def _microphone(self) -> QWidget:
        page, layout = self._page("Let's check your microphone", "Say a few words. The bars should dance while you talk.")
        self.device = QComboBox()
        self.device.addItem("System default microphone", None)
        for index, name in list_input_devices():
            self.device.addItem(name, index)
        self.device.setCurrentIndex(max(0, self.device.findData(self.controller.config.speech.device)))
        self.device.currentIndexChanged.connect(self._device_changed)
        card = Card(padding=24, spacing=14)
        self.meter = LevelMeter(40)
        self.meter.setFixedHeight(28)
        self.mic_status = label("", "Muted")
        self.mic_spinner = Spinner(16)
        card.add(label("Microphone", "SectionTitle"), self.device, 6, self.meter, hbox(self.mic_spinner, self.mic_status, None, spacing=8))
        layout.addWidget(card)
        layout.addStretch(1)
        self._heard = 0
        return page

    def _try_it(self) -> QWidget:
        page, layout = self._page("Give it a try", "Click the button and read the sentence below out loud.")
        self.try_mic = MicButton(96)
        self.try_mic.clicked.connect(self.controller.engine.toggle)
        prompt = Card(flat=True, padding=16)
        sample = label("“Hello Voxy comma this is my first dictation exclamation mark”", wrap=True)
        sample.setStyleSheet("font-size: 12pt; font-weight: 500;")
        prompt.add(label("Try saying", "Faint"), sample)
        self.transcript = label("Your words will appear here.", wrap=True)
        self.transcript.setStyleSheet(f"font-size: 14pt; color: {current().faint};")
        self.transcript.setMinimumHeight(80)
        self.transcript.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        output = Card(padding=20)
        output.add(self.transcript)
        layout.addLayout(hbox(self.try_mic, vbox(prompt, output, spacing=12), spacing=18))
        layout.addStretch(1)
        self._typed_text = ""
        return page

    def _shortcut(self) -> QWidget:
        page, layout = self._page(
            "Keyboard shortcut",
            "Press it from any app to start talking, and again to stop. Voxy types right where your cursor is.",
        )
        card = Card(padding=24, spacing=14)
        self.keys = KeyCaps(desktop.shortcut_label(self.controller.config.shortcut.toggle))
        self.keys.setStyleSheet("QLabel#KeyCap { font-size: 14pt; padding: 8px 16px; }")
        self.capture = QKeySequenceEdit()
        self.capture.setMaximumSequenceLength(1)
        self.capture.hide()
        self.capture.editingFinished.connect(self._captured)
        change = button("Choose different keys", "Ghost", "keyboard")
        change.clicked.connect(self._start_capture)
        self.shortcut_result = label("", "Muted", wrap=True)
        self.shortcut_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add(hbox(self.keys, self.capture, None, change), self.shortcut_result)
        layout.addWidget(card)
        if not desktop.can_register_shortcut():
            note = label(desktop.manual_shortcut_help(self.controller.config.shortcut.toggle), "Mono", wrap=True)
            note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.manual_note = note
            layout.addWidget(Card(flat=True, padding=16).add(label("Add it in your system settings", "SectionTitle"), note))
        else:
            self.manual_note = None
        layout.addStretch(1)
        return page

    def _done(self) -> QWidget:
        page = QWidget()
        p = current()
        badge = QLabel()
        badge.setPixmap(icons.pixmap("check", p.success, 64, 2.4))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = label("You're all set!", "PageTitle")
        title.setStyleSheet("font-size: 26pt;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_text = label("", "PageSubtitle", wrap=True)
        self.done_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.autostart = ToggleSwitch(True)
        options = Card(padding=18, spacing=0)
        options.add(hbox(vbox(label("Start Voxy when I log in"), label("So your shortcut always works.", "Muted"), spacing=2), None, self.autostart))
        layout = vbox(None, badge, 6, title, self.done_text, 24, options, None, spacing=6, margins=(120, 24, 120, 8))
        page.setLayout(layout)
        return page


    def go(self, index: int) -> None:
        index = max(0, min(self.STEPS - 1, index))
        previous = self.stack.currentIndex()
        if previous == 2 and index != 2:
            self.controller.engine.set_mic_test(False)
        if previous == 3 and index != 3:
            self.controller.engine.set_listening(False)
            self.controller.engine.preview = False

        self.stack.setCurrentIndex(index)
        self.dots.set_index(index)
        self.back.setVisible(0 < index < self.STEPS - 1)
        labels = ["Get started", "Download", "Sounds good", "Continue", "Set up shortcut", "Start using Voxy"]
        self.next.setText(labels[index] + " ")
        self.next.setEnabled(True)

        if index == 1:
            self._update_language_button()
        elif index == 2:
            self._heard = 0
            self.controller.engine.set_mic_test(True)
            self._update_mic_state()
        elif index == 3:
            self.controller.engine.preview = True
            self.try_mic.set_state(self.controller.engine.state)
        elif index == 5:
            keys = desktop.shortcut_label(self.controller.config.shortcut.toggle)
            self.done_text.setText(f"Press {keys} anytime, anywhere to start dictating.\nVoxy lives in your system tray.")

    def _next_clicked(self) -> None:
        index = self.stack.currentIndex()
        if index == 1:
            self._start_language()
            return
        if index == 4:
            if self.shortcut_result.text() and self.next.text().strip() == "Continue":
                self.go(5)
                return
            self._register()
            return
        if index == self.STEPS - 1:
            desktop.set_autostart(self.autostart.isChecked())
            self.controller.config.app.onboarded = True
            self.controller.save()
            self.finished_setup.emit()
            self.accept()
            return
        self.go(index + 1)


    def _select_model(self, choice: ModelChoice) -> None:
        self.custom_model = None
        self.selected_model = choice.info
        for c in self.choices:
            c.set_selected(c is choice)
        self._update_language_button()

    def _select_other(self, model_id: str | None) -> None:
        if not model_id:
            return
        info = next(m for m in CATALOG if m.id == model_id)
        self.custom_model = None
        self.selected_model = info
        for c in self.choices:
            c.set_selected(False)
        self._update_language_button()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a Vosk model folder")
        if folder and model_is_valid(folder):
            self.custom_model = folder
            for c in self.choices:
                c.set_selected(False)
            self.download_box.show()
            self.download_bar.hide()
            self.download_text.setText(f"Using the model in {folder}")
            self.next.setText("Continue ")
        elif folder:
            self.download_box.show()
            self.download_bar.hide()
            self.download_text.setText("That folder doesn't look like a Vosk model.")

    def _update_language_button(self) -> None:
        if self.stack.currentIndex() != 1:
            return
        if self.custom_model or self.selected_model.installed:
            self.next.setText("Continue ")
        else:
            self.next.setText(f"Download · {self.selected_model.size_mb} MB ")

    def _start_language(self) -> None:
        if self.custom_model:
            self.controller.use_model(self.custom_model)
            self.go(2)
            return
        info = self.selected_model
        if info.installed:
            self.controller.use_model(str(info.path))
            self.go(2)
            return
        self.next.setEnabled(False)
        self.back.setEnabled(False)
        self.download_box.show()
        self.download_bar.show()
        self.download_bar.setValue(0)
        self.download_text.setText(f"Downloading {info.language}…")
        task = self.controller.download(info)
        task.progress.connect(self._download_progress)
        task.done.connect(self._download_done)
        task.failed.connect(self._download_failed)

    def _download_progress(self, done: int, total: int) -> None:
        self.download_bar.setMaximum(max(total, 1))
        self.download_bar.setValue(done)
        self.download_text.setText(f"Downloading… {done / 1e6:.1f} of {total / 1e6:.0f} MB")

    def _download_done(self, _path: str) -> None:
        self.download_text.setText("Download complete.")
        self.back.setEnabled(True)
        QTimer.singleShot(500, lambda: self.go(2))

    def _download_failed(self, message: str) -> None:
        self.back.setEnabled(True)
        self.next.setEnabled(True)
        self.next.setText("Try again ")
        self.download_bar.hide()
        self.download_text.setText(f"The download didn't finish: {message}\nCheck your internet connection and try again.")


    def _device_changed(self, _index: int) -> None:
        self.controller.config.speech.device = self.device.currentData()
        self.controller.save()
        self._heard = 0
        QTimer.singleShot(300, lambda: self.controller.engine.set_mic_test(self.stack.currentIndex() == 2))

    def _update_mic_state(self) -> None:
        if self.stack.currentIndex() != 2:
            return
        state = self.controller.engine.state
        loading = state == "loading"
        self.mic_spinner.setVisible(loading)
        if loading:
            self.mic_status.setText("Loading the speech model…")
        elif self._heard < 6:
            self.mic_status.setStyleSheet("")
            self.mic_status.setText("Listening for your voice…")
        if state in ("ready", "listening"):
            self.controller.engine.set_mic_test(True)

    def _on_level(self, level: float) -> None:
        if self.stack.currentIndex() != 2:
            return
        self.meter.push_level(level)
        if level > 0.4:
            self._heard += 1
            if self._heard == 6:
                self.mic_status.setStyleSheet(f"color: {current().success}; font-weight: 600;")
                self.mic_status.setText("✓ We can hear you clearly!")


    def _on_partial(self, text: str) -> None:
        if self.stack.currentIndex() != 3 or not text:
            return
        self.transcript.setStyleSheet(f"font-size: 14pt; color: {current().text};")
        shown = (self._typed_text + " " + f"<span style='color:{current().faint}'>{text}</span>").strip()
        self.transcript.setText(shown)

    def _on_typed(self, payload: dict) -> None:
        if self.stack.currentIndex() != 3:
            return
        self._typed_text = (self._typed_text + " " + str(payload.get("text", ""))).strip()
        self.transcript.setStyleSheet(f"font-size: 14pt; color: {current().text};")
        self.transcript.setText(self._typed_text)


    def _start_capture(self) -> None:
        self.keys.hide()
        self.capture.show()
        self.capture.clear()
        self.capture.setFocus()
        self.shortcut_result.setText("Press the keys you want to use…")

    def _captured(self) -> None:
        sequence = self.capture.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        self.capture.hide()
        self.keys.show()
        if not sequence or "+" not in sequence:
            self.shortcut_result.setText("Use at least one modifier like Ctrl, Alt or Super.")
            return
        accel = desktop.qt_to_gtk(sequence)
        self.controller.config.shortcut.toggle = accel
        self.controller.save()
        self.keys.set_combo(desktop.shortcut_label(accel))
        self.shortcut_result.setText("")
        if self.manual_note is not None:
            self.manual_note.setText(desktop.manual_shortcut_help(accel))

    def _register(self) -> None:
        accel = self.controller.config.shortcut.toggle
        if desktop.can_register_shortcut():
            ok, message = desktop.register_shortcut(accel)
        else:
            ok, message = True, "Add the shortcut in your system settings as shown below, then continue."
        self.shortcut_result.setStyleSheet(f"color: {current().success if ok else current().warning};")
        self.shortcut_result.setText(("✓ " if ok else "") + message)
        self.next.setText("Continue ")
        self.controller.refresh_shortcut()

    def reject(self) -> None:
        self.controller.engine.set_mic_test(False)
        self.controller.engine.preview = False
        super().reject()
