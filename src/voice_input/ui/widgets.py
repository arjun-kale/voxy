"""Shared custom widgets."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .theme import current


def vbox(*items: object, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    _fill(layout, items)
    return layout


def hbox(*items: object, spacing: int = 8, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    _fill(layout, items)
    return layout


def _fill(layout: QVBoxLayout | QHBoxLayout, items: tuple[object, ...]) -> None:
    for item in items:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)  # type: ignore[arg-type]


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            # Detach right away so stale rows never paint while awaiting deletion.
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return widget


def button(text: str, kind: str | None = None, icon_name: str | None = None) -> QPushButton:
    # Qt leaves almost no gap between icon and text.
    widget = QPushButton(f" {text}" if icon_name and text else text)
    if kind:
        widget.setObjectName(kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon_name:
        p = current()
        color = p.on_accent if kind == "Primary" else p.text
        widget.setIcon(icons.icon(icon_name, color, 16))
        widget.setIconSize(QSize(16, 16))
    return widget


def icon_button(icon_name: str, tooltip: str, color: str | None = None) -> QPushButton:
    widget = QPushButton()
    widget.setObjectName("IconButton")
    widget.setToolTip(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setIcon(icons.icon(icon_name, color or current().muted, 16))
    widget.setIconSize(QSize(16, 16))
    widget.setFixedSize(32, 32)
    return widget


def icon_label(icon_name: str, color: str, size: int = 18) -> QLabel:
    widget = QLabel()
    widget.setPixmap(icons.pixmap(icon_name, color, size))
    widget.setFixedSize(size, size)
    return widget


class Card(QFrame):
    def __init__(self, flat: bool = False, padding: int = 20, spacing: int = 12) -> None:
        super().__init__()
        self.setObjectName("CardFlat" if flat else "Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def add(self, *items: object) -> "Card":
        _fill(self.body, items)
        return self


class SettingRow(QFrame):
    """Title and helper text on the left, a control on the right."""

    def __init__(self, title: str, description: str, control: QWidget | None, last: bool = False) -> None:
        super().__init__()
        self.setObjectName("RowLast" if last else "Row")
        text = vbox(label(title), spacing=2)
        if description:
            text.addWidget(label(description, "Muted", wrap=True))
        layout = hbox(spacing=16, margins=(0, 12, 0, 12))
        layout.addLayout(text, 1)
        if control is not None:
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setLayout(layout)


class KeyCaps(QWidget):
    def __init__(self, combo: str = "") -> None:
        super().__init__()
        self._layout = hbox(spacing=6)
        self.setLayout(self._layout)
        self.set_combo(combo)

    def set_combo(self, combo: str) -> None:
        clear_layout(self._layout)
        parts = [p.strip() for p in combo.split("+") if p.strip()]
        for index, part in enumerate(parts):
            if index:
                self._layout.addWidget(label("+", "Faint"))
            self._layout.addWidget(label(part, "KeyCap"))
        self._layout.addStretch(1)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def sizeHint(self) -> QSize:
        return QSize(44, 26)

    def paintEvent(self, _event: object) -> None:
        p = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(p.border)
        on = QColor(p.accent)
        t = self._offset
        mixed = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        if not self.isEnabled():
            mixed.setAlpha(110)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(mixed)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob = track.height() - 6
        x = track.left() + 3 + (track.width() - knob - 6) * t
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, track.top() + 3, knob, knob))


class Waveform(QWidget):
    """Animated voice bars that follow the microphone level."""

    def __init__(self, bars: int = 28, bar_width: float = 3.0, gap: float = 3.0) -> None:
        super().__init__()
        self.bars = bars
        self.bar_width = bar_width
        self.gap = gap
        self._target = 0.0
        self._level = 0.0
        self._active = False
        self._start = time.monotonic()
        self.colors: tuple[str, str] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(24)
        self.setFixedWidth(int(bars * (bar_width + gap)))

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and not self._timer.isActive():
            self._timer.start()
        if not active:
            self._target = 0.0

    def push_level(self, level: float) -> None:
        self._target = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        # Fast attack, slow release.
        speed = 0.45 if self._target > self._level else 0.10
        self._level += (self._target - self._level) * speed
        if not self._active and self._level < 0.01:
            self._level = 0.0
            self._timer.stop()
        self.update()

    def paintEvent(self, _event: object) -> None:
        p = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        mid = h / 2
        t = time.monotonic() - self._start
        start, end = self.colors or (p.accent, "#FF5CA8")
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, QColor(start))
        gradient.setColorAt(1, QColor(end))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))

        for i in range(self.bars):
            x = i * (self.bar_width + self.gap) + self.gap / 2
            centre = 1 - abs(i - (self.bars - 1) / 2) / (self.bars / 2)
            envelope = 0.35 + 0.65 * math.sin(centre * math.pi / 2)
            wobble = 0.55 + 0.45 * math.sin(t * 7.5 + i * 0.85) * math.sin(t * 3.1 + i * 0.37)
            idle = 0.08 + 0.04 * math.sin(t * 2.2 + i * 0.6) if self._active else 0.06
            amp = max(idle, self._level * envelope * wobble)
            bar_h = max(self.bar_width, amp * (h - 2))
            painter.drawRoundedRect(
                QRectF(x, mid - bar_h / 2, self.bar_width, bar_h),
                self.bar_width / 2,
                self.bar_width / 2,
            )


class LevelMeter(QWidget):
    """Segmented horizontal meter for the microphone test."""

    def __init__(self, segments: int = 32) -> None:
        super().__init__()
        self.segments = segments
        self._level = 0.0
        self._peak = 0.0
        self.setMinimumHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def push_level(self, level: float) -> None:
        self._level = self._level * 0.5 + level * 0.5 if level < self._level else level
        self._peak = max(self._peak * 0.97, self._level)
        self.update()

    def paintEvent(self, _event: object) -> None:
        p = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        gap = 3
        w = (self.width() - gap * (self.segments - 1)) / self.segments
        lit = int(self._level * self.segments + 0.5)
        peak = int(self._peak * self.segments)
        for i in range(self.segments):
            frac = i / self.segments
            if i < lit or (peak and i == peak):
                color = QColor(p.success if frac < 0.65 else p.warning if frac < 0.88 else p.danger)
            else:
                color = QColor(p.surface2)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(i * (w + gap), 0, w, self.height()), 3, 3)


class MicButton(QAbstractButton):
    """The big round dictation button with a breathing glow."""

    def __init__(self, diameter: int = 132) -> None:
        super().__init__()
        self.diameter = diameter
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(diameter + 72, diameter + 72)
        self.state = "ready"
        self._level = 0.0
        self._smoothed = 0.0
        self._hover = 0.0
        self._start = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)

    # Animate only while on screen so a hidden window costs no CPU.
    def showEvent(self, event: object) -> None:
        self._timer.start()
        super().showEvent(event)  # type: ignore[arg-type]

    def hideEvent(self, event: object) -> None:
        self._timer.stop()
        super().hideEvent(event)  # type: ignore[arg-type]

    def set_state(self, state: str) -> None:
        self.state = state
        self.setEnabled(state not in ("needs_model", "loading"))
        self.update()

    def push_level(self, level: float) -> None:
        self._level = level

    def enterEvent(self, event: object) -> None:
        self._hover = 1.0
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: object) -> None:
        self._hover = 0.0
        super().leaveEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, _event: object) -> None:
        p = current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(self.width() / 2, self.height() / 2)
        r = self.diameter / 2
        t = time.monotonic() - self._start
        listening = self.state == "listening"
        self._smoothed += (self._level - self._smoothed) * 0.25

        base = QColor(p.listening if listening else p.accent)
        if self.state in ("needs_model", "error"):
            base = QColor(p.faint)

        if listening:
            for k in range(3):
                phase = (t * 0.7 + k / 3) % 1.0
                ring_r = r + 8 + phase * (26 + 30 * self._smoothed)
                color = QColor(base)
                color.setAlphaF(max(0.0, 0.32 * (1 - phase)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(centre, ring_r, ring_r)
        else:
            breathe = 0.5 + 0.5 * math.sin(t * 1.6)
            glow = QRadialGradient(centre, r + 34)
            c1 = QColor(base)
            c1.setAlphaF(0.20 + 0.10 * breathe + 0.08 * self._hover)
            c2 = QColor(base)
            c2.setAlphaF(0.0)
            glow.setColorAt(0.6, c1)
            glow.setColorAt(1.0, c2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(centre, r + 34, r + 34)

        grow = 1 + (0.06 * self._smoothed if listening else 0.02 * self._hover)
        body = QRadialGradient(centre - QPointF(r * 0.35, r * 0.45), r * 1.6)
        body.setColorAt(0, base.lighter(135))
        body.setColorAt(1, base.darker(115))
        painter.setBrush(body)
        painter.drawEllipse(centre, r * grow, r * grow)

        highlight = QColor(255, 255, 255, 40)
        painter.setPen(QPen(highlight, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, r * grow - 1, r * grow - 1)

        if self.state == "loading":
            pen = QPen(QColor("#FFFFFF"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            rect = QRectF(centre.x() - 22, centre.y() - 22, 44, 44)
            painter.drawArc(rect, int(-t * 360 * 16) % (360 * 16), 100 * 16)
            return
        glyph = "stop" if listening else "mic"
        size = 40 if listening else 52
        pm = icons.pixmap(glyph, "#FFFFFF", size, 1.9)
        painter.drawPixmap(int(centre.x() - size / 2), int(centre.y() - size / 2), pm)


class Spinner(QWidget):
    def __init__(self, size: int = 18) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event: object) -> None:
        self._timer.start()
        super().showEvent(event)  # type: ignore[arg-type]

    def hideEvent(self, event: object) -> None:
        self._timer.stop()
        super().hideEvent(event)  # type: ignore[arg-type]

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(current().accent), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        m = 2.0
        painter.drawArc(QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m), -self._angle * 16, 260 * 16)


class StatusDot(QWidget):
    def __init__(self, size: int = 8) -> None:
        super().__init__()
        self.setFixedSize(size + 8, size + 8)
        self.size_ = size
        self.color = current().success
        self.pulse = False
        self._start = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)

    def set(self, color: str, pulse: bool = False) -> None:
        self.color = color
        self.pulse = pulse
        if pulse:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        c = QPointF(self.width() / 2, self.height() / 2)
        if self.pulse:
            phase = ((time.monotonic() - self._start) * 1.2) % 1.0
            halo = QColor(self.color)
            halo.setAlphaF(0.45 * (1 - phase))
            painter.setBrush(halo)
            rad = self.size_ / 2 + phase * 4
            painter.drawEllipse(c, rad, rad)
        painter.setBrush(QColor(self.color))
        painter.drawEllipse(c, self.size_ / 2, self.size_ / 2)


class Divider(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(1)
        self.setStyleSheet(f"background: {current().border};")


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class Clickable(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event: object) -> None:
        self.clicked.emit()
        super().mouseReleaseEvent(event)  # type: ignore[arg-type]
