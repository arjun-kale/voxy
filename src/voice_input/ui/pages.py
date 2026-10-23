"""Main window pages."""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import desktop
from ..doctor import FAIL, OK, run_checks
from ..models import CATALOG, ModelInfo, describe_model
from ..speech import list_input_devices, model_is_valid
from ..textproc import COMMAND_HELP
from . import icons
from .theme import ACCENTS, current
from .widgets import (
    Card,
    clear_layout,
    KeyCaps,
    LevelMeter,
    MicButton,
    SettingRow,
    ToggleSwitch,
    button,
    hbox,
    icon_button,
    icon_label,
    label,
    vbox,
)

if TYPE_CHECKING:
    from .app import Controller


TIPS = [
    "Say “new paragraph” to start a fresh block of text.",
    "Said something wrong? Just say “scratch that”.",
    "End a message with “send it” to press Enter for you.",
    "Add names you use often under Vocabulary so they're always spelled right.",
    "Create a snippet called “my address”, then say “insert my address”.",
    "Say “stop listening” to turn the mic off hands-free.",
    "Voxy stops by itself after a quiet pause, so you never leave the mic on.",
    "Everything stays on your computer. No audio ever leaves it.",
]


def time_ago(ts: float) -> str:
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)} h ago"
    if delta < 7 * 86400:
        return time.strftime("%A %H:%M", time.localtime(ts))
    return time.strftime("%d %b %Y", time.localtime(ts))


def format_minutes(minutes: float) -> str:
    if minutes < 1:
        return f"{int(minutes * 60)} s"
    if minutes < 60:
        return f"{int(minutes)} min"
    return f"{int(minutes // 60)} h {int(minutes % 60)} m"


class Page(QScrollArea):
    title = ""
    subtitle = ""

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self.controller = controller
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(40, 36, 40, 40)
        inner = QWidget()
        inner.setMaximumWidth(820)
        inner.setMinimumWidth(560)
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(16)
        # Same width on every page so switching pages never shifts the layout.
        row = hbox(spacing=0)
        row.addStretch(1)
        row.addWidget(inner, 100)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.setWidget(holder)

        if self.title:
            self.content.addWidget(label(self.title, "PageTitle"))
        if self.subtitle:
            self.content.addWidget(label(self.subtitle, "PageSubtitle", wrap=True))
            self.content.addSpacing(8)

    def refresh(self) -> None:
        pass

    def section(self, title: str) -> None:
        self.content.addSpacing(8)
        self.content.addWidget(label(title, "SectionTitle"))


class HomePage(Page):
    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        p = current()
        bridge = controller.bridge

        self.greeting = label("", "PageTitle")
        self.content.addWidget(self.greeting)
        self.subtitle_label = label("Your voice, typed anywhere. Private and offline.", "PageSubtitle")
        self.content.addWidget(self.subtitle_label)
        self.content.addSpacing(6)

        hero = Card(padding=24)
        self.mic = MicButton(124)
        self.mic.clicked.connect(controller.toggle_or_setup)
        self.state_title = label("", "Big")
        self.state_text = label("", "Muted", wrap=True)
        self.live = label("", wrap=True)
        self.live.setStyleSheet(f"color: {p.text}; font-size: 12pt;")
        self.live.setMinimumHeight(24)
        self.keys = KeyCaps(desktop.shortcut_label(controller.config.shortcut.toggle))
        self.shortcut_hint = label("or press", "Faint")
        shortcut_row = hbox(self.shortcut_hint, self.keys, None, spacing=10)
        self.setup_button = button("Finish setup", "Primary", "arrow-right")
        self.setup_button.clicked.connect(lambda: controller.open_onboarding())
        right = vbox(None, self.state_title, self.state_text, 6, shortcut_row, self.live, self.setup_button, None, spacing=6)
        hero.body.addLayout(hbox(self.mic, right, spacing=18))
        self.content.addWidget(hero)

        self.stat_today = self._stat("Words today", "sparkles")
        self.stat_total = self._stat("Words all-time", "book")
        self.stat_saved = self._stat("Time saved", "timer")
        self.content.addLayout(hbox(self.stat_today[0], self.stat_total[0], self.stat_saved[0], spacing=12))

        recent_header = hbox(label("Recent", "SectionTitle"), None)
        see_all = button("See all", "Ghost")
        see_all.clicked.connect(lambda: controller.show_page("history"))
        recent_header.addWidget(see_all)
        self.content.addLayout(recent_header)
        self.recent = Card(padding=8, spacing=0)
        self.content.addWidget(self.recent)

        tip = Card(flat=True, padding=16)
        self.tip_label = label(random.choice(TIPS), wrap=True)
        tip.body.addLayout(hbox(icon_label("info", p.accent, 18), self.tip_label, spacing=12))
        self.content.addWidget(tip)

        bridge.state.connect(lambda _s: self.update_state())
        bridge.level.connect(self.mic.push_level)
        bridge.partial.connect(self._on_partial)
        bridge.typed.connect(lambda _p: QTimer.singleShot(50, self.refresh))
        self.update_state()
        self.refresh()

    def _stat(self, caption: str, icon_name: str) -> tuple[Card, QLabel]:
        card = Card(padding=18, spacing=4)
        value = label("0", "Big")
        card.add(hbox(icon_label(icon_name, current().accent, 16), label(caption, "Muted"), None, spacing=8), value)
        return card, value

    def _on_partial(self, text: str) -> None:
        if self.controller.engine.listening:
            self.live.setText(text or "…")

    def update_state(self) -> None:
        hour = time.localtime().tm_hour
        part = "morning" if 5 <= hour < 12 else "afternoon" if hour < 18 else "evening"
        self.greeting.setText(f"Good {part}")

        engine = self.controller.engine
        state = engine.state
        self.mic.set_state(state)
        self.setup_button.setVisible(state == "needs_model")
        self.keys.setVisible(state != "needs_model")
        self.shortcut_hint.setVisible(state != "needs_model")
        self.live.setVisible(state == "listening")
        if state == "listening":
            self.state_title.setText("Listening…")
            self.state_text.setText("Speak naturally. Click the button, press your shortcut or say “stop listening” to finish.")
            self.live.setText("…")
        elif state == "loading":
            self.state_title.setText("Warming up")
            self.state_text.setText("Loading the speech model. This takes a moment the first time.")
        elif state == "needs_model":
            self.state_title.setText("Almost there")
            self.state_text.setText("Pick a language so Voxy can understand you. It downloads once and then works offline.")
        elif state == "error":
            self.state_title.setText("Something's not right")
            self.state_text.setText(engine.last_error or "Open Health to see what's wrong.")
        else:
            self.state_title.setText("Ready when you are")
            self.state_text.setText("Click the microphone and start talking. Voxy types into whatever app you're using.")

    def refresh(self) -> None:
        stats = self.controller.engine.history.stats()
        self.stat_today[1].setText(f"{stats.today_words:,}")
        self.stat_total[1].setText(f"{stats.total_words:,}")
        self.stat_saved[1].setText(format_minutes(stats.minutes_saved))

        body = self.recent.body
        clear_layout(body)
        entries = self.controller.engine.history.entries()[:4]
        if not entries:
            empty = label("Nothing yet. Your dictations will show up here.", "Muted")
            empty.setContentsMargins(12, 14, 12, 14)
            body.addWidget(empty)
            return
        for index, entry in enumerate(entries):
            body.addWidget(HistoryRow(self.controller, entry, compact=True, last=index == len(entries) - 1))


class HistoryRow(QFrame):
    def __init__(self, controller: "Controller", entry, compact: bool = False, last: bool = False) -> None:
        super().__init__()
        self.setObjectName("RowLast" if last else "Row")
        p = current()
        text = label(entry.text, wrap=True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if compact:
            metrics = text.fontMetrics()
            text.setText(metrics.elidedText(entry.text, Qt.TextElideMode.ElideRight, 520))
            text.setWordWrap(False)
        meta = label(f"{time_ago(entry.ts)} · {entry.words} words", "Faint")
        copy = icon_button("copy", "Copy")
        copy.clicked.connect(lambda: self._copy(controller, entry.text, copy))
        buttons = [copy]
        if not compact:
            again = icon_button("insert", "Type it again into the last app")
            again.clicked.connect(lambda: controller.type_again(entry.text))
            delete = icon_button("trash", "Delete", p.danger)
            delete.clicked.connect(lambda: controller.delete_history(entry.ts))
            buttons += [again, delete]
        layout = hbox(spacing=10, margins=(12, 10, 6, 10))
        layout.addLayout(vbox(text, meta, spacing=3), 1)
        for b in buttons:
            layout.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

    @staticmethod
    def _copy(controller: "Controller", text: str, origin: QPushButton) -> None:
        QGuiApplication.clipboard().setText(text)
        origin.setIcon(icons.icon("check", current().success, 16))
        QTimer.singleShot(1200, lambda: origin.setIcon(icons.icon("copy", current().muted, 16)))


class HistoryPage(Page):
    title = "History"
    subtitle = "Everything you've dictated, stored only on this computer."

    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your dictations…")
        self.search.addAction(icons.icon("search", current().faint, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._debounce.start())
        clear = button("Clear all", "Danger", None)
        clear.clicked.connect(self._clear)
        self.content.addLayout(hbox(self.search, clear, spacing=10))
        self.list = Card(padding=8, spacing=0)
        self.content.addWidget(self.list)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self.refresh)
        controller.bridge.typed.connect(lambda _p: self.refresh() if self.isVisible() else None)

    def _clear(self) -> None:
        answer = QMessageBox.question(self, "Clear history", "Delete every saved dictation? This can't be undone.")
        if answer == QMessageBox.StandardButton.Yes:
            self.controller.engine.history.clear()
            self.refresh()

    def refresh(self) -> None:
        body = self.list.body
        clear_layout(body)
        query = self.search.text().strip().lower()
        entries = [e for e in self.controller.engine.history.entries() if query in e.text.lower()][:200]
        if not entries:
            msg = "No matches." if query else "No dictations yet. Press the mic on Home to begin."
            empty = label(msg, "Muted")
            empty.setContentsMargins(12, 18, 12, 18)
            body.addWidget(empty)
            return
        for index, entry in enumerate(entries):
            body.addWidget(HistoryRow(self.controller, entry, last=index == len(entries) - 1))


class PairEditor(Card):
    """Editable list of “when I say … → write …” pairs."""

    def __init__(self, title: str, hint: str, left: str, right: str, values: dict[str, str], multiline: bool, on_change) -> None:
        super().__init__(padding=20, spacing=10)
        self.multiline = multiline
        self.on_change = on_change
        self.left_placeholder = left
        self.right_placeholder = right
        add = button("Add", None, "plus")
        add.clicked.connect(lambda: self._add_row("", "", focus=True))
        header = hbox(spacing=12)
        header.addLayout(vbox(label(title, "SectionTitle"), label(hint, "Muted", wrap=True), spacing=2), 1)
        header.addWidget(add, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(header)
        self.rows_layout = vbox(spacing=8)
        self.body.addLayout(self.rows_layout)
        self.rows: list[tuple[QWidget, QLineEdit, QWidget]] = []
        for key, value in values.items():
            self._add_row(key, value)

    def _add_row(self, key: str, value: str, focus: bool = False) -> None:
        row = QWidget()
        key_edit = QLineEdit(key)
        key_edit.setPlaceholderText(self.left_placeholder)
        if self.multiline:
            value_edit: QWidget = QPlainTextEdit(value)
            value_edit.setPlaceholderText(self.right_placeholder)
            value_edit.setFixedHeight(64)
            value_edit.textChanged.connect(self._changed)  # type: ignore[attr-defined]
        else:
            value_edit = QLineEdit(value)
            value_edit.setPlaceholderText(self.right_placeholder)
            value_edit.textChanged.connect(self._changed)  # type: ignore[attr-defined]
        key_edit.textChanged.connect(self._changed)
        remove = icon_button("x", "Remove")
        layout = hbox(key_edit, icon_label("arrow-right", current().faint, 16), value_edit, remove, spacing=10)
        layout.setStretch(0, 2)
        layout.setStretch(2, 3)
        row.setLayout(layout)
        entry = (row, key_edit, value_edit)
        remove.clicked.connect(lambda: self._remove(entry))
        self.rows.append(entry)
        self.rows_layout.addWidget(row)
        if focus:
            key_edit.setFocus()

    def _remove(self, entry) -> None:
        self.rows.remove(entry)
        entry[0].deleteLater()
        self._changed()

    def values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for _row, key_edit, value_edit in self.rows:
            key = key_edit.text().strip()
            value = value_edit.toPlainText() if isinstance(value_edit, QPlainTextEdit) else value_edit.text()  # type: ignore[attr-defined]
            if key and value.strip():
                result[key] = value
        return result

    def _changed(self) -> None:
        self.on_change()


class VocabularyPage(Page):
    title = "Vocabulary"
    subtitle = "Teach Voxy your words. Changes save automatically."

    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        text = controller.config.text
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._save)
        self.fixes = PairEditor(
            "Word fixes",
            "Voxy hears it one way, you want it written another. Great for names and brands.",
            "When I say…",
            "Write…",
            text.replacements,
            False,
            self._save_timer.start,
        )
        self.snippets = PairEditor(
            "Snippets",
            "Say “insert” followed by the name to type the whole text, e.g. “insert my email”.",
            "Snippet name",
            "Text to type",
            text.snippets,
            True,
            self._save_timer.start,
        )
        self.content.addWidget(self.fixes)
        self.content.addWidget(self.snippets)
        if not text.replacements and not text.snippets:
            self.fixes._add_row("voxy", "Voxy")

    def _save(self) -> None:
        cfg = self.controller.config
        cfg.text.replacements = self.fixes.values()
        cfg.text.snippets = self.snippets.values()
        self.controller.save()


class CommandsPage(Page):
    title = "Voice commands"
    subtitle = "Speak these while dictating. No need to touch the keyboard."

    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, (phrase, meaning) in enumerate(COMMAND_HELP):
            card = Card(padding=16, spacing=4)
            phrase_label = label(phrase, wrap=True)
            phrase_label.setStyleSheet("font-weight: 600; font-size: 11pt;")
            card.add(phrase_label, label(meaning, "Muted", wrap=True))
            grid.addWidget(card, index // 2, index % 2)
        self.content.addLayout(grid)

        self.section("Smart formatting")
        text = controller.config.text
        card = Card(padding=20, spacing=0)
        card.add(
            self._row("Spoken punctuation", "Turn words like “comma” and “period” into symbols.", "spoken_punctuation", text.spoken_punctuation),
            self._row("Voice commands", "Listen for commands like “scratch that” and “press enter”.", "voice_commands", text.voice_commands),
            self._row("Automatic capitals", "Start sentences with a capital letter and write “I” properly.", "auto_capitalize", text.auto_capitalize),
            self._row("Remove filler words", "Leave out “um”, “uh” and similar sounds.", "remove_fillers", text.remove_fillers, last=True),
        )
        self.content.addWidget(card)

    def _row(self, title: str, description: str, attr: str, value: bool, last: bool = False) -> SettingRow:
        toggle = ToggleSwitch(value)

        def changed(checked: bool) -> None:
            setattr(self.controller.config.text, attr, checked)
            self.controller.save()

        toggle.toggled.connect(changed)
        return SettingRow(title, description, toggle, last=last)


class ModelRow(QFrame):
    def __init__(self, page: "SettingsPage", info: ModelInfo, last: bool) -> None:
        super().__init__()
        self.page = page
        self.info = info
        self.setObjectName("RowLast" if last else "Row")
        flag = QLabel(info.flag)
        flag.setStyleSheet("font-size: 18pt;")
        flag.setFixedWidth(34)
        name = label(info.language)
        name.setStyleSheet("font-weight: 600;")
        badge = label("Most accurate" if info.quality == "accurate" else "Fast", "Badge" if info.quality == "accurate" else "BadgeMuted")
        meta = label(f"{info.size_mb} MB download", "Faint")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(140)
        self.progress.hide()
        self.action = button("", None)
        self.action.setFixedWidth(118)
        self.action.clicked.connect(self._clicked)
        layout = hbox(spacing=12, margins=(0, 10, 0, 10))
        layout.addWidget(flag)
        layout.addLayout(vbox(hbox(name, badge, None, spacing=8), meta, spacing=2), 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.action)
        self.setLayout(layout)
        self.update_state()

    def update_state(self) -> None:
        in_use = self.page.controller.config.speech.model_path == str(self.info.path)
        task = self.page.controller.downloads.get(self.info.id)
        self.progress.setVisible(task is not None)
        if task is not None:
            self.action.setText("Cancel")
            self.action.setObjectName("Ghost")
        elif in_use and self.info.installed:
            self.action.setText("In use ✓")
            self.action.setObjectName("Ghost")
        elif self.info.installed:
            self.action.setText("Use")
            self.action.setObjectName("")
        else:
            self.action.setText("Download")
            self.action.setObjectName("Primary")
        self.action.setEnabled(not (in_use and self.info.installed and task is None))
        self.action.style().unpolish(self.action)
        self.action.style().polish(self.action)

    def _clicked(self) -> None:
        controller = self.page.controller
        task = controller.downloads.get(self.info.id)
        if task is not None:
            task.cancel()
            return
        if self.info.installed:
            controller.use_model(str(self.info.path))
            self.page.refresh_models()
            return
        task = controller.download(self.info)
        task.progress.connect(self._progress)
        task.done.connect(lambda _path: self.page.refresh_models())
        task.failed.connect(lambda _msg: self.page.refresh_models())
        self.update_state()

    def _progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        self.progress.setToolTip(f"{done / 1e6:.1f} of {total / 1e6:.0f} MB")


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Everything has a sensible default. Change only what you like."

    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        cfg = controller.config

        self.section("General")
        general = Card(padding=20, spacing=0)
        autostart = ToggleSwitch(desktop.autostart_enabled())
        autostart.toggled.connect(desktop.set_autostart)
        sounds = self._bool_toggle(cfg.behavior, "sounds")
        history = self._bool_toggle(cfg.behavior, "history")
        auto_stop = QComboBox()
        options = [(0, "Never"), (10, "After 10 seconds"), (20, "After 20 seconds"), (30, "After 30 seconds"), (60, "After 1 minute")]
        for seconds, text in options:
            auto_stop.addItem(text, seconds)
        auto_stop.setCurrentIndex(max(0, auto_stop.findData(cfg.behavior.auto_stop_seconds)))
        auto_stop.currentIndexChanged.connect(lambda _i: self._set(cfg.behavior, "auto_stop_seconds", auto_stop.currentData()))
        general.add(
            SettingRow("Start Voxy when I log in", "Keeps Voxy ready in the background.", autostart),
            SettingRow("Sound cues", "A soft chime when dictation starts and stops.", sounds),
            SettingRow("Stop on silence", "Turns the microphone off when you stop talking.", auto_stop),
            SettingRow("Keep history", "Save what you dictate so you can find and copy it later.", history, last=True),
        )
        self.content.addWidget(general)

        self.section("Microphone")
        mic = Card(padding=20, spacing=0)
        self.device = QComboBox()
        self.device.setMinimumWidth(240)
        self.device.addItem("System default", None)
        for index, name in list_input_devices():
            self.device.addItem(name, index)
        self.device.setCurrentIndex(max(0, self.device.findData(cfg.speech.device)))
        self.device.currentIndexChanged.connect(lambda _i: self._set(cfg.speech, "device", self.device.currentData()))
        self.meter = LevelMeter()
        self.test_button = button("Test microphone", None, "mic")
        self.test_button.setCheckable(True)
        self.test_button.toggled.connect(self._mic_test)
        controller.bridge.level.connect(self.meter.push_level)
        mic.add(
            SettingRow("Input device", "Which microphone Voxy listens to.", self.device),
            SettingRow("Check your levels", "Speak normally. The bars should reach the green-to-yellow area.", self.test_button, last=True),
            self.meter,
        )
        self.content.addWidget(mic)

        self.section("Language")
        self.models_card = Card(padding=20, spacing=0)
        self.model_rows: list[ModelRow] = []
        for index, info in enumerate(CATALOG):
            row = ModelRow(self, info, last=index == len(CATALOG) - 1)
            self.model_rows.append(row)
            self.models_card.add(row)
        custom = button("Use a model folder…", "Ghost", "folder")
        custom.clicked.connect(self._choose_folder)
        self.current_model = label("", "Faint")
        self.models_card.add(hbox(self.current_model, None, custom))
        self.content.addWidget(self.models_card)

        self.section("Typing")
        typing = Card(padding=20, spacing=0)
        method = QComboBox()
        for value, text in [
            ("auto", "Automatic (recommended)"),
            ("wtype", "wtype (Wayland)"),
            ("ydotool", "ydotool (any desktop)"),
            ("xdotool", "xdotool (X11)"),
            ("clipboard", "Copy to clipboard only"),
        ]:
            method.addItem(text, value)
        method.setCurrentIndex(max(0, method.findData(cfg.input.backend)))
        method.currentIndexChanged.connect(lambda _i: self._set(cfg.input, "backend", method.currentData()))
        self.backend_label = label("", "Faint")
        controller.bridge.backend.connect(lambda _l: self._update_backend())
        space = self._bool_toggle(cfg.input, "append_space")
        typing.add(
            SettingRow("Typing method", "How Voxy puts text into other apps.", method),
            self.backend_label,
            SettingRow("Space after each phrase", "So the next sentence doesn't run into the last one.", space, last=True),
        )
        self.content.addWidget(typing)

        self.section("Keyboard shortcut")
        shortcut = Card(padding=20, spacing=12)
        self.keys = KeyCaps(desktop.shortcut_label(cfg.shortcut.toggle))
        self.capture = QKeySequenceEdit()
        self.capture.setMaximumSequenceLength(1)
        self.capture.hide()
        self.capture.editingFinished.connect(self._captured)
        change = button("Change", None, "keyboard")
        change.clicked.connect(self._start_capture)
        apply = button("Set up shortcut", "Primary")
        apply.clicked.connect(self._register_shortcut)
        self.shortcut_result = label("", "Muted", wrap=True)
        self.shortcut_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        shortcut.add(
            label("Press this anywhere to start and stop dictation.", "Muted"),
            hbox(self.keys, self.capture, None, change, apply, spacing=10),
            self.shortcut_result,
        )
        self.content.addWidget(shortcut)

        self.section("Appearance")
        look = Card(padding=20, spacing=0)
        theme_row = QWidget()
        theme_layout = hbox(spacing=6)
        group = QButtonGroup(theme_row)
        for value, text in [("system", "System"), ("light", "Light"), ("dark", "Dark")]:
            b = button(text, None)
            b.setCheckable(True)
            b.setChecked(cfg.appearance.theme == value)
            b.clicked.connect(lambda _c=False, v=value: self._set_theme(v))
            group.addButton(b)
            theme_layout.addWidget(b)
        theme_row.setLayout(theme_layout)
        swatches = QWidget()
        swatch_layout = hbox(spacing=8)
        swatch_group = QButtonGroup(swatches)
        for color in ACCENTS:
            s = QPushButton()
            s.setObjectName("Swatch")
            s.setCheckable(True)
            s.setFixedSize(28, 28)
            s.setCursor(Qt.CursorShape.PointingHandCursor)
            s.setChecked(cfg.appearance.accent.lower() == color.lower())
            s.setStyleSheet(f"QPushButton#Swatch {{ background: {color}; }}")
            s.clicked.connect(lambda _c=False, v=color: self._set_accent(v))
            swatch_group.addButton(s)
            swatch_layout.addWidget(s)
        swatches.setLayout(swatch_layout)
        overlay = self._bool_toggle(cfg.appearance, "overlay")
        live = self._bool_toggle(cfg.appearance, "live_text")
        position = QComboBox()
        position.addItem("Bottom of the screen", "bottom")
        position.addItem("Top of the screen", "top")
        position.setCurrentIndex(max(0, position.findData(cfg.appearance.overlay_position)))
        position.currentIndexChanged.connect(lambda _i: self._set(cfg.appearance, "overlay_position", position.currentData()))
        look.add(
            SettingRow("Theme", "", theme_row),
            SettingRow("Accent colour", "", swatches),
            SettingRow("Floating bar", "Show a small bar with a live waveform while dictating.", overlay),
            SettingRow("Show words as you speak", "Preview the transcript inside the floating bar.", live),
            SettingRow("Floating bar position", "", position, last=True),
        )
        self.content.addWidget(look)
        self.refresh_models()
        self._update_backend()


    def _bool_toggle(self, section: object, attr: str) -> ToggleSwitch:
        toggle = ToggleSwitch(bool(getattr(section, attr)))
        toggle.toggled.connect(lambda checked: self._set(section, attr, checked))
        return toggle

    def _set(self, section: object, attr: str, value: object) -> None:
        setattr(section, attr, value)
        self.controller.save()

    def _set_theme(self, value: str) -> None:
        self.controller.config.appearance.theme = value
        self.controller.save()
        self.controller.apply_theme()

    def _set_accent(self, value: str) -> None:
        self.controller.config.appearance.accent = value
        self.controller.save()
        self.controller.apply_theme()

    def _update_backend(self) -> None:
        sink = self.controller.engine.selection.sink
        note = "" if sink.types_directly else ". Press Ctrl+V to paste"
        self.backend_label.setText(f"Currently typing with {sink.label}{note}")

    def _mic_test(self, on: bool) -> None:
        self.controller.engine.set_mic_test(on)
        self.test_button.setText("Stop test" if on else "Test microphone")

    def hideEvent(self, event: object) -> None:
        if self.test_button.isChecked():
            self.test_button.setChecked(False)
        super().hideEvent(event)  # type: ignore[arg-type]

    def refresh_models(self) -> None:
        for row in self.model_rows:
            row.update_state()
        self.current_model.setText(f"In use: {describe_model(self.controller.config.speech.model_path)}")

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a Vosk model folder")
        if not folder:
            return
        if not model_is_valid(folder):
            QMessageBox.warning(self, "Not a speech model", "That folder doesn't look like a Vosk model.")
            return
        self.controller.use_model(folder)
        self.refresh_models()

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
            self.shortcut_result.setText("Use at least one modifier, like Ctrl, Alt or Super.")
            return
        accel = desktop.qt_to_gtk(sequence)
        self.controller.config.shortcut.toggle = accel
        self.controller.save()
        self.keys.set_combo(desktop.shortcut_label(accel))
        self._register_shortcut()

    def _register_shortcut(self) -> None:
        accel = self.controller.config.shortcut.toggle
        if desktop.can_register_shortcut():
            ok, message = desktop.register_shortcut(accel)
        else:
            ok, message = False, desktop.manual_shortcut_help(accel)
        color = current().success if ok else current().muted
        self.shortcut_result.setStyleSheet(f"color: {color};")
        self.shortcut_result.setText(message)
        self.controller.refresh_shortcut()


class HealthPage(Page):
    title = "Health check"
    subtitle = "A quick look at everything Voxy needs, with a fix for anything missing."

    def __init__(self, controller: "Controller") -> None:
        super().__init__(controller)
        self.card = Card(padding=20, spacing=0)
        rerun = button("Check again", None, "refresh")
        rerun.clicked.connect(self.refresh)
        copy = button("Copy report", "Ghost", "copy")
        copy.clicked.connect(self._copy)
        self.content.addLayout(hbox(None, copy, rerun))
        self.content.addWidget(self.card)
        self._report = ""

    def refresh(self) -> None:
        body = self.card.body
        clear_layout(body)
        p = current()
        checks = run_checks(self.controller.config)
        lines = []
        for index, check in enumerate(checks):
            color = p.success if check.status == OK else p.danger if check.status == FAIL else p.warning
            glyph = "check" if check.status == OK else "x" if check.status == FAIL else "alert"
            row = QFrame()
            row.setObjectName("RowLast" if index == len(checks) - 1 else "Row")
            text = vbox(label(check.title), label(check.detail, "Muted", wrap=True), spacing=2)
            if check.fix:
                fix = label(check.fix, "Mono", wrap=True)
                fix.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text.addWidget(fix)
            layout = hbox(icon_label(glyph, color, 20), spacing=14, margins=(0, 12, 0, 12))
            layout.addLayout(text, 1)
            row.setLayout(layout)
            body.addWidget(row)
            lines.append(f"[{check.status.upper()}] {check.title}: {check.detail}" + (f" (fix: {check.fix})" if check.fix else ""))
        self._report = "\n".join(lines)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._report)

