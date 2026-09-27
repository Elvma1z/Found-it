"""Found It design system (v2) for Qt.

Tokens mirror the design system's `tokens/*.css`: a cool near-black (or soft
grey-blue) window with two faint accent glows, translucent "glass" surfaces
layered on top, hairline borders and ONE accent at a time. Translucent colors
are `#AARRGGBB` strings - Qt's stylesheet parser and QColor both read that
form, so the same token works in QSS and in QPainter code.

`app_qss(p)` is the single application-wide stylesheet. Widgets opt into the
design's variants with the dynamic `cls` property (buttons: primary /
secondary / ghost / success / danger; labels: h1 / h2 / h3 / secondary /
small / caption / eyebrow / mono / status ...).
"""

from PyQt5.QtCore import QPointF, QRectF
from PyQt5.QtGui import QBrush, QColor, QRadialGradient
from PyQt5.QtWidgets import QWidget


def repolish(widget: QWidget):
    """Force Qt to re-evaluate `[cls="..."]` selectors on a widget and all its
    descendants - needed after changing a `cls` property at runtime."""
    for w in [widget] + widget.findChildren(QWidget):
        style = w.style()
        style.unpolish(w)
        style.polish(w)


FONT = "Segoe UI"
FONT_DISPLAY = "Segoe UI"
FONT_MONO = "Cascadia Mono"
QSS_FONT = f'"{FONT}", "Open Sans", sans-serif'
QSS_FONT_DISPLAY = f'"{FONT_DISPLAY}", "Open Sans", sans-serif'
QSS_FONT_MONO = f'"{FONT_MONO}", "Cascadia Code", Consolas, monospace'

# tokens/colors.css - dark (default) and light modes
_DARK = {
    "bg": "#0a0c11", "overlay": (255, 255, 255),
    "surface1": ((22, 26, 35), 0.62), "pop": ((18, 21, 29), 0.86), "solid": "#12151c",
    "s2": 0.045, "s3": 0.085, "s4": 0.12, "border": 0.075, "border_strong": 0.14,
    "text": "#e8ebf1", "text2": "#a1a8b6", "text3": "#6b7383",
    "success": "#22c55e", "warning": "#f59e0b", "danger": "#ef4444",
    "scrim": ((3, 5, 9), 0.55), "glow1": 0.16,
}
_LIGHT = {
    "bg": "#eef1f6", "overlay": (15, 23, 42),
    "surface1": ((255, 255, 255), 0.68), "pop": ((255, 255, 255), 0.9), "solid": "#ffffff",
    "s2": 0.04, "s3": 0.07, "s4": 0.10, "border": 0.085, "border_strong": 0.16,
    "text": "#0f172a", "text2": "#475569", "text3": "#8591a3",
    "success": "#16a34a", "warning": "#d97706", "danger": "#dc2626",
    "scrim": ((15, 23, 42), 0.25), "glow1": 0.14,
}
# accent, hover, accent-text, on-accent, glow-2 (rgb, alpha) - per mode
ACCENTS = {
    "Blue": (("#3b82f6", "#60a5fa", "#93c5fd", "#ffffff", ((6, 182, 212), 0.08)),
             ("#2563eb", "#1d4ed8", "#1d4ed8", "#ffffff", ((6, 182, 212), 0.10))),
    "Cyan": (("#06b6d4", "#22d3ee", "#67e8f9", "#03151a", ((59, 130, 246), 0.07)),
             ("#0891b2", "#0e7490", "#0e7490", "#ffffff", ((59, 130, 246), 0.10))),
    "Emerald": (("#10b981", "#34d399", "#6ee7b7", "#03170f", ((6, 182, 212), 0.07)),
                ("#059669", "#047857", "#047857", "#ffffff", ((6, 182, 212), 0.10))),
    "Slate": (("#94a3b8", "#cbd5e1", "#cbd5e1", "#0b1220", ((100, 116, 139), 0.06)),
              ("#475569", "#334155", "#334155", "#ffffff", ((100, 116, 139), 0.08))),
}
ACCENT_NAMES = list(ACCENTS)
DEFAULT_THEME = "Blue"
THEME_NAMES = ACCENT_NAMES + [f"Light {n}" for n in ACCENT_NAMES]

# room map pin colors (tokens/colors.css) - fixed across themes
PIN_COLORS = {0: "#f87171", 1: "#60a5fa", 2: "#34d399"}
PIN_FALLBACK = ["#fbbf24", "#a78bfa", "#f472b6", "#22d3ee"]
PIN_SELECTED = "#facc15"
DRAWER_LINE = "#fbbf24"

# file-type colors for result-row icon tiles
FILE_TYPE_COLORS = {"image": "#a78bfa", "text": "#60a5fa", "code": "#34d399"}

# Names saved by earlier versions (nine hue themes) map onto the nearest new one.
_LEGACY_THEMES = {
    "Dark": "Blue", "White": "Light Blue", "Indigo": "Blue", "Violet": "Blue",
    "Red": "Blue", "Orange": "Blue", "Yellow": "Blue", "Green": "Emerald",
}


def pin_color(cam_id: int) -> str:
    if cam_id in PIN_COLORS:
        return PIN_COLORS[cam_id]
    return PIN_FALLBACK[cam_id % len(PIN_FALLBACK)]


def _rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def argb(color, alpha: float) -> str:
    """`color` (hex or rgb tuple) at `alpha` (0-1), as a #AARRGGBB token."""
    r, g, b = _rgb(color) if isinstance(color, str) else color
    return "#{:02x}{:02x}{:02x}{:02x}".format(round(alpha * 255), round(r), round(g), round(b))


def _hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(round(c) for c in rgb))


def _blend(base, over, alpha):
    return tuple(b + (o - b) * alpha for b, o in zip(base, over))


def theme_parts(theme_name: str):
    """("Light Cyan") -> (True, "Cyan")."""
    name = normalize_theme(theme_name)
    if name.startswith("Light "):
        return True, name[len("Light "):]
    return False, name


def theme_name(light: bool, accent: str) -> str:
    return f"Light {accent}" if light else accent


def normalize_theme(theme_name: str) -> str:
    if theme_name in THEMES:
        return theme_name
    return _LEGACY_THEMES.get(theme_name, DEFAULT_THEME)


def _build_palette(mode: dict, accent_name: str, light: bool) -> dict:
    a, a_hover, a_text, on_a, (g2_rgb, g2_a) = ACCENTS[accent_name][1 if light else 0]
    bg = _rgb(mode["bg"])
    ov = mode["overlay"]
    s1_rgb, s1_a = mode["surface1"]
    panel_solid = _blend(bg, s1_rgb, s1_a)
    pop_solid = _blend(bg, mode["pop"][0], mode["pop"][1])
    p = {
        "name": theme_name(light, accent_name), "accent_name": accent_name, "is_light": light,
        "bg": mode["bg"],
        "glow1": argb(a, mode["glow1"] if accent_name != "Slate" else 0.10),
        "glow2": argb(g2_rgb, g2_a),
        "surface1": argb(s1_rgb, s1_a),
        "surface2": argb(ov, mode["s2"]),
        "surface3": argb(ov, mode["s3"]),
        "surface4": argb(ov, mode["s4"]),
        "pop": _hex(pop_solid),
        "solid": mode["solid"],
        "border": argb(ov, mode["border"]),
        "border_strong": argb(ov, mode["border_strong"]),
        "text": mode["text"], "text2": mode["text2"], "text3": mode["text3"],
        "accent": a, "accent_hover": a_hover, "accent_text": a_text, "on_accent": on_a,
        "accent_soft": argb(a, 0.12 if light else 0.16),
        "accent_ring": argb(a, 0.45),
        "success": mode["success"], "success_soft": argb(mode["success"], 0.14),
        "warning": mode["warning"], "warning_soft": argb(mode["warning"], 0.14),
        "danger": mode["danger"], "danger_soft": argb(mode["danger"], 0.14),
        "on_success": "#04130a",
        "scrim": argb(*mode["scrim"]),
        # Opaque equivalents, for top-level popups (menus, dropdowns,
        # tooltips) which Qt can't composite over the window behind them.
        "panel_solid": _hex(panel_solid),
        "surface3_solid": _hex(_blend(pop_solid, ov, mode["s3"])),
        "border_solid": _hex(_blend(panel_solid, ov, mode["border"])),
    }
    # Aliases kept for older call sites (painters, dialogs).
    p.update({
        "text_dim": p["text2"], "text_faint": p["text3"],
        "panel": p["panel_solid"], "header": p["pop"],
        "selected": p["surface3_solid"], "hover": p["border_strong"],
        "selected_grad": p["accent_soft"], "hover_grad": p["surface3"],
        "accent_grad": a, "accent_grad_hover": a_hover,
        "accent2": a, "accent2_hover": a_hover,
        "glow": p["accent_ring"], "glow_line": p["border"],
        "header_grad": p["surface1"], "panel_grad": p["surface1"],
        "bg_glow": p["glow1"], "bg_deep": mode["bg"], "bg_grad": mode["bg"],
    })
    return p


THEMES = {}
for _name in ACCENT_NAMES:
    THEMES[_name] = _build_palette(_DARK, _name, False)
    THEMES[f"Light {_name}"] = _build_palette(_LIGHT, _name, True)


def get_palette(theme: str) -> dict:
    return THEMES[normalize_theme(theme)]


def aura_brush(p: dict, rect) -> QBrush:
    """The window's accent glow, for painted canvases."""
    r = QRectF(rect)
    grad = QRadialGradient(QPointF(r.left() + r.width() * 0.12, r.top() - r.height() * 0.1),
                           max(r.width(), r.height()) * 0.7)
    grad.setColorAt(0, QColor(p["glow1"]))
    grad.setColorAt(1, QColor(0, 0, 0, 0))
    return QBrush(grad)


def widget_qss(p: dict) -> str:
    """Kept for existing callers - everything now lives in the single
    application stylesheet (`app_qss`), so per-widget sheets are empty."""
    return ""


def glass_qss(p: dict) -> str:
    return ""


def app_qss(p: dict) -> str:
    """The whole design system as one application stylesheet."""
    return f"""
    * {{ font-family: {QSS_FONT}; font-size: 13.5px; color: {p['text']}; }}
    QWidget {{ background: transparent; }}
    QMainWindow {{ background: transparent; }}
    QDialog {{ background: {p['pop']}; }}
    QToolTip {{
        background: {p['pop']}; color: {p['text']}; border: 1px solid {p['border_solid']};
        border-radius: 6px; padding: 5px 8px; font-size: 12.5px;
    }}

    /* ---------- text roles (components/core/Text) ---------- */
    QLabel {{ color: {p['text']}; }}
    QLabel[cls="display"] {{ font-family: {QSS_FONT_DISPLAY}; font-size: 32px; font-weight: 700; }}
    QLabel[cls="h1"] {{ font-family: {QSS_FONT_DISPLAY}; font-size: 24px; font-weight: 600; }}
    QLabel[cls="h2"] {{ font-family: {QSS_FONT_DISPLAY}; font-size: 18px; font-weight: 600; }}
    QLabel[cls="h3"] {{ font-size: 15px; font-weight: 600; }}
    QLabel[cls="secondary"] {{ color: {p['text2']}; }}
    QLabel[cls="small"] {{ color: {p['text2']}; font-size: 12.5px; }}
    QLabel[cls="caption"] {{ color: {p['text3']}; font-size: 11.5px; }}
    QLabel[cls="eyebrow"] {{ color: {p['text3']}; font-size: 11px; font-weight: 600; }}
    QLabel[cls="mono"] {{ font-family: {QSS_FONT_MONO}; font-size: 12px; color: {p['text3']}; }}
    QLabel[cls="status"] {{ color: {p['accent_text']}; font-size: 12.5px; }}
    QLabel[cls="panelTitle"] {{ font-weight: 600; }}
    /* legacy roles */
    QLabel[cls="title"] {{ font-family: {QSS_FONT_DISPLAY}; font-weight: 600; }}
    QLabel[cls="muted"] {{ color: {p['text2']}; font-size: 12.5px; }}
    QLabel[cls="hint"] {{ color: {p['text3']}; font-size: 11.5px; }}
    QFrame[cls="sep"] {{ color: {p['border']}; background: {p['border']}; border: none; max-height: 1px; min-height: 1px; }}
    QFrame[cls="vsep"] {{ background: {p['border']}; border: none; max-width: 1px; min-width: 1px; }}

    /* ---------- surfaces (components/layout/Panel) ---------- */
    QFrame#glassPanel {{
        background: {p['surface1']}; border: 1px solid {p['border']}; border-radius: 12px;
    }}
    QWidget#panelHeader {{ background: transparent; border: none; border-bottom: 1px solid {p['border']}; }}
    QFrame[cls="card"] {{
        background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px;
    }}
    QWidget#titleBar {{ background: {p['surface1']}; border-bottom: 1px solid {p['border']}; }}
    QWidget#statusStrip {{ background: {p['surface1']}; border-top: 1px solid {p['border']}; }}
    QLabel#statusText, QLabel#statusRight {{ color: {p['text3']}; font-size: 11.5px; }}

    /* ---------- buttons (components/core/Button) ---------- */
    QPushButton {{
        min-height: 32px; padding: 0 14px; border-radius: 8px;
        border: 1px solid {p['border']}; background: {p['surface2']}; color: {p['text']};
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {p['surface3']}; }}
    QPushButton:disabled {{ color: {p['text3']}; background: {p['surface2']}; }}
    QPushButton[cls="primary"], QPushButton[cls="secondary"], QPushButton[cls="ghost"], QPushButton[cls="muted"],
    QPushButton[cls="success"], QPushButton[cls="danger"], QPushButton[cls="destructive"] {{ max-height: 32px; }}
    QPushButton[size="sm"] {{ min-height: 26px; max-height: 26px; padding: 0 10px; font-size: 12.5px; }}
    QPushButton[size="lg"] {{ min-height: 40px; max-height: 40px; padding: 0 18px; font-size: 14px; }}
    QPushButton[cls="primary"] {{
        background: {p['accent']}; color: {p['on_accent']}; border: 1px solid {p['accent']}; font-weight: 600;
    }}
    QPushButton[cls="primary"]:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
    QPushButton[cls="primary"]:disabled {{ background: {p['surface3']}; border-color: transparent; color: {p['text3']}; }}
    QPushButton[cls="secondary"]:checked {{ background: {p['accent_soft']}; color: {p['accent_text']}; border-color: {p['accent']}; }}
    QPushButton[cls="ghost"], QPushButton[cls="muted"] {{ background: transparent; border-color: transparent; color: {p['text2']}; }}
    QPushButton[cls="ghost"]:hover, QPushButton[cls="muted"]:hover {{ background: {p['surface2']}; color: {p['text']}; }}
    QPushButton[cls="ghost"]:checked, QPushButton[cls="muted"]:checked {{ background: {p['surface3']}; color: {p['text']}; }}
    QPushButton[cls="ghost"]:disabled, QPushButton[cls="muted"]:disabled {{ background: transparent; color: {p['text3']}; }}
    QPushButton[cls="success"] {{ background: {p['success_soft']}; color: {p['success']}; border-color: transparent; }}
    QPushButton[cls="success"]:hover {{ background: {p['success']}; color: {p['on_success']}; }}
    QPushButton[cls="success"]:disabled {{ background: {p['surface2']}; color: {p['text3']}; }}
    QPushButton[cls="danger"], QPushButton[cls="destructive"] {{ background: {p['danger_soft']}; color: {p['danger']}; border-color: transparent; }}
    QPushButton[cls="danger"]:hover, QPushButton[cls="destructive"]:hover,
    QPushButton[cls="danger"]:checked, QPushButton[cls="destructive"]:checked {{ background: {p['danger']}; color: #ffffff; }}
    QPushButton[cls="danger"]:disabled, QPushButton[cls="destructive"]:disabled {{ background: {p['surface2']}; color: {p['text3']}; }}

    /* IconButton */
    QPushButton[cls="iconbtn"] {{ min-height: 0px; padding: 0; border: 1px solid transparent; background: transparent; }}
    QPushButton[cls="iconbtn"]:hover {{ background: {p['surface3']}; }}
    QPushButton[cls="iconbtn"]:checked {{ background: {p['accent_soft']}; }}
    QPushButton[cls="iconbtn"][variant="solid"] {{ background: {p['surface2']}; border-color: {p['border']}; }}
    QPushButton[cls="iconbtn"][variant="solid"]:hover {{ background: {p['surface3']}; }}
    QPushButton[cls="iconbtn"][danger="true"]:hover {{ background: {p['danger']}; }}
    QPushButton[cls="iconbtn"]:disabled {{ background: transparent; }}

    /* title bar: NavTab, search trigger, window controls */
    QPushButton[cls="navtab"] {{
        min-height: 34px; max-height: 34px; padding: 0 12px; border: none; border-radius: 8px;
        background: transparent; color: {p['text2']}; font-weight: 500;
    }}
    QPushButton[cls="navtab"]:hover {{ background: {p['surface2']}; color: {p['text']}; }}
    QPushButton[cls="navtab"]:checked {{ background: {p['surface3']}; color: {p['text']}; font-weight: 600; }}
    QPushButton#searchTrigger {{
        min-height: 30px; max-height: 30px; padding: 0 6px 0 32px; text-align: left;
        border: 1px solid {p['border']}; background: {p['surface2']}; color: {p['text3']}; font-weight: 400;
    }}
    QPushButton#searchTrigger:hover {{ border-color: {p['border_strong']}; background: {p['surface2']}; }}
    QPushButton[cls="winbtn"] {{ min-height: 52px; max-height: 52px; padding: 0; border: none; border-radius: 0; background: transparent; }}
    QPushButton[cls="winbtn"]:hover {{ background: {p['surface2']}; }}
    QPushButton[cls="winbtn"][close="true"]:hover {{ background: {p['danger']}; }}

    /* segmented Tabs (components/navigation/Tabs) */
    QFrame[cls="segmented"] {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; }}
    QPushButton[cls="seg"] {{
        min-height: 26px; max-height: 26px; padding: 0 12px; border: none; border-radius: 6px;
        background: transparent; color: {p['text2']}; font-size: 12.5px; font-weight: 500;
    }}
    QPushButton[cls="seg"]:hover {{ color: {p['text']}; background: transparent; }}
    QPushButton[cls="seg"]:checked {{ background: {p['surface4']}; color: {p['text']}; font-weight: 600; }}

    /* CollapsibleSection header */
    QPushButton[cls="sectionHeader"] {{
        min-height: 44px; max-height: 44px; padding: 0 4px; border: none; border-radius: 0;
        background: transparent; text-align: left; font-weight: 600;
    }}
    QPushButton[cls="sectionHeader"]:hover {{ background: transparent; }}
    QFrame[cls="section"] {{ background: transparent; border: none; border-bottom: 1px solid {p['border']}; }}
    QFrame[cls="section"][last="true"] {{ border-bottom: none; }}

    /* ThemeSwatch */
    QPushButton[cls="swatch"] {{ min-height: 104px; padding: 0; border: none; background: transparent; border-radius: 12px; }}

    /* ---------- form controls (components/forms) ---------- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']};
        border-radius: 8px; padding: 0 10px; min-height: 32px;
        selection-background-color: {p['accent_soft']}; selection-color: {p['text']};
    }}
    QPlainTextEdit, QTextEdit {{ padding: 6px 8px; }}
    QLineEdit[size="sm"], QSpinBox[size="sm"], QDoubleSpinBox[size="sm"], QComboBox[size="sm"] {{ min-height: 26px; max-height: 26px; font-size: 13px; }}
    QLineEdit[size="lg"] {{ min-height: 40px; max-height: 40px; font-size: 15px; }}
    QLineEdit[icon="true"] {{ padding-left: 32px; }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {p['border_strong']}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p['accent']}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {p['text3']}; }}
    QLineEdit[bare="true"] {{ background: transparent; border: none; padding: 0; min-height: 0; }}
    QSpinBox, QDoubleSpinBox {{ padding: 0 6px 0 10px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
        width: 18px; border: none; background: transparent; subcontrol-origin: border;
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; margin-right: 3px; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; margin-right: 3px; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {p['surface3']}; border-radius: 4px; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url(__CHEVRON_UP__); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url(__CHEVRON_DOWN__); width: 10px; height: 10px; }}
    QComboBox {{ padding-right: 28px; }}
    QComboBox::drop-down {{ border: none; width: 26px; subcontrol-position: center right; }}
    QComboBox::down-arrow {{ image: url(__CHEVRONS__); width: 14px; height: 14px; }}
    QComboBox QAbstractItemView {{
        background: {p['pop']}; border: 1px solid {p['border_solid']}; border-radius: 8px;
        padding: 4px; outline: none; color: {p['text']};
        selection-background-color: {p['surface3_solid']}; selection-color: {p['text']};
    }}
    QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 8px; border-radius: 6px; }}
    QComboBox QAbstractItemView::item:hover {{ background: {p['surface3_solid']}; }}

    QCheckBox {{ spacing: 10px; color: {p['text']}; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {p['border_strong']}; background: {p['surface2']}; }}
    QCheckBox::indicator:hover {{ border-color: {p['text3']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url(__CHECK__); }}
    QRadioButton {{ spacing: 8px; }}

    QProgressBar {{ background: {p['surface3']}; border: none; border-radius: 2px; max-height: 4px; min-height: 4px; color: transparent; }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 2px; }}

    /* ---------- lists (ListBox, ListItem, SettingsNav) ---------- */
    QListView, QListWidget, QTreeView, QTableView {{
        background: transparent; border: none; outline: none; color: {p['text']};
    }}
    QListWidget::item {{ min-height: 38px; padding: 0 10px; border-radius: 8px; margin: 1px 0; }}
    QListWidget::item:hover {{ background: {p['surface2']}; }}
    QListWidget::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
    QListWidget[cls="nav"]::item {{ min-height: 36px; color: {p['text2']}; }}
    QListWidget[cls="nav"]::item:selected {{ background: {p['surface3']}; color: {p['text']}; font-weight: 600; }}
    QListWidget[cls="rows"]::item, QListWidget[cls="rows"]::item:selected, QListWidget[cls="rows"]::item:hover {{ background: transparent; padding: 0; margin: 0; min-height: 0; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {p['surface3']}; border-radius: 3px; min-height: 28px; margin: 2px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['surface4']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {p['surface3']}; border-radius: 3px; min-width: 28px; margin: 2px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QSplitter::handle {{ background: transparent; }}
    QMainWindow::separator {{ background: transparent; width: 12px; height: 12px; }}
    QDockWidget {{ border: none; }}

    QTabWidget::pane {{ border: none; background: transparent; top: 0; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: transparent; color: {p['text2']}; border: none; border-radius: 6px;
        padding: 5px 12px; margin: 3px 2px; font-size: 12.5px; font-weight: 500;
    }}
    QTabBar::tab:selected {{ background: {p['surface4']}; color: {p['text']}; font-weight: 600; }}
    QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

    QMenuBar {{ background: transparent; }}
    QMenu {{ background: {p['pop']}; border: 1px solid {p['border_solid']}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 7px 14px; border-radius: 6px; color: {p['text']}; }}
    QMenu::item:selected {{ background: {p['surface3_solid']}; }}
    QMenu::separator {{ height: 1px; background: {p['border_solid']}; margin: 4px 6px; }}

    QMessageBox, QInputDialog, QFileDialog {{ background: {p['pop']}; }}
    QMessageBox QLabel, QInputDialog QLabel {{ color: {p['text']}; }}
    QGraphicsView {{ background: transparent; border: none; }}
    """
