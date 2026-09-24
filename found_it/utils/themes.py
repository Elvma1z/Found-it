import colorsys

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QBrush, QColor, QRadialGradient
from PyQt5.QtWidgets import QWidget


def repolish(widget: QWidget):
    """Force Qt to re-evaluate `[cls="..."]` style-sheet selectors on a
    widget and all its descendants. setStyleSheet() is supposed to trigger
    this on its own, but in large/deeply-nested widget trees (e.g. Room
    Setup, Settings) Qt can leave already-polished children showing their
    previous theme's colors until unpolish/polish is forced explicitly."""
    for w in [widget] + widget.findChildren(QWidget):
        style = w.style()
        style.unpolish(w)
        style.polish(w)

# Hue (degrees, 0-360) for each rainbow color. Order doubles as display order.
RAINBOW_HUES = [
    ("Red", 0),
    ("Orange", 30),
    ("Yellow", 50),
    ("Green", 130),
    ("Blue", 210),
    ("Indigo", 248),
    ("Violet", 285),
]

THEME_NAMES = [name for name, _ in RAINBOW_HUES] + ["White", "Dark"]


def _hex(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _rgba(hex_color, alpha):
    """`hex_color` at `alpha` (0-1) as a QSS rgba() string, for soft glows
    that let whatever is underneath bleed through."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


def _add_gradients(p):
    """Derive the blended "aura" brushes from a palette's solid colors.
    Solid keys stay untouched because QPainter code (room map, splash)
    needs plain colors; the gradient keys are QSS brush strings only."""
    a, a2 = p["accent"], p["accent2"]
    p["bg_grad"] = (
        "qradialgradient(cx:0.15, cy:0, radius:1.25, fx:0.15, fy:0, "
        f"stop:0 {p['bg_glow']}, stop:0.55 {p['bg']}, stop:1 {p['bg_deep']})"
    )
    p["header_grad"] = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {p['header']}, stop:0.5 {p['bg_glow']}, stop:1 {p['header']})"
    )
    p["panel_grad"] = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {p['selected']}, stop:1 {p['panel']})"
    )
    p["selected_grad"] = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {_rgba(a, 0.28)}, stop:1 {_rgba(a2, 0.18)})"
    )
    p["hover_grad"] = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {_rgba(a, 0.16)}, stop:1 {_rgba(a2, 0.10)})"
    )
    p["accent_grad"] = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a}, stop:1 {a2})"
    )
    p["accent_grad_hover"] = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        f"stop:0 {p['accent_hover']}, stop:1 {p['accent2_hover']})"
    )
    # A line that fades in from nothing, peaks in the accent blend, and
    # fades out again - used for the nav bar's bottom edge and separators.
    p["glow_line"] = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        f"stop:0 {_rgba(a, 0)}, stop:0.35 {_rgba(a, 0.85)}, "
        f"stop:0.65 {_rgba(a2, 0.85)}, stop:1 {_rgba(a2, 0)})"
    )
    p["glow"] = _rgba(a, 0.55)
    return p


def _palette_for_hue(hue):
    # The companion hue sits a little further round the wheel so gradients
    # drift between two related colors instead of fading one to black.
    hue2 = (hue + 38) % 360
    return _add_gradients({
        "bg": _hex(hue, 0.22, 0.075),
        "bg_glow": _hex(hue, 0.45, 0.155),
        "bg_deep": _hex(hue2, 0.30, 0.045),
        "header": _hex(hue, 0.26, 0.055),
        "panel": _hex(hue, 0.28, 0.13),
        "selected": _hex(hue, 0.30, 0.19),
        "hover": _hex(hue, 0.32, 0.26),
        "border": _hex(hue, 0.15, 0.16),
        "accent": _hex(hue, 0.75, 0.62),
        "accent_hover": _hex(hue, 0.75, 0.70),
        "accent2": _hex(hue2, 0.80, 0.60),
        "accent2_hover": _hex(hue2, 0.80, 0.68),
        "text": "#e0e0e0",
        "text_dim": "#aaaaaa",
        "text_faint": "#777777",
    })


def _white_palette():
    return _add_gradients({
        "bg": "#f4f4f6",
        "bg_glow": "#ecebfb",
        "bg_deep": "#f7eef8",
        "header": "#ffffff",
        "panel": "#e9e9ec",
        "selected": "#dcdce2",
        "hover": "#cfcfd6",
        "border": "#c7c7cf",
        "accent": "#5b53e0",
        "accent_hover": "#443cc9",
        "accent2": "#b04fd8",
        "accent2_hover": "#9a3cc2",
        "text": "#1a1a1f",
        "text_dim": "#55555c",
        "text_faint": "#8a8a91",
    })


def _dark_palette():
    return _add_gradients({
        "bg": "#1a1a1d",
        "bg_glow": "#23222e",
        "bg_deep": "#141318",
        "header": "#121214",
        "panel": "#232326",
        "selected": "#2d2d31",
        "hover": "#39393e",
        "border": "#303034",
        "accent": "#6c6cf0",
        "accent_hover": "#8080f5",
        "accent2": "#a86cf0",
        "accent2_hover": "#b980f5",
        "text": "#e8e8ea",
        "text_dim": "#a5a5ac",
        "text_faint": "#707078",
    })


THEMES = {name: _palette_for_hue(hue) for name, hue in RAINBOW_HUES}
THEMES["White"] = _white_palette()
THEMES["Dark"] = _dark_palette()


def get_palette(theme_name: str) -> dict:
    return THEMES.get(theme_name, THEMES["Indigo"])


def aura_brush(p: dict, rect) -> QBrush:
    """QPainter counterpart of `bg_grad`: a soft glow from the top-left of
    `rect` that blends through the base background into the companion hue,
    so painted canvases (room map, Room Setup) match the window behind them."""
    r = QRectF(rect)
    grad = QRadialGradient(QPointF(r.left() + r.width() * 0.2, r.top()),
                           max(r.width(), r.height()) * 1.1)
    grad.setColorAt(0, QColor(p["bg_glow"]))
    grad.setColorAt(0.6, QColor(p["bg"]))
    grad.setColorAt(1, QColor(p["bg_deep"]))
    return QBrush(grad)


def widget_qss(p: dict) -> str:
    """Shared stylesheet for the widget "classes" (Qt dynamic `cls` property)
    used across the panels, so every interactive control - inputs, lists,
    buttons - shifts with the active theme instead of a few of them being
    hardcoded to what used to be the only look."""
    return f"""
        QLabel[cls="title"] {{ color: {p['text']}; }}
        QLabel[cls="muted"] {{ color: {p['text_dim']}; font-size: 11px; }}
        QLabel[cls="hint"] {{ color: {p['text_faint']}; font-size: 10px; }}
        QLabel[cls="status"] {{ color: {p['accent']}; font-size: 11px; }}
        QFrame[cls="sep"] {{ color: {p['border']}; }}
        QCheckBox {{ color: {p['text_dim']}; }}
        QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
            background-color: {p['panel']}; color: {p['text']};
            border: 1px solid {p['border']}; border-radius: 4px;
            padding: 6px; font-size: 12px;
        }}
        QLineEdit:hover, QDoubleSpinBox:hover, QSpinBox:hover, QComboBox:hover {{
            border: 1px solid {p['hover']};
        }}
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
            border: 1px solid {p['accent']}; background-color: {p['selected']};
        }}
        QComboBox::drop-down {{ border: none; }}
        QComboBox QAbstractItemView {{
            background-color: {p['panel']}; color: {p['text']};
            border: 1px solid {p['border']};
            selection-background-color: {p['selected']};
            selection-color: {p['text']};
            outline: none;
        }}
        QListWidget {{
            background-color: {p['bg']}; color: {p['text']};
            border: 1px solid {p['border']}; border-radius: 4px; padding: 4px;
        }}
        QListWidget::item {{ padding: 6px; border-bottom: 1px solid {p['panel']}; }}
        QListWidget::item:selected {{
            background: {p['selected_grad']}; color: {p['text']};
            border-left: 2px solid {p['accent']};
        }}
        QListWidget::item:hover:!selected {{ background: {p['hover_grad']}; }}
        QScrollArea {{ background-color: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
        QScrollBar:vertical {{
            background-color: {p['bg']}; width: 12px; margin: 0; border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {p['border']}; min-height: 24px; border-radius: 6px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {p['accent_grad']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        QPushButton[cls="primary"] {{
            background: {p['accent_grad']}; color: white;
            border: 1px solid {p['glow']};
            border-radius: 17px; padding: 8px 20px; font-weight: bold;
        }}
        QPushButton[cls="primary"]:hover {{ background: {p['accent_grad_hover']}; border-color: {p['accent2_hover']}; }}
        QPushButton[cls="primary"]:pressed {{ background: {p['accent_grad']}; padding-top: 9px; padding-bottom: 7px; }}
        QPushButton[cls="primary"]:disabled {{ background-color: {p['border']}; color: {p['text_faint']}; }}
        QPushButton[cls="secondary"] {{
            background: {p['panel_grad']}; color: {p['text_dim']};
            border: 1px solid {p['border']}; border-radius: 6px; padding: 6px 14px; font-size: 12px;
        }}
        QPushButton[cls="secondary"]:hover {{ background: {p['selected_grad']}; color: {p['text']}; border-color: {p['glow']}; }}
        QPushButton[cls="secondary"]:checked {{ background: {p['accent_grad']}; color: white; border-color: {p['glow']}; }}
        QPushButton[cls="secondary"]:disabled {{ color: {p['text_faint']}; }}
        QPushButton[cls="destructive"] {{
            background-color: transparent; color: #e57373;
            border: 1px solid #e57373; border-radius: 4px; padding: 6px 14px; font-size: 12px;
        }}
        QPushButton[cls="destructive"]:hover {{ background-color: #e53935; color: white; border-color: #e53935; }}
        QPushButton[cls="destructive"]:checked {{ background-color: #e53935; color: white; border-color: #e53935; }}
        QPushButton[cls="destructive"]:disabled {{ color: {p['text_faint']}; border-color: {p['border']}; }}
        QPushButton[cls="muted"] {{
            background-color: transparent; color: {p['text_dim']};
            border: 1px solid transparent; border-radius: 4px; padding: 6px 14px; font-size: 12px;
        }}
        QPushButton[cls="muted"]:hover {{ background: {p['hover_grad']}; color: {p['text']}; border-color: {p['border']}; }}
        QPushButton[cls="muted"]:checked {{ background: {p['selected_grad']}; color: {p['text']}; border-color: {p['glow']}; }}
        QPushButton[cls="muted"]:disabled {{ color: {p['text_faint']}; }}
        QProgressBar {{
            background-color: {p['bg']}; border: 1px solid {p['border']};
            border-radius: 4px; text-align: center; color: {p['text_dim']};
            max-height: 20px;
        }}
        QProgressBar::chunk {{ background: {p['accent_grad']}; border-radius: 3px; }}
        QTabWidget::pane {{
            background-color: {p['bg']}; border: 1px solid {p['border']};
            border-radius: 4px; top: -1px;
        }}
        QTabBar::tab {{
            background-color: {p['panel']}; color: {p['text_dim']};
            border: 1px solid {p['border']}; border-bottom: none;
            border-top-left-radius: 4px; border-top-right-radius: 4px;
            padding: 6px 16px; margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {p['selected_grad']}; color: {p['text']};
            border-bottom: 2px solid {p['accent']};
        }}
        QTabBar::tab:hover:!selected {{
            background: {p['hover_grad']}; color: {p['text']};
        }}
    """
