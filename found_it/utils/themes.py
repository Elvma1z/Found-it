import colorsys

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


def _palette_for_hue(hue):
    return {
        "bg": _hex(hue, 0.22, 0.075),
        "header": _hex(hue, 0.26, 0.055),
        "panel": _hex(hue, 0.28, 0.13),
        "selected": _hex(hue, 0.30, 0.19),
        "hover": _hex(hue, 0.32, 0.26),
        "border": _hex(hue, 0.15, 0.16),
        "accent": _hex(hue, 0.75, 0.62),
        "accent_hover": _hex(hue, 0.75, 0.70),
        "text": "#e0e0e0",
        "text_dim": "#aaaaaa",
        "text_faint": "#777777",
    }


def _white_palette():
    return {
        "bg": "#f4f4f6",
        "header": "#ffffff",
        "panel": "#e9e9ec",
        "selected": "#dcdce2",
        "hover": "#cfcfd6",
        "border": "#c7c7cf",
        "accent": "#5b53e0",
        "accent_hover": "#443cc9",
        "text": "#1a1a1f",
        "text_dim": "#55555c",
        "text_faint": "#8a8a91",
    }


def _dark_palette():
    return {
        "bg": "#1a1a1d",
        "header": "#121214",
        "panel": "#232326",
        "selected": "#2d2d31",
        "hover": "#39393e",
        "border": "#303034",
        "accent": "#6c6cf0",
        "accent_hover": "#8080f5",
        "text": "#e8e8ea",
        "text_dim": "#a5a5ac",
        "text_faint": "#707078",
    }


THEMES = {name: _palette_for_hue(hue) for name, hue in RAINBOW_HUES}
THEMES["White"] = _white_palette()
THEMES["Dark"] = _dark_palette()


def get_palette(theme_name: str) -> dict:
    return THEMES.get(theme_name, THEMES["Indigo"])


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
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
            border: 1px solid {p['accent']};
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
        QListWidget::item:selected {{ background-color: {p['selected']}; }}
        QListWidget::item:hover {{ background-color: {p['hover']}; }}
        QScrollArea {{ background-color: transparent; border: none; }}
        QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
        QScrollBar:vertical {{
            background-color: {p['bg']}; width: 12px; margin: 0; border-radius: 6px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {p['border']}; min-height: 24px; border-radius: 6px;
        }}
        QScrollBar::handle:vertical:hover {{ background-color: {p['hover']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        QPushButton[cls="primary"] {{
            background-color: {p['accent']}; color: white; border: none;
            border-radius: 4px; padding: 8px 16px; font-weight: bold;
        }}
        QPushButton[cls="primary"]:hover {{ background-color: {p['accent_hover']}; }}
        QPushButton[cls="primary"]:disabled {{ background-color: {p['border']}; color: {p['text_faint']}; }}
        QPushButton[cls="secondary"] {{
            background-color: {p['panel']}; color: {p['text_dim']};
            border: 1px solid {p['border']}; border-radius: 4px; padding: 6px 14px; font-size: 12px;
        }}
        QPushButton[cls="secondary"]:hover {{ background-color: {p['hover']}; color: {p['text']}; }}
        QPushButton[cls="secondary"]:checked {{ background-color: {p['accent']}; color: white; }}
        QPushButton[cls="secondary"]:disabled {{ color: {p['text_faint']}; }}
        QProgressBar {{
            background-color: {p['bg']}; border: 1px solid {p['border']};
            border-radius: 4px; text-align: center; color: {p['text_dim']};
            max-height: 20px;
        }}
        QProgressBar::chunk {{ background-color: {p['accent']}; border-radius: 3px; }}
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
            background-color: {p['bg']}; color: {p['text']};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {p['hover']}; color: {p['text']};
        }}
    """
