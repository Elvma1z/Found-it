"""Found It design system components for PyQt5.

Qt ports of the design system's React components (components/*): Button,
IconButton, Badge, Kbd, Text roles, Panel, PageHeader, Tabs, Switch,
CollapsibleSection, DetailList, ResultRow / ListItem / PersonTile rows,
SettingsNav, ThemeSwatch, StatusBar, the window glow backdrop and a toast.

Colors come from the active palette (see themes.py). Everything that paints
or carries an icon listens to `theme_bus().changed` and recolors itself, so
screens never have to re-theme individual components.
"""

import os
import tempfile
from typing import Iterable, List, Optional, Sequence, Tuple

from PyQt5.QtCore import (
    QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QVBoxLayout, QWidget,
)

from found_it.gui.icons import get_pixmap, get_icon
from found_it.utils.themes import (
    DEFAULT_THEME, FONT, FONT_DISPLAY, FONT_MONO, QSS_FONT, QSS_FONT_DISPLAY,
    app_qss, get_palette,
)


# ---------------------------------------------------------------- theming

class _ThemeBus(QObject):
    changed = pyqtSignal(dict)


_bus = None
_current = get_palette(DEFAULT_THEME)
_family = FONT


def theme_bus() -> _ThemeBus:
    global _bus
    if _bus is None:
        _bus = _ThemeBus()
    return _bus


def pal() -> dict:
    """The active palette."""
    return _current


def qc(value: str, alpha: Optional[float] = None) -> QColor:
    c = QColor(value)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def mix(color: str, alpha: float) -> QColor:
    """CSS `color-mix(in srgb, color N%, transparent)`."""
    return qc(color, alpha)


def _icon_file(name: str, color: str, stroke: float = 2.0) -> str:
    """A Lucide icon written to a temp .svg, for QSS `image: url(...)`."""
    from found_it.gui.icons import _ICON_BODY
    path = os.path.join(tempfile.gettempdir(), f"found_it_{name}_{color.lstrip('#')}_{stroke}.svg")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" '
                f'fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
                f'stroke-linejoin="round">{_ICON_BODY[name]}</svg>'
            )
    return path.replace("\\", "/")


def apply_app_theme(p: dict, font_family: Optional[str] = None):
    """Install palette `p` app-wide: stylesheet, QPalette, and a
    `theme_bus().changed` broadcast for painted components."""
    global _current, _family
    _current = p
    _family = font_family if font_family and font_family not in ("Segoe UI", FONT) else FONT
    app = QApplication.instance()
    if app is None:
        return
    qss = (app_qss(p)
           .replace("__CHECK__", _icon_file("check", p["on_accent"], 3))
           .replace("__CHEVRONS__", _icon_file("chevrons-up-down", p["text3"]))
           .replace("__CHEVRON_UP__", _icon_file("chevron-up", p["text3"]))
           .replace("__CHEVRON_DOWN__", _icon_file("chevron-down", p["text3"])))
    if font_family and font_family not in ("Segoe UI", FONT):
        custom = f'"{font_family}", "Segoe UI", sans-serif'
        qss = qss.replace(QSS_FONT_DISPLAY, custom).replace(QSS_FONT, custom)
    qpal = app.palette()
    qpal.setColor(QPalette.Window, qc(p["bg"]))
    qpal.setColor(QPalette.WindowText, qc(p["text"]))
    qpal.setColor(QPalette.Base, qc(p["panel_solid"]))
    qpal.setColor(QPalette.Text, qc(p["text"]))
    qpal.setColor(QPalette.Button, qc(p["panel_solid"]))
    qpal.setColor(QPalette.ButtonText, qc(p["text"]))
    qpal.setColor(QPalette.Highlight, qc(p["accent"]))
    qpal.setColor(QPalette.HighlightedText, qc(p["on_accent"]))
    qpal.setColor(QPalette.ToolTipBase, qc(p["pop"]))
    qpal.setColor(QPalette.ToolTipText, qc(p["text"]))
    qpal.setColor(QPalette.PlaceholderText, qc(p["text3"]))
    app.setPalette(qpal)
    app.setStyleSheet(qss)
    theme_bus().changed.emit(p)


def on_theme(widget: QObject, fn):
    """Call `fn(palette)` now and on every theme change."""
    theme_bus().changed.connect(fn)
    fn(_current)


def font(size: float = 13.5, weight: int = 400, family: Optional[str] = None) -> QFont:
    """A QFont in the design's type scale, in the user's chosen UI font."""
    f = QFont(family or _family)
    f.setPixelSize(round(size))
    f.setWeight({400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold, 700: QFont.Bold}.get(weight, QFont.Normal))
    return f


def restyle(widget: QWidget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ---------------------------------------------------------------- text

def text(value: str = "", role: str = "body", wrap: bool = False, selectable: bool = False) -> QLabel:
    """components/core/Text - roles: display h1 h2 h3 body secondary small
    caption eyebrow mono status."""
    if role == "eyebrow":
        value = value.upper()
    lbl = QLabel(value)
    if role != "body":
        lbl.setProperty("cls", role)
    if role == "eyebrow":
        f = lbl.font()
        f.setLetterSpacing(QFont.PercentageSpacing, 106)
        lbl.setFont(f)
    lbl.setWordWrap(wrap)
    if selectable:
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def separator(vertical: bool = False) -> QFrame:
    sep = QFrame()
    sep.setProperty("cls", "vsep" if vertical else "sep")
    return sep


# ---------------------------------------------------------------- buttons

class Button(QPushButton):
    """components/core/Button - variant: primary | secondary | ghost | success |
    danger; size: sm | md | lg."""

    _FG = {
        "primary": ("on_accent", "on_accent"),
        "secondary": ("text", "text"),
        "ghost": ("text2", "text"),
        "success": ("success", "on_success"),
        "danger": ("danger", "#ffffff"),
    }

    def __init__(self, label: str = "", variant: str = "primary", icon: Optional[str] = None,
                 size: str = "md", parent=None):
        super().__init__(label, parent)
        self.variant = variant
        self.icon_name = icon
        self._hover = False
        self.setProperty("cls", variant)
        if size != "md":
            self.setProperty("size", size)
        self.setCursor(Qt.PointingHandCursor)
        s = 14 if size == "sm" else 16
        self.setIconSize(QSize(s, s))
        on_theme(self, self._retint)
        self.toggled.connect(lambda _c: self._retint(pal()))

    def set_icon(self, name: Optional[str]):
        self.icon_name = name
        self._retint(pal())

    def set_variant(self, variant: str):
        self.variant = variant
        self.setProperty("cls", variant)
        restyle(self)
        self._retint(pal())

    def _retint(self, p):
        if not self.icon_name:
            self.setIcon(QIcon())
            return
        base, hover = self._FG.get(self.variant, ("text", "text"))
        key = hover if self._hover else base
        if self.variant == "secondary" and self.isCheckable() and self.isChecked():
            key = "accent_text"
        if not self.isEnabled():
            key = "text3"
        color = p.get(key, key)
        self.setIcon(get_icon(self.icon_name, color, self.iconSize().width()))

    def enterEvent(self, e):
        self._hover = True
        self._retint(pal())
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self._retint(pal())
        super().leaveEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.EnabledChange:
            self._retint(pal())
        super().changeEvent(e)


class IconButton(QPushButton):
    """components/core/IconButton - square, icon only. size sm 28 / md 34 / lg 40."""

    def __init__(self, icon_name: str, tooltip: str = "", size: str = "md", variant: str = "ghost",
                 danger: bool = False, checkable: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self._danger = danger
        self._hover = False
        d = {"sm": 28, "md": 34, "lg": 40}[size]
        self.setFixedSize(d, d)
        self.setProperty("cls", "iconbtn")
        if variant == "solid":
            self.setProperty("variant", "solid")
        if danger:
            self.setProperty("danger", "true")
        s = 15 if size == "sm" else 17
        self.setIconSize(QSize(s, s))
        self.setCheckable(checkable)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(lambda _c: self.apply_theme(pal()))
        on_theme(self, self.apply_theme)

    def set_icon(self, name: str):
        self.icon_name = name
        self.apply_theme(pal())

    def apply_theme(self, p: dict):
        if self._danger and self._hover:
            color = "#ffffff"
        elif self.isChecked():
            color = p["accent_text"]
        elif self._hover:
            color = p["text"]
        else:
            color = p["text2"]
        self.setIcon(get_icon(self.icon_name, color, self.iconSize().width()))

    def enterEvent(self, e):
        self._hover = True
        self.apply_theme(pal())
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.apply_theme(pal())
        super().leaveEvent(e)


# ---------------------------------------------------------------- badge / kbd

class Badge(QWidget):
    """components/core/Badge - tone: neutral | accent | success | warning | danger."""

    def __init__(self, label: str = "", tone: str = "neutral", dot: bool = False, parent=None):
        super().__init__(parent)
        self._text, self._tone, self._dot = label, tone, dot
        self._font = font(11.5, 600)
        self.setFixedHeight(22)
        self._resize()
        theme_bus().changed.connect(lambda _p: self.update())

    def set_text(self, label: str, tone: Optional[str] = None):
        self._text = label
        if tone:
            self._tone = tone
        self._resize()
        self.update()

    def set_tone(self, tone: str):
        self._tone = tone
        self.update()

    def setText(self, label: str):
        self.set_text(label)

    def text(self) -> str:
        return self._text

    def _resize(self):
        w = QFontMetrics(self._font).horizontalAdvance(self._text) + 16 + (12 if self._dot else 0)
        self.setFixedWidth(max(w, 22))

    def _colors(self, p):
        return {
            "neutral": (p["surface3"], p["text2"]),
            "accent": (p["accent_soft"], p["accent_text"]),
            "success": (p["success_soft"], p["success"]),
            "warning": (p["warning_soft"], p["warning"]),
            "danger": (p["danger_soft"], p["danger"]),
            "faint": (p["surface3"], p["text3"]),
        }[self._tone]

    def paintEvent(self, _e):
        bg, fg = self._colors(pal())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(bg))
        painter.drawRoundedRect(QRectF(self.rect()), 6, 6)
        x = 8
        if self._dot:
            painter.setBrush(qc(fg))
            painter.drawEllipse(QRectF(x, 8, 6, 6))
            x += 12
        painter.setPen(qc(fg))
        painter.setFont(self._font)
        painter.drawText(QRect(x, 0, self.width() - x, self.height()), Qt.AlignVCenter, self._text)
        painter.end()


def match_badge(score: float) -> Badge:
    pct = round(score * 100)
    return Badge(f"{pct}%", "accent" if pct >= 80 else ("neutral" if pct >= 50 else "faint"))


class Kbd(QWidget):
    """components/core/Kbd - keyboard key hint."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._text = label
        self._font = font(11.5, 500)
        w = max(20, QFontMetrics(self._font).horizontalAdvance(label) + 10)
        self.setFixedSize(w, 20)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        theme_bus().changed.connect(lambda _p: self.update())

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(qc(p["border_strong"]), 1))
        painter.setBrush(qc(p["surface2"]))
        painter.drawRoundedRect(r, 5, 5)
        painter.setPen(QPen(qc(p["border_strong"]), 1))
        painter.drawLine(QPointF(r.left() + 3, r.bottom()), QPointF(r.right() - 3, r.bottom()))
        painter.setPen(qc(p["text2"]))
        painter.setFont(self._font)
        painter.drawText(self.rect().adjusted(0, 0, 0, -1), Qt.AlignCenter, self._text)
        painter.end()


class IconLabel(QLabel):
    """A themed Lucide icon as a label."""

    def __init__(self, icon_name: str, color_key: str = "text3", size: int = 16, parent=None):
        super().__init__(parent)
        self.icon_name, self.color_key, self._size = icon_name, color_key, size
        self.setFixedSize(size, size)
        on_theme(self, self._retint)

    def set_icon(self, name: str, color_key: Optional[str] = None):
        self.icon_name = name
        if color_key:
            self.color_key = color_key
        self._retint(pal())

    def _retint(self, p):
        color = p.get(self.color_key, self.color_key)
        self.setPixmap(get_pixmap(self.icon_name, color, self._size))


# ---------------------------------------------------------------- inputs

class TextInput(QLineEdit):
    """components/forms/TextInput - optional leading icon, trailing Kbd hint."""

    def __init__(self, placeholder: str = "", icon: Optional[str] = None, hint: Optional[str] = None,
                 size: str = "md", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._icon = icon
        if size != "md":
            self.setProperty("size", size)
        if icon:
            self.setProperty("icon", "true")
        self._kbd = None
        if hint:
            self._kbd = Kbd(hint, self)
            self.setTextMargins(0, 0, self._kbd.width() + 6, 0)
        theme_bus().changed.connect(lambda _p: self.update())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._kbd is not None:
            self._kbd.move(self.width() - self._kbd.width() - 8, (self.height() - self._kbd.height()) // 2)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._icon:
            painter = QPainter(self)
            pm = get_pixmap(self._icon, pal()["text3"], 16)
            painter.drawPixmap(11, (self.height() - 16) // 2, pm)
            painter.end()


class Select(QComboBox):
    """components/forms/Select - a combo box with an optional leading icon."""

    def __init__(self, icon: Optional[str] = None, size: str = "md", parent=None):
        super().__init__(parent)
        self._icon = icon
        if size != "md":
            self.setProperty("size", size)
        if icon:
            self.setStyleSheet("QComboBox { padding-left: 32px; }")
        self.setCursor(Qt.PointingHandCursor)
        view = QListView()
        self.setView(view)
        theme_bus().changed.connect(lambda _p: self.update())

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._icon:
            painter = QPainter(self)
            painter.drawPixmap(11, (self.height() - 15) // 2, get_pixmap(self._icon, pal()["text2"], 15))
            painter.end()


class NumberInput(QFrame):
    """components/forms/NumberInput - `−  value  +` stepper. The wrapped
    QDoubleSpinBox is exposed as `.spin` so existing code keeps working."""

    def __init__(self, minimum: float = 0, maximum: float = 99, step: float = 1, decimals: int = 0,
                 prefix: str = "", suffix: str = "", size: str = "md", integer: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("numberInput")
        h = 28 if size == "sm" else 34
        self.setFixedHeight(h)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 0, 3, 0)
        lay.setSpacing(2)
        from PyQt5.QtWidgets import QSpinBox
        self.spin = QSpinBox() if integer else QDoubleSpinBox()
        if not integer:
            self.spin.setDecimals(decimals)
        self.spin.setRange(minimum, maximum)
        self.spin.setSingleStep(step)
        self.spin.setPrefix(prefix)
        self.spin.setSuffix(suffix)
        self.spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin.setAlignment(Qt.AlignCenter)
        self.spin.setStyleSheet("QAbstractSpinBox { background: transparent; border: none; padding: 0; min-height: 0; }")
        self.minus = IconButton("minus", "Decrease", "sm")
        self.plus = IconButton("plus", "Increase", "sm")
        for b in (self.minus, self.plus):
            b.setFixedSize(24, 24)
            b.setIconSize(QSize(14, 14))
            b.setAutoRepeat(True)
        self.minus.clicked.connect(self.spin.stepDown)
        self.plus.clicked.connect(self.spin.stepUp)
        lay.addWidget(self.minus)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.plus)
        self.setMinimumWidth(112)
        on_theme(self, self._style)

    def _style(self, p):
        self.setStyleSheet(f"""
            QFrame#numberInput {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; }}
            QFrame#numberInput:hover {{ border-color: {p['border_strong']}; }}
        """)


class Switch(QCheckBox):
    """components/forms/Switch - 34x20 pill toggle with an optional label."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(label, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._font = font(13.5)
        theme_bus().changed.connect(lambda _p: self.update())

    def sizeHint(self):
        w = 34
        if self.text():
            w += 10 + QFontMetrics(self._font).horizontalAdvance(self.text())
        return QSize(w, 22)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        track = QRectF(0, (self.height() - 20) / 2, 34, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(p["accent"] if self.isChecked() else p["surface4"]))
        painter.drawRoundedRect(track, 10, 10)
        knob_x = track.left() + (16 if self.isChecked() else 2)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawEllipse(QRectF(knob_x, track.top() + 3, 16, 16))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(knob_x, track.top() + 2, 16, 16))
        if self.text():
            painter.setPen(qc(p["text"]))
            painter.setFont(self._font)
            painter.drawText(QRect(44, 0, self.width() - 44, self.height()), Qt.AlignVCenter, self.text())
        painter.end()


# ---------------------------------------------------------------- surfaces

class GlassPanel(QFrame):
    """components/layout/Panel - glass surface, optional header with icon,
    title and actions, and a body with 12px gaps."""

    def __init__(self, title: Optional[str] = None, icon_name: Optional[str] = None, parent=None,
                 padding: int = 16, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("glassPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QWidget()
        self.header.setObjectName("panelHeader")
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        self.header.setFixedHeight(48)
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(16, 0, 10, 0)
        self.header_layout.setSpacing(10)
        self.icon_label = IconLabel(icon_name or "square", "text3", 16)
        self.icon_label.setVisible(bool(icon_name))
        self.header_layout.addWidget(self.icon_label)
        self.title_label = QLabel(title or "")
        self.title_label.setProperty("cls", "panelTitle")
        self.header_layout.addWidget(self.title_label)
        self.header_layout.addStretch(1)
        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(4)
        self.header_layout.addLayout(self.actions_layout)
        outer.addWidget(self.header)
        self.header.setVisible(title is not None)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(padding, padding, padding, padding)
        self.body_layout.setSpacing(spacing)
        outer.addWidget(self.body, 1)

    def set_title(self, title: str):
        self.title_label.setText(title)

    def add_title_widget(self, widget: QWidget):
        """Widgets that sit right after the title (e.g. a status Badge)."""
        self.header_layout.insertWidget(self.header_layout.indexOf(self.title_label) + 1, widget)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions_layout.addWidget(widget)
        return widget

    def add_icon_button(self, icon_name: str, tooltip: str, **kw) -> IconButton:
        return self.add_action(IconButton(icon_name, tooltip, "sm", **kw))

    # compatibility with the first GlassPanel
    def add_header_widget(self, widget: QWidget):
        self.add_action(widget)

    def apply_theme(self, _p=None):
        pass


class Card(QFrame):
    """The inset surface-2 block the kit uses inside panels (item details,
    device card)."""

    def __init__(self, padding: int = 14, spacing: int = 12, parent=None):
        super().__init__(parent)
        self.setProperty("cls", "card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(padding, padding, padding, padding)
        self.layout_.setSpacing(spacing)


class PageHeader(QWidget):
    """The kit's screen header: h1 + secondary line on the left, controls on
    the right, bottom-aligned (padding 8px 4px 0)."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 0)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title_label = text(title, "h1")
        col.addWidget(self.title_label)
        self.subtitle_label = text(subtitle, "secondary", wrap=True)
        self.subtitle_label.setVisible(bool(subtitle))
        col.addWidget(self.subtitle_label)
        lay.addLayout(col, 1)
        self.right = QHBoxLayout()
        self.right.setSpacing(8)
        lay.addLayout(self.right)
        lay.setAlignment(self.right, Qt.AlignBottom)

    def add(self, widget: QWidget) -> QWidget:
        self.right.addWidget(widget, 0, Qt.AlignBottom)
        return widget


class SegmentedTabs(QFrame):
    """components/navigation/Tabs - segmented control."""

    changed = pyqtSignal(str)

    def __init__(self, tabs: Sequence[Tuple], parent=None):
        super().__init__(parent)
        self.setProperty("cls", "segmented")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        self._icons = {}
        for spec in tabs:
            key, label = spec[0], spec[1]
            icon = spec[2] if len(spec) > 2 else None
            btn = QPushButton(label)
            btn.setProperty("cls", "seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(14, 14))
            btn.clicked.connect(lambda _c, k=key: self._pick(k))
            btn.toggled.connect(lambda _c: self._retint(pal()))
            self.group.addButton(btn)
            lay.addWidget(btn)
            self.buttons[key] = btn
            self._icons[key] = icon
        if tabs:
            self.buttons[tabs[0][0]].setChecked(True)
        on_theme(self, self._retint)

    def _retint(self, p):
        for key, btn in self.buttons.items():
            if self._icons[key]:
                btn.setIcon(get_icon(self._icons[key], p["text"] if btn.isChecked() else p["text2"], 14))

    def set_label(self, key: str, label: str):
        self.buttons[key].setText(label)

    def _pick(self, key: str):
        self.changed.emit(key)

    def set_current(self, key: str):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def current(self) -> Optional[str]:
        for key, btn in self.buttons.items():
            if btn.isChecked():
                return key
        return None


class CollapsibleSection(QFrame):
    """components/layout/CollapsibleSection - fold-away group with icon,
    title and count; 44px header, hairline divider under it."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, icon_name: Optional[str] = None, count=None,
                 open_: bool = True, parent=None):
        super().__init__(parent)
        self.setProperty("cls", "section")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._open = open_
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.header = QPushButton()
        self.header.setProperty("cls", "sectionHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(self.toggle)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.setSpacing(10)
        self.chevron = IconLabel("chevron-right", "text3", 14)
        hl.addWidget(self.chevron)
        if icon_name:
            hl.addWidget(IconLabel(icon_name, "text2", 16))
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.title_label, 1)
        self.count_label = text("" if count is None else str(count), "small")
        self.count_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        hl.addWidget(self.count_label)
        for child in self.header.findChildren(QLabel):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.header)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 2, 4, 16)
        self.body_layout.setSpacing(10)
        lay.addWidget(self.body)
        self._sync()

    def set_count(self, count):
        self.count_label.setText("" if count is None else str(count))

    def set_last(self, last: bool = True):
        self.setProperty("last", "true" if last else "false")
        restyle(self)

    def toggle(self):
        self._open = not self._open
        self._sync()
        self.toggled.emit(self._open)

    def set_open(self, open_: bool):
        if open_ != self._open:
            self.toggle()

    def _sync(self):
        self.body.setVisible(self._open)
        self.chevron.set_icon("chevron-down" if self._open else "chevron-right")

    def apply_theme(self, _p=None):
        pass


class DetailList(QWidget):
    """components/data/DetailList - key/value grid, 16px column gap, 8px rows."""

    def __init__(self, items: Iterable = (), parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(8)
        self._grid.setColumnStretch(1, 1)
        self.set_items(items)

    def set_items(self, items: Iterable):
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for row, entry in enumerate(items):
            key, value = entry[0], entry[1]
            mono = len(entry) > 2 and entry[2]
            k = text(key, "small")
            k.setProperty("cls", "caption")
            k.setStyleSheet("font-size: 12.5px;")
            v = QLabel(str(value))
            v.setWordWrap(not mono)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if mono:
                v.setProperty("cls", "mono")
                v.setStyleSheet(f"color: {pal()['text']};")
            else:
                v.setStyleSheet("font-size: 12.5px;")
            self._grid.addWidget(k, row, 0, Qt.AlignTop)
            self._grid.addWidget(v, row, 1, Qt.AlignTop)


# ---------------------------------------------------------------- rows (ListBox)

ROW_ROLE = Qt.UserRole + 101


def row_data(item: QListWidgetItem) -> dict:
    return item.data(ROW_ROLE) or {}


def make_row(kind: str = "result", **data) -> QListWidgetItem:
    """A list item rendered by RowDelegate.

    kind "result" (ResultRow): icon, color, title, subtitle, path, score, badge
    kind "item"   (ListItem):  icon, title, meta, (trailing handled by caller)
    kind "nav"    (SettingsNav): icon, title
    kind "person" (PersonTile): title, count, image (path)
    kind "header" : a non-selectable eyebrow group label
    """
    item = QListWidgetItem(data.get("title", ""))
    data["kind"] = kind
    item.setData(ROW_ROLE, data)
    if kind == "header":
        item.setFlags(Qt.NoItemFlags)
    return item


class RowDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._title = font(13.5, 500)
        self._sub = font(12.5)
        self._mono = font(12, 400, FONT_MONO)
        self._eyebrow = font(11, 600)
        self._eyebrow.setLetterSpacing(QFont.PercentageSpacing, 106)
        self._thumbs = {}

    def sizeHint(self, option, index):
        d = index.data(ROW_ROLE) or {}
        kind = d.get("kind", "result")
        if kind == "result":
            lines = 1 + bool(d.get("subtitle")) + bool(d.get("path"))
            h = max(54, 20 + 19 + 17 * (lines - 1))
            return QSize(option.rect.width(), h + 2)
        if kind == "item":
            return QSize(option.rect.width(), 40)
        if kind == "nav":
            return QSize(option.rect.width(), 38)
        if kind == "person":
            return QSize(118, 138)
        if kind == "header":
            return QSize(option.rect.width(), 30)
        return super().sizeHint(option, index)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        d = index.data(ROW_ROLE)
        if not d:
            return super().paint(painter, option, index)
        p = pal()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        kind = d.get("kind", "result")
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        r = QRectF(option.rect)

        if kind == "header":
            painter.setPen(qc(p["text3"]))
            painter.setFont(self._eyebrow)
            painter.drawText(r.adjusted(10, 6, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, d.get("title", "").upper())
            painter.restore()
            return

        box = r.adjusted(0, 1, 0, -1) if kind != "person" else r.adjusted(4, 4, -4, -4)
        radius = 12 if kind == "person" else 8
        if kind == "nav":
            bg = p["surface3"] if selected else (p["surface2"] if hover else None)
            ring = False
        else:
            bg = p["accent_soft"] if selected else (p["surface2"] if hover else None)
            ring = selected and kind in ("result", "person")
        if bg:
            painter.setPen(QPen(qc(p["accent_ring"]), 1) if ring else Qt.NoPen)
            painter.setBrush(qc(bg))
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if kind == "result":
            self._paint_result(painter, box, d, p)
        elif kind == "item":
            self._paint_item(painter, box, d, p, selected)
        elif kind == "nav":
            self._paint_nav(painter, box, d, p, selected)
        elif kind == "person":
            self._paint_person(painter, box, d, p)
        painter.restore()

    def _paint_result(self, painter, box, d, p):
        color = d.get("color")
        tile = QRectF(box.left() + 12, box.center().y() - 17, 34, 34)
        painter.setPen(Qt.NoPen)
        painter.setBrush(mix(color, 0.16) if color else qc(p["surface3"]))
        painter.drawRoundedRect(tile, 8, 8)
        icon_color = color or p["text2"]
        pm = get_pixmap(d.get("icon", "file"), icon_color, 17)
        painter.drawPixmap(QPointF(tile.left() + 8.5, tile.top() + 8.5), pm)

        right = box.right() - 12
        badge_text = d.get("badge")
        score = d.get("score")
        if score is not None:
            pct = round(score * 100)
            badge_text = f"{pct}%"
            tone = "accent" if pct >= 80 else ("neutral" if pct >= 50 else "faint")
        else:
            tone = d.get("badge_tone", "neutral")
        if badge_text:
            right = self._paint_badge(painter, right, box.center().y(), badge_text, tone, p) - 12

        x = tile.right() + 12
        w = right - x
        lines = [(d.get("title", ""), self._title, p["text"])]
        if d.get("subtitle"):
            lines.append((d["subtitle"], self._sub, p["text2"]))
        if d.get("path"):
            lines.append((d["path"], self._mono, p["text3"]))
        heights = [19] + [17] * (len(lines) - 1)
        y = box.center().y() - sum(heights) / 2
        for (value, f, color), h in zip(lines, heights):
            painter.setFont(f)
            painter.setPen(qc(color))
            fm = QFontMetrics(f)
            painter.drawText(QRectF(x, y, w, h), Qt.AlignLeft | Qt.AlignVCenter,
                             fm.elidedText(value, Qt.ElideRight if f is not self._mono else Qt.ElideMiddle, int(w)))
            y += h

    def _paint_badge(self, painter, right, cy, label, tone, p) -> float:
        colors = {
            "neutral": (p["surface3"], p["text2"]), "accent": (p["accent_soft"], p["accent_text"]),
            "success": (p["success_soft"], p["success"]), "warning": (p["warning_soft"], p["warning"]),
            "danger": (p["danger_soft"], p["danger"]), "faint": (p["surface3"], p["text3"]),
        }[tone]
        f = font(11.5, 600)
        w = QFontMetrics(f).horizontalAdvance(label) + 16
        rect = QRectF(right - w, cy - 11, w, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(colors[0]))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(qc(colors[1]))
        painter.setFont(f)
        painter.drawText(rect, Qt.AlignCenter, label)
        return rect.left()

    def _paint_item(self, painter, box, d, p, selected):
        x = box.left() + 10
        if d.get("icon"):
            pm = get_pixmap(d["icon"], p["accent_text"] if selected else p["text2"], 16)
            painter.drawPixmap(QPointF(x, box.center().y() - 8), pm)
            x += 26
        right = box.right() - 10 - d.get("trailing_width", 0)
        if d.get("meta"):
            painter.setFont(self._mono)
            fm = QFontMetrics(self._mono)
            mw = fm.horizontalAdvance(d["meta"])
            painter.setPen(qc(p["text3"]))
            painter.drawText(QRectF(right - mw, box.top(), mw, box.height()), Qt.AlignVCenter, d["meta"])
            right -= mw + 10
        painter.setFont(font(13.5))
        painter.setPen(qc(p["text"]))
        fm = painter.fontMetrics()
        painter.drawText(QRectF(x, box.top(), right - x, box.height()), Qt.AlignVCenter,
                         fm.elidedText(d.get("title", ""), Qt.ElideRight, int(right - x)))

    def _paint_nav(self, painter, box, d, p, selected):
        x = box.left() + 10
        if d.get("icon"):
            pm = get_pixmap(d["icon"], p["accent_text"] if selected else p["text2"], 16)
            painter.drawPixmap(QPointF(x, box.center().y() - 8), pm)
            x += 26
        painter.setFont(font(13.5, 600 if selected else 400))
        painter.setPen(qc(p["text"] if selected else p["text2"]))
        painter.drawText(QRectF(x, box.top(), box.right() - x, box.height()), Qt.AlignVCenter, d.get("title", ""))

    def _paint_person(self, painter, box, d, p):
        circle = QRectF(box.center().x() - 36, box.top() + 10, 72, 72)
        image = d.get("image")
        pm = None
        if image:
            pm = self._thumbs.get(image)
            if pm is None and os.path.exists(image):
                src = QPixmap(image)
                if not src.isNull():
                    pm = src.scaled(144, 144, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    pm.setDevicePixelRatio(2)
                    self._thumbs[image] = pm
        path = QPainterPath()
        path.addEllipse(circle)
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(p["surface3"]))
        painter.drawEllipse(circle)
        if pm is not None:
            painter.save()
            painter.setClipPath(path)
            ox = circle.left() - (pm.width() / 2 - 72) / 2
            oy = circle.top() - (pm.height() / 2 - 72) / 2
            painter.drawPixmap(QPointF(ox, oy), pm)
            painter.restore()
        else:
            painter.drawPixmap(QPointF(circle.center().x() - 14, circle.center().y() - 14),
                               get_pixmap("user", p["text3"], 28))
        name = d.get("title", "")
        unnamed = not name or name.startswith("Unnamed")
        painter.setFont(font(12.5, 500))
        painter.setPen(qc(p["text2"] if unnamed else p["text"]))
        fm = painter.fontMetrics()
        painter.drawText(QRectF(box.left(), circle.bottom() + 8, box.width(), 18), Qt.AlignHCenter,
                         fm.elidedText(name, Qt.ElideRight, int(box.width() - 8)))
        count = d.get("count", 0)
        painter.setFont(font(11.5))
        painter.setPen(qc(p["text3"]))
        painter.drawText(QRectF(box.left(), circle.bottom() + 25, box.width(), 16), Qt.AlignHCenter,
                         f"{count} photo{'' if count == 1 else 's'}")


class RowList(QListWidget):
    """components/data/ListBox - a scrolling list of delegate-painted rows
    with the kit's empty state (icon + message)."""

    def __init__(self, empty: str = "Nothing here yet", empty_icon: str = "inbox",
                 grid: bool = False, parent=None):
        super().__init__(parent)
        self.setProperty("cls", "rows")
        self.setItemDelegate(RowDelegate(self))
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSpacing(0)
        self.setUniformItemSizes(False)
        self.empty_text = empty
        self.empty_icon = empty_icon
        if grid:
            self.setViewMode(QListWidget.IconMode)
            self.setResizeMode(QListWidget.Adjust)
            self.setMovement(QListWidget.Static)
            self.setGridSize(QSize(122, 142))
            self.setWrapping(True)
        theme_bus().changed.connect(lambda _p: self.viewport().update())

    def set_empty(self, message: str, icon: Optional[str] = None):
        self.empty_text = message
        if icon:
            self.empty_icon = icon
        self.viewport().update()

    def visible_count(self) -> int:
        return sum(1 for i in range(self.count()) if not self.item(i).isHidden())

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.visible_count() == 0 and self.empty_text:
            p = pal()
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing)
            rect = self.viewport().rect()
            cy = rect.center().y()
            painter.drawPixmap(QPointF(rect.center().x() - 11, cy - 26), get_pixmap(self.empty_icon, p["text3"], 22))
            painter.setPen(qc(p["text3"]))
            painter.setFont(font(12.5))
            painter.drawText(QRect(rect.left() + 16, cy + 4, rect.width() - 32, 40),
                             Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.empty_text)
            painter.end()


class SettingsNav(RowList):
    """components/navigation/SettingsNav - 210px category list."""

    def __init__(self, items: Sequence[Tuple[str, str]], parent=None):
        super().__init__("", parent=parent)
        self.setFixedWidth(210)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for title, icon in items:
            self.addItem(make_row("nav", title=title, icon=icon))


# ---------------------------------------------------------------- swatch

class ThemeSwatch(QPushButton):
    """components/brand/ThemeSwatch - a mini preview of a mode + accent."""

    def __init__(self, preview: dict, label: str, parent=None):
        super().__init__(parent)
        self.preview = preview
        self.label = label
        self.setCheckable(True)
        self.setProperty("cls", "swatch")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(140, 104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._hover = False
        theme_bus().changed.connect(lambda _p: self.update())

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        s = self.preview
        cur = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        outer = QRectF(self.rect()).adjusted(3.5, 3.5, -3.5, -3.5)
        if self.isChecked():
            painter.setPen(QPen(qc(cur["accent_soft"]), 6))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(outer, 12, 12)
        border = cur["accent"] if self.isChecked() else (cur["border_strong"] if self._hover else cur["border"])
        painter.setPen(QPen(qc(border), 1))
        painter.setBrush(qc(s["bg"]))
        painter.drawRoundedRect(outer, 12, 12)

        box = QRectF(outer.left() + 10, outer.top() + 10, outer.width() - 20, 54)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        painter.setPen(QPen(qc(s["border"]), 1))
        painter.setBrush(qc(s["surface2"]))
        painter.drawPath(path)
        painter.save()
        painter.setClipPath(path)
        g = QRadialGradient(box.topLeft(), 120)
        g.setColorAt(0, qc(s["glow1"]))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(box, QBrush(g))
        painter.restore()
        painter.setPen(Qt.NoPen)
        bx, by = box.left() + 8, box.top() + 8
        painter.setBrush(qc(s["accent"]))
        painter.drawRoundedRect(QRectF(bx, by, 28, 6), 3, 3)
        painter.setBrush(qc(s["surface4"]))
        painter.drawRoundedRect(QRectF(bx + 32, by, 18, 6), 3, 3)
        painter.drawRoundedRect(QRectF(bx, by + 12, (box.width() - 16) * 0.7, 6), 3, 3)
        painter.setBrush(qc(s["surface3"]))
        painter.drawRoundedRect(QRectF(bx, by + 24, (box.width() - 16) * 0.45, 6), 3, 3)

        ly = box.bottom() + 10
        painter.setBrush(qc(s["accent"]))
        painter.drawEllipse(QRectF(outer.left() + 10, ly + 3, 12, 12))
        painter.setPen(qc(s["text"]))
        painter.setFont(font(12.5, 500))
        painter.drawText(QRectF(outer.left() + 30, ly, outer.width() - 60, 18), Qt.AlignVCenter, self.label)
        if self.isChecked():
            painter.drawPixmap(QPointF(outer.right() - 24, ly + 2), get_pixmap("check", s["accent_text"], 14))
        painter.end()


# ---------------------------------------------------------------- window chrome

class GlowBackdrop(QWidget):
    """components/layout/AppWindow - base color plus two soft accent glows
    (900x520 at 12%,-10% and 800x600 at 105%,110%). Glass panels are
    translucent, so the glow shows through them like the kit's blur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        theme_bus().changed.connect(lambda _p: self.update())

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.fillRect(self.rect(), qc(p["bg"]))
        w, h = self.width(), self.height()
        for (cx, cy, rx, ry, color) in (
            (0.12 * w, -0.10 * h, 900, 520, p["glow1"]),
            (1.05 * w, 1.10 * h, 800, 600, p["glow2"]),
        ):
            painter.save()
            painter.translate(cx, cy)
            painter.scale(1.0, ry / rx)
            g = QRadialGradient(QPointF(0, 0), rx * 0.7)
            g.setColorAt(0, qc(color))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            painter.fillRect(QRectF(-rx, -rx, rx * 2, rx * 2), QBrush(g))
            painter.restore()
        painter.end()


class StatusStrip(QWidget):
    """components/layout/StatusBar - dot + message, right-hand hint."""

    TONES = {"neutral": "text3", "success": "success", "busy": "accent", "danger": "danger"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(6, 6)
        lay.addWidget(self.dot)
        self.label = QLabel("Ready")
        self.label.setObjectName("statusText")
        lay.addWidget(self.label, 1)
        self.right = QLabel("")
        self.right.setObjectName("statusRight")
        lay.addWidget(self.right)
        self._tone = "neutral"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._base = ("Ready", "neutral")
        self._timer.timeout.connect(lambda: self._set(*self._base))
        on_theme(self, lambda _p: self._paint_dot())

    def _paint_dot(self):
        color = pal()[self.TONES.get(self._tone, "text3")]
        self.dot.setStyleSheet(f"background: {color}; border-radius: 3px;")

    def _set(self, message: str, tone: str):
        self.label.setText(message)
        self._tone = tone
        self._paint_dot()

    def set_status(self, message: str, tone: str = "neutral"):
        """The persistent status for the current screen."""
        self._base = (message, tone)
        if not self._timer.isActive():
            self._set(message, tone)

    def showMessage(self, message: str, timeout: int = 0, tone: str = "neutral"):
        """QStatusBar-compatible: a temporary message."""
        self._set(message, tone)
        if timeout:
            self._timer.start(timeout)
        else:
            self._timer.stop()
            self._base = (message, tone)


class Toast(QLabel):
    """The kit's bottom-centre confirmation toast."""

    def __init__(self, parent: QWidget, message: str, ms: int = 2400):
        super().__init__(message, parent)
        p = pal()
        self.setStyleSheet(
            f"background: {p['pop']}; color: {p['text']}; border: 1px solid {p['border_strong']};"
            "border-radius: 10px; padding: 10px 16px;"
        )
        self.adjustSize()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 48)
        self.show()
        self.raise_()
        QTimer.singleShot(ms, self.deleteLater)


def toast(widget: QWidget, message: str):
    Toast(widget.window(), message)


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: Optional[int] = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for i, w in enumerate(widgets):
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif hasattr(w, "addWidget") and not isinstance(w, QWidget):
            lay.addLayout(w)
        else:
            lay.addWidget(w, 1 if stretch_at == i else 0)
    return lay


class ProgressBar(QWidget):
    """components/data/ProgressBar - 4px bar with an optional label/detail
    line. Range (0, 0) means indeterminate (a sliding 35% segment).
    QProgressBar-compatible: setRange / setValue / setVisible."""

    def __init__(self, label: str = "", parent=None):
        super().__init__(parent)
        self._label, self._detail = label, ""
        self._min, self._max, self._value = 0, 0, 0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(28 if label else 4)
        theme_bus().changed.connect(lambda _p: self.update())

    def set_label(self, label: str, detail: str = ""):
        self._label, self._detail = label, detail
        self.setFixedHeight(28 if (label or detail) else 4)
        self.update()

    def set_detail(self, detail: str):
        self._detail = detail
        self.update()

    def setRange(self, minimum: int, maximum: int):
        self._min, self._max = minimum, maximum
        self._sync_timer()
        self.update()

    def setValue(self, value: int):
        self._value = value
        self.update()

    def _busy(self) -> bool:
        return self._max <= self._min

    def _sync_timer(self):
        if self._busy() and self.isVisible():
            self._timer.start(16)
        else:
            self._timer.stop()

    def showEvent(self, e):
        self._sync_timer()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self._phase = (self._phase + 16 / 1200) % 1.0
        self.update()

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        if self._label or self._detail:
            painter.setFont(font(12.5))
            painter.setPen(qc(p["text2"]))
            painter.drawText(QRect(0, 0, w, 18), Qt.AlignLeft | Qt.AlignVCenter, self._label)
            detail = self._detail
            if not detail and not self._busy():
                span = max(self._max - self._min, 1)
                detail = f"{round((self._value - self._min) * 100 / span)}%"
            painter.setPen(qc(p["text3"]))
            painter.drawText(QRect(0, 0, w, 18), Qt.AlignRight | Qt.AlignVCenter, detail)
        track = QRectF(0, self.height() - 4, w, 4)
        path = QPainterPath()
        path.addRoundedRect(track, 2, 2)
        painter.setClipPath(path)
        painter.fillRect(track, qc(p["surface3"]))
        painter.setPen(Qt.NoPen)
        painter.setBrush(qc(p["accent"]))
        if self._busy():
            seg = w * 0.35
            x = -seg + (w + seg) * self._phase
            painter.drawRoundedRect(QRectF(x, track.top(), seg, 4), 2, 2)
        else:
            span = max(self._max - self._min, 1)
            frac = min(max((self._value - self._min) / span, 0), 1)
            painter.drawRoundedRect(QRectF(0, track.top(), w * frac, 4), 2, 2)
        painter.end()
