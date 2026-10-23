"""Floating bar shown while dictating."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..config import AppearanceConfig
from . import icons
from .widgets import Spinner, Waveform


SHADOW = 18
HEIGHT = 60


class Overlay(QWidget):
    def __init__(self, appearance: AppearanceConfig, on_stop) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if QGuiApplication.platformName() == "xcb":
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("Voxy")

        self.appearance = appearance
        self.mode = "hidden"
        self.started_at = 0.0
        self.session_words = 0
        self.partial = ""
        self.last_typed = ""
        self.copied = False
        self.countdown = 0
        self.accent = QColor("#7C5CFF")
        self.listen_color = QColor("#FF4F64")

        self.orb = _Orb()
        self.spinner = Spinner(18)
        self.spinner.hide()
        self.wave = Waveform(bars=22, bar_width=3, gap=3)
        self.wave.colors = ("#A28BFF", "#FF6FB1")
        self.text = QLabel()
        self.text.setStyleSheet("color: rgba(255,255,255,0.92); font-size: 11pt; font-weight: 500;")
        self.chip = QLabel()
        self.chip.hide()
        self.timer_label = QLabel("0:00")
        self.timer_label.setStyleSheet(
            "color: rgba(255,255,255,0.45); font-family: 'JetBrains Mono', monospace; font-size: 9.5pt;"
        )
        self.stop_button = QPushButton()
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.stop_button.setToolTip("Stop dictation")
        self.stop_button.setIcon(icons.icon("stop", "#FFFFFF", 14))
        self.stop_button.setFixedSize(30, 30)
        self.stop_button.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.10); border: none; border-radius: 15px; }"
            "QPushButton:hover { background: rgba(255,79,100,0.85); }"
        )
        self.stop_button.clicked.connect(on_stop)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SHADOW + 14, SHADOW + 8, SHADOW + 10, SHADOW + 8)
        layout.setSpacing(12)
        layout.addWidget(self.orb)
        layout.addWidget(self.spinner)
        layout.addWidget(self.wave)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.chip)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.stop_button)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(170)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)
        self._fading_out = False

        self._clock = QTimer(self)
        self._clock.setInterval(250)
        self._clock.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.fade_out)

        self.apply_appearance(appearance)


    def apply_appearance(self, appearance: AppearanceConfig) -> None:
        self.appearance = appearance
        self.accent = QColor(appearance.accent)
        self.wave.colors = (self.accent.lighter(130).name(), "#FF6FB1")
        width = 560 if appearance.live_text else 340
        self.setFixedSize(width + 2 * SHADOW, HEIGHT + 2 * SHADOW)
        self.text.setVisible(appearance.live_text or self.mode != "listening")
        if self.isVisible():
            self._place()

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = area.center().x() - self.width() // 2
        if self.appearance.overlay_position == "top":
            y = area.top() + 28 - SHADOW
        else:
            y = area.bottom() - self.height() - 28 + SHADOW
        self.move(QPoint(x, y))


    def show_listening(self) -> None:
        if not self.appearance.overlay:
            return
        self._hide_timer.stop()
        self.mode = "listening"
        self.started_at = time.monotonic()
        self.session_words = 0
        self.partial = ""
        self.last_typed = ""
        self.copied = False
        self.countdown = 0
        self.orb.listening = True
        self.orb.show()
        self.spinner.hide()
        self.wave.show()
        self.wave.set_active(True)
        self.timer_label.show()
        self.stop_button.show()
        self.text.setVisible(self.appearance.live_text)
        self._update_text()
        self._update_chip()
        self._clock.start()
        self._tick()
        self._appear()

    def show_loading(self, message: str = "Getting ready…") -> None:
        if not self.appearance.overlay:
            return
        self.mode = "loading"
        self.orb.hide()
        self.spinner.show()
        self.wave.hide()
        self.timer_label.hide()
        self.stop_button.hide()
        self.chip.hide()
        self.text.show()
        self._set_text(message, muted=True)
        self._appear()

    def show_done(self) -> None:
        self._clock.stop()
        self.wave.set_active(False)
        if self.mode != "listening" or not self.isVisible():
            self.mode = "hidden"
            return
        self.mode = "done"
        self.orb.listening = False
        self.stop_button.hide()
        self.timer_label.hide()
        self.wave.hide()
        self.chip.hide()
        self.text.show()
        words = self.session_words
        if words == 0:
            message = "Didn't catch anything this time"
        elif self.copied:
            message = f"{words} word{'s' if words != 1 else ''} copied, press Ctrl+V to paste"
        else:
            message = f"Typed {words} word{'s' if words != 1 else ''}"
        self._set_text(message)
        self.orb.done = words > 0
        self.orb.update()
        self._hide_timer.start(1600 if words else 1100)

    def show_notice(self, message: str, level: str = "info") -> None:
        if not self.appearance.overlay:
            return
        if self.mode == "listening":
            self._set_chip(message[:48] + ("…" if len(message) > 48 else ""), level)
            QTimer.singleShot(3500, self._update_chip)
            return
        self.mode = "notice"
        self.orb.listening = False
        self.orb.done = False
        self.orb.warning = level != "info"
        self.orb.show()
        self.spinner.hide()
        self.wave.hide()
        self.timer_label.hide()
        self.stop_button.hide()
        self.chip.hide()
        self.text.show()
        self._set_text(message, elide_right=True)
        self._appear()
        self._hide_timer.start(4200)


    def on_level(self, level: float) -> None:
        self.wave.push_level(level)
        self.orb.level = level

    def on_partial(self, text: str) -> None:
        self.partial = text
        if self.mode == "listening":
            self._update_text()

    def on_typed(self, payload: dict) -> None:
        text = str(payload.get("text", ""))
        self.session_words += len(text.split())
        self.last_typed = text
        self.copied = payload.get("mode") == "copied"
        if self.mode == "listening":
            self._update_text()
            if self.copied:
                self._set_chip("Copied · Ctrl+V", "info")
        elif self.mode == "done" and self.isVisible():
            # Final words arrive just after stopping; refresh the summary.
            self.mode = "listening"
            self.show_done()

    def on_countdown(self, seconds: int) -> None:
        self.countdown = seconds
        self._update_chip()

    def _update_text(self) -> None:
        if self.partial:
            self._set_text(self.partial)
        elif self.last_typed:
            self._set_text(self.last_typed, muted=True)
        else:
            self._set_text("Listening...", muted=True)

    def _set_text(self, text: str, muted: bool = False, elide_right: bool = False) -> None:
        alpha = 0.55 if muted else 0.95
        self.text.setStyleSheet(f"color: rgba(255,255,255,{alpha}); font-size: 11pt; font-weight: 500;")
        metrics = QFontMetrics(self.text.font())
        width = max(60, self.text.width() or 300)
        mode = Qt.TextElideMode.ElideRight if elide_right else Qt.TextElideMode.ElideLeft
        self.text.setText(metrics.elidedText(text.replace("\n", " ⏎ "), mode, width))
        self.text.setToolTip(text)

    def _update_chip(self) -> None:
        if self.mode != "listening":
            return
        if self.countdown:
            self._set_chip(f"Stopping in {self.countdown}s", "warning")
        else:
            self.chip.hide()

    def _set_chip(self, text: str, level: str) -> None:
        colors = {
            "info": ("rgba(255,255,255,0.12)", "rgba(255,255,255,0.85)"),
            "warning": ("rgba(255,178,36,0.18)", "#FFC965"),
            "error": ("rgba(255,79,100,0.20)", "#FF8A98"),
        }
        bg, fg = colors.get(level, colors["info"])
        self.chip.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 9px; padding: 3px 9px; font-size: 9pt; font-weight: 600;"
        )
        self.chip.setText(text)
        self.chip.show()

    def _tick(self) -> None:
        elapsed = int(time.monotonic() - self.started_at)
        self.timer_label.setText(f"{elapsed // 60}:{elapsed % 60:02d}")


    def _appear(self) -> None:
        self._fading_out = False
        if not self.isVisible():
            self._place()
            self.setWindowOpacity(0.0)
            self.show()
            self.raise_()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(1.0)
        self._fade.start()

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._fading_out = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self._fading_out:
            self._fading_out = False
            self.hide()
            self.mode = "hidden"
            self.orb.done = False
            self.orb.warning = False


    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pill = QRectF(SHADOW, SHADOW, self.width() - 2 * SHADOW, self.height() - 2 * SHADOW)
        radius = pill.height() / 2

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(SHADOW, 0, -2):
            alpha = int(46 * (1 - i / SHADOW) ** 2)
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(pill.adjusted(-i, -i + 4, i, i + 4), radius + i, radius + i)

        painter.setBrush(QColor(20, 20, 28, 238))
        painter.drawRoundedRect(pill, radius, radius)

        edge = QColor(self.accent if self.mode == "listening" else QColor(255, 255, 255))
        edge.setAlpha(90 if self.mode == "listening" else 26)
        painter.setPen(edge)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class _Orb(QWidget):
    """Pulsing record light; turns into a check or warning sign afterwards."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(30, 30)
        self.level = 0.0
        self.listening = False
        self.done = False
        self.warning = False
        self._start = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)

    def showEvent(self, event: object) -> None:
        self._timer.start()
        super().showEvent(event)  # type: ignore[arg-type]

    def hideEvent(self, event: object) -> None:
        self._timer.stop()
        super().hideEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        c = self.rect().center()
        if self.done or self.warning:
            color = QColor("#FFB224") if self.warning else QColor("#2FD180")
            soft = QColor(color)
            soft.setAlpha(50)
            painter.setBrush(soft)
            painter.drawEllipse(c, 14, 14)
            name = "alert" if self.warning else "check"
            painter.drawPixmap(c.x() - 8, c.y() - 8, icons.pixmap(name, color.name(), 16, 2.6))
            return

        red = QColor("#FF4F64")
        if self.listening:
            t = time.monotonic() - self._start
            halo = QColor(red)
            halo.setAlphaF(0.18 + 0.25 * min(1.0, self.level * 1.4))
            radius = 9 + 5 * min(1.0, self.level * 1.3) + 1.2 * (1 + math.sin(t * 4))
            painter.setBrush(halo)
            painter.drawEllipse(c, radius, radius)
        painter.setBrush(red)
        painter.drawEllipse(c, 6, 6)
