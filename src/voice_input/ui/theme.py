"""Colour palettes and stylesheet."""

from __future__ import annotations

from dataclasses import dataclass, replace
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication


@dataclass(frozen=True, slots=True)
class Palette:
    dark: bool
    bg: str
    sidebar: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    success: str
    warning: str
    danger: str
    listening: str


DARK = Palette(
    dark=True,
    bg="#0E0E13",
    sidebar="#13131A",
    surface="#191921",
    surface2="#21212B",
    border="#2A2A36",
    text="#F3F3F8",
    muted="#A0A0B4",
    faint="#6C6C80",
    accent="#7C5CFF",
    accent_hover="#9277FF",
    accent_soft="rgba(124, 92, 255, 0.16)",
    on_accent="#FFFFFF",
    success="#2FD180",
    warning="#FFB224",
    danger="#FF4F64",
    listening="#FF4F64",
)

LIGHT = Palette(
    dark=False,
    bg="#F6F6FA",
    sidebar="#EEEEF5",
    surface="#FFFFFF",
    surface2="#F1F1F6",
    border="#E2E2EB",
    text="#15151D",
    muted="#62627A",
    faint="#9A9AAE",
    accent="#6A47FF",
    accent_hover="#5A36F5",
    accent_soft="rgba(106, 71, 255, 0.10)",
    on_accent="#FFFFFF",
    success="#13A35A",
    warning="#C77800",
    danger="#E5243B",
    listening="#E5243B",
)

ACCENTS = ["#7C5CFF", "#2F80FF", "#00B8A9", "#2FBF71", "#FF8A3D", "#FF4F8B"]

_current: Palette = DARK


def current() -> Palette:
    """The palette custom-painted widgets should use right now."""
    return _current


def set_current(palette: Palette) -> None:
    global _current
    _current = palette


def _soft(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def system_prefers_dark() -> bool:
    app = QGuiApplication.instance()
    if app is None:
        return True
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return QGuiApplication.palette().window().color().lightness() < 128


def build_palette(theme: str, accent: str) -> Palette:
    dark = system_prefers_dark() if theme == "system" else theme == "dark"
    base = DARK if dark else LIGHT
    color = QColor(accent)
    if not color.isValid():
        return base
    hover = color.lighter(115) if dark else color.darker(110)
    return replace(
        base,
        accent=color.name(),
        accent_hover=hover.name(),
        accent_soft=_soft(color.name(), 0.16 if dark else 0.10),
    )


def pick_font_family() -> str:
    families = set(QFontDatabase.families())
    for family in ("Inter", "Inter Variable", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"):
        if family in families:
            return family
    return QFont().family()


def apply_app_font() -> None:
    font = QFont(pick_font_family())
    font.setPointSizeF(10.5)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    QGuiApplication.setFont(font)


_QSS = Template(
    """
* { outline: none; }
QWidget { color: $text; font-size: 10.5pt; }
QMainWindow, QDialog, #Root { background: $bg; }
QToolTip { background: $surface2; color: $text; border: 1px solid $border; border-radius: 6px; padding: 6px 8px; }

#Sidebar { background: $sidebar; border-right: 1px solid $border; }
#Brand { font-size: 15pt; font-weight: 700; letter-spacing: -0.3px; }
#NavButton { text-align: left; padding: 9px 12px; border: none; background: transparent; border-radius: 10px; color: $muted; font-weight: 500; }
#NavButton:hover { background: $surface2; color: $text; }
#NavButton:checked { background: $accent_soft; color: $text; font-weight: 600; }

#PageTitle { font-size: 21pt; font-weight: 700; letter-spacing: -0.6px; }
#PageSubtitle { color: $muted; font-size: 10.5pt; }
#SectionTitle { font-size: 11pt; font-weight: 600; color: $text; padding-top: 6px; }
#Muted { color: $muted; }
#Faint { color: $faint; font-size: 9.5pt; }
#Big { font-size: 24pt; font-weight: 700; letter-spacing: -0.8px; }
#Mono { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 9.5pt; color: $muted; }

#Card { background: $surface; border: 1px solid $border; border-radius: 16px; }
#CardFlat { background: $surface2; border: none; border-radius: 12px; }
#Row { background: transparent; border: none; border-bottom: 1px solid $border; }
#RowLast { background: transparent; border: none; }
#Badge { background: $accent_soft; color: $accent; border-radius: 8px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }
#BadgeMuted { background: $surface2; color: $muted; border-radius: 8px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }
#KeyCap { background: $surface2; border: 1px solid $border; border-bottom: 3px solid $border; border-radius: 8px; padding: 4px 10px; font-weight: 600; font-size: 10pt; }

QPushButton { background: $surface2; border: 1px solid $border; border-radius: 10px; padding: 8px 16px; font-weight: 600; }
QPushButton:hover { border-color: $faint; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $faint; }
QPushButton#Primary { background: $accent; color: $on_accent; border: none; }
QPushButton#Primary:hover { background: $accent_hover; }
QPushButton#Primary:disabled { background: $surface2; color: $faint; }
QPushButton#Ghost { background: transparent; border: none; color: $muted; padding: 6px 10px; }
QPushButton#Ghost:hover { background: $surface2; color: $text; }
QPushButton#Danger { background: transparent; border: 1px solid $border; color: $danger; }
QPushButton#Danger:hover { border-color: $danger; }
QPushButton#IconButton { background: transparent; border: none; border-radius: 8px; padding: 6px; }
QPushButton#IconButton:hover { background: $surface2; }
QPushButton#Swatch { border-radius: 14px; padding: 0; border: 2px solid transparent; }
QPushButton#Swatch:checked { border: 2px solid $text; }

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
  background: $surface2; border: 1px solid $border; border-radius: 10px; padding: 7px 10px;
  selection-background-color: $accent; selection-color: $on_accent;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 4px; selection-background-color: $accent_soft; selection-color: $text; }

QSlider::groove:horizontal { height: 6px; background: $surface2; border-radius: 3px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 3px; }
QSlider::handle:horizontal { background: #FFFFFF; border: 1px solid $border; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }

QProgressBar { background: $surface2; border: none; border-radius: 5px; height: 10px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 5px; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { height: 0; background: none; }

QMenu { background: $surface; border: 1px solid $border; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 8px 18px 8px 12px; border-radius: 8px; }
QMenu::item:selected { background: $accent_soft; }
QMenu::item:disabled { color: $faint; }
QMenu::separator { height: 1px; background: $border; margin: 4px 8px; }
"""
)


def stylesheet(p: Palette) -> str:
    return _QSS.substitute(
        bg=p.bg,
        sidebar=p.sidebar,
        surface=p.surface,
        surface2=p.surface2,
        border=p.border,
        text=p.text,
        muted=p.muted,
        faint=p.faint,
        accent=p.accent,
        accent_hover=p.accent_hover,
        accent_soft=p.accent_soft,
        on_accent=p.on_accent,
        danger=p.danger,
    )
