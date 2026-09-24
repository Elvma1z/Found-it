"""Reusable "Helpful Info" toggle: an (i) button every tab places in its own
top-right corner, plus small contextual tips that only take up layout space
once it's switched on - so the UI stays exactly as it is today when it's off.
"""

from PyQt5.QtWidgets import QLabel, QPushButton
from found_it.gui.icons import get_icon, ICON_SIZE


class HelpLabel(QLabel):
    """A small contextual tip. Hidden (and taking no layout space) until the
    tab's Helpful Info toggle is switched on."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setObjectName("helpLabel")
        self.hide()

    def apply_theme(self, p):
        self.setStyleSheet(f"""
            QLabel#helpLabel {{
                color: {p['text_dim']};
                background: {p['panel']};
                border: 1px solid {p['glow_line']};
                border-left: 3px solid {p['accent']};
                border-radius: 4px;
                padding: 6px 10px;
                font-size: 11px;
            }}
        """)


class InfoToggleButton(QPushButton):
    """Small round (i) button. Meant to sit in a tab's top-right corner and
    toggle that tab's HelpLabels on/off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setIconSize(ICON_SIZE)
        self.setFixedSize(28, 28)
        self.setObjectName("infoToggleBtn")

    def apply_theme(self, p):
        color = p["accent"] if self.isChecked() else p["text_faint"]
        self.setIcon(get_icon("info", color))
        self.setToolTip("Hide helpful info" if self.isChecked() else "Show helpful info")
        self.setStyleSheet(f"""
            QPushButton#infoToggleBtn {{
                background: transparent; border: none; border-radius: 14px;
            }}
            QPushButton#infoToggleBtn:hover {{ background: {p['hover_grad']}; }}
            QPushButton#infoToggleBtn:checked {{ background: {p['selected_grad']}; }}
        """)


class HelpInfoMixin:
    """Mix into a QWidget-based panel to give it a toggleable set of
    contextual HelpLabels plus the corner button that drives them.

    Usage:
        self._init_help_info()                       # once, in __init__
        self.info_btn = self._make_info_toggle()      # place it in a header layout
        self._add_help(some_widget, "Tip text.")      # after building each section
        ...
        self.apply_theme(p) should call self._apply_help_theme(p)
    """

    def _init_help_info(self):
        self._help_labels = []
        self._help_visible = False

    def _make_info_toggle(self):
        btn = InfoToggleButton(self)
        btn.toggled.connect(self.set_help_visible)
        self._info_toggle_btn = btn
        return btn

    def _add_help(self, after_widget, text, layout=None):
        """Insert a HelpLabel directly after `after_widget` in its layout (or
        `layout`, if the widget isn't in one yet) so the tip lands next to the
        control it explains."""
        label = HelpLabel(text, self)
        target_layout = layout
        if target_layout is None and after_widget is not None:
            target_layout = after_widget.parentWidget().layout()
        if target_layout is not None and after_widget is not None:
            index = target_layout.indexOf(after_widget)
            if index != -1:
                target_layout.insertWidget(index + 1, label)
            else:
                target_layout.addWidget(label)
        elif target_layout is not None:
            target_layout.addWidget(label)
        label.setVisible(self._help_visible)
        self._help_labels.append(label)
        return label

    def set_help_visible(self, visible):
        self._help_visible = visible
        for label in self._help_labels:
            label.setVisible(visible)
        if hasattr(self, "_info_toggle_btn"):
            self._info_toggle_btn.setChecked(visible)
            if hasattr(self, "palette"):
                self._info_toggle_btn.apply_theme(self.palette)

    def _apply_help_theme(self, p):
        if hasattr(self, "_info_toggle_btn"):
            self._info_toggle_btn.apply_theme(p)
        for label in self._help_labels:
            label.apply_theme(p)
