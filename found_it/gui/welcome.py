"""First-run tutorial and the per-update "What's New" splash.

Both are the same themed, frameless card so an update notice and the
walkthrough feel like one thing rather than two unrelated dialogs. What they
show comes from found_it/version.py (release notes) and TUTORIAL_STEPS below,
so neither needs GUI changes to stay current.

The tutorial drives the main window as it goes: each step names the tab it is
talking about, and the window switches to it behind the card, so the user is
reading about the screen they can actually see rather than a description of
one they still have to go find.
"""

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QStackedWidget, QApplication, QGraphicsDropShadowEffect, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QFont, QColor, QPainter, QBrush

from found_it.utils.themes import widget_qss, repolish
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.version import APP_VERSION, releases_since


# Each step: the tab the main window should switch to while the step is on
# screen ("" leaves the window alone), a title, a lead paragraph, and
# bullets. Bullets are rich text - <b> marks the exact control to look for.
TUTORIAL_STEPS = [
    {
        "mode": "",
        "title": "Welcome to Found It",
        "lead": "Found It watches your room through the cameras you connect, remembers where "
                "it last saw your things, and searches this PC for photos and files you can't "
                "find. Everything it learns stays on this machine - nothing is uploaded anywhere.",
        "bullets": [
            "<b>Room Tracker</b> - live camera feeds, a map of your room, and everything found so far.",
            "<b>Room Setup</b> - draw your room, its furniture, and where each camera sits.",
            "<b>Cameras</b> - add cameras and tune what detection looks for.",
            "<b>File Search</b> - scan this PC for missing pictures and files.",
            "<b>Other Devices</b> - search a phone plugged in over USB.",
            "<b>The gear, top right</b> - themes, fonts, your data, and the layout of the app itself.",
        ],
        "note": "This takes about a minute. You can reopen it any time from Settings → Help.",
    },
    {
        "mode": "room_setup",
        "title": "Build your room",
        "lead": "Open the Room Setup tab. Everything the tracker knows about where your things "
                "are comes from the layout you draw here.",
        "bullets": [
            "Pick or create a room with <b>New Room</b> - <b>Rename</b> and <b>Delete</b> sit next "
            "to it. Every saved room keeps its own cameras and keeps tracking in the background.",
            "Set <b>Width (ft)</b> and <b>Depth (ft)</b> to the real size of the room. The floor "
            "plan underneath redraws to match.",
            "Type a name in the box (\"Bed\", \"Desk\", \"Closet\"), press <b>Draw Zone</b>, then "
            "drag a rectangle on the floor plan where that piece actually stands.",
            "Drag a zone to move it, drag its top-left handle to resize it, press <b>Delete</b> to "
            "remove it, or <b>Ctrl+R</b> to rotate it 90°.",
            "Press <b>Save Room</b> when you're done - nothing is stored until you do.",
        ],
        "note": "",
    },
    {
        "mode": "room_setup",
        "title": "Give each piece a height",
        "lead": "Furniture needs a real-world height before the room can be stood up in 3D.",
        "bullets": [
            "Select a piece in <b>Zones / Furniture</b>, then set its <b>Type</b> and <b>Height (in)</b>.",
            "Rough guide: a bed is about 24 in, a desk 30 in, a dresser 32 in, a wardrobe 78 in.",
            "<b>Set Drawers</b> splits a dresser or desk into drawer-level spots, so \"in the top "
            "drawer\" becomes an answer the tracker can give you.",
            "Press <b>3D View</b> to stand the room up. If anything is still missing a height, the "
            "app names the pieces instead of just refusing.",
        ],
        "note": "",
    },
    {
        "mode": "cameras",
        "title": "Add your cameras",
        "lead": "The Cameras tab is where cameras get added and configured.",
        "bullets": [
            "Press <b>Add Camera</b>. The app scans for cameras attached to this PC and drops you "
            "straight into the new camera's own settings screen.",
            "Give it a <b>Label</b> and set its <b>Type</b>: a normal lens, a 180° camera (which "
            "only sees the half of the room it faces - set <b>Facing</b> too), or a 360° camera "
            "(which sees the whole room from wherever it sits).",
            "<b>Enabled</b> turns a camera off without losing its settings; <b>Remove Camera</b> "
            "takes it out for good.",
            "Press <b>Save Cameras</b>, then go back to <b>Room Setup</b> and drag the camera's "
            "marker to where it physically sits in the room. Save the room again.",
            "With cameras placed and enabled, <b>Scan Room with Cameras</b> in Room Setup creates "
            "zones for the furniture it recognizes - a fast start you can then correct by hand.",
        ],
        "note": "",
    },
    {
        "mode": "room",
        "title": "Watch the room",
        "lead": "Room Tracker is the day-to-day view: what the cameras see, and what they've found.",
        "bullets": [
            "<b>Cameras</b> on the left shows every live feed. Tick <b>Dewarp</b> to flatten a "
            "fisheye or 360° image into something you can read.",
            "The <b>Room Map</b> in the middle plots each detected item onto the layout you drew.",
            "<b>Found Items</b> on the right lists everything seen, newest first, and can be "
            "searched by name.",
            "Click an item and it stays highlighted - on the map and in the live feeds - as you "
            "switch between cameras.",
            "The room button above the feeds switches which room you're watching. The others keep "
            "tracking in the background.",
        ],
        "note": "",
    },
    {
        "mode": "file",
        "title": "Find missing pictures on this PC",
        "lead": "File Search reads the pictures and documents on this computer so you can find one "
                "by describing it, instead of remembering where you filed it.",
        "bullets": [
            "Leave <b>Scan entire PC (recommended)</b> ticked and press <b>Scan</b>. It walks every "
            "drive and skips system folders like Windows, Program Files, and AppData. To narrow it, "
            "untick the box and use <b>Add Folder</b>.",
            "The first scan takes a while - it reads every image once. <b>Cancel</b> stops it, and "
            "whatever was already indexed is kept.",
            "Then just describe what you want: \"vacation photo with mountains\", or a person's name.",
            "<b>Search by Image</b> takes a picture you already have and finds visually similar ones.",
            "<b>Add Image</b> names one specific picture (\"Passport\") so you can find it by that "
            "name from then on.",
            "The <b>People</b> tab groups faces found during the scan - name someone once and every "
            "photo of them becomes searchable.",
            "Select a result to preview it, then <b>Open File</b> or <b>Open Folder</b>.",
        ],
        "note": "",
    },
    {
        "mode": "device",
        "title": "Search a phone over USB",
        "lead": "Other Devices does the same thing for a phone plugged into this PC.",
        "bullets": [
            "Plug the device in with a USB cable, accept the prompt on the phone, then press "
            "<b>Connect</b>.",
            "<b>Scan Device</b> indexes its pictures. Search them the way you search this PC.",
            "Save a device under Settings → Saved Devices to reconnect it in one click next time.",
        ],
        "note": "",
    },
    {
        "mode": "settings",
        "title": "Make it yours",
        "lead": "The gear icon at the top right holds everything else.",
        "bullets": [
            "<b>Appearance</b> - any font installed on this machine, and one of nine themes. The "
            "whole app follows it, startup splash included.",
            "<b>Data &amp; Security</b> - everything is stored only on this machine. Clear detection "
            "history or snapshots, and export/import your rooms to move them to another PC.",
            "<b>Customization</b> - reorder the top-bar tabs and the panels against a live preview, "
            "and bind the \"Found It\" title in the corner to any button as a one-click shortcut.",
            "<b>Help</b> - reopen this tutorial, or the notes for the latest update.",
        ],
        "note": "",
    },
    {
        "mode": "",
        "title": "You're all set",
        "lead": "The quickest path from here:",
        "bullets": [
            "Draw your room in <b>Room Setup</b> and save it.",
            "Add your cameras in <b>Cameras</b>, then place their markers back in Room Setup.",
            "Start a <b>Scan</b> in File Search and leave it running in the background.",
            "Watch things get found in <b>Room Tracker</b>.",
        ],
        "note": "Settings → Help brings this tutorial back whenever you want it.",
    },
]


def pending_startup(settings) -> tuple:
    """What (if anything) to show on launch: ("tutorial"|"whats_new"|"", releases).

    An install that has never been launched gets the walkthrough. One that has
    run before gets the notes for every release it missed - skipping updates
    is normal, so this is deliberately not just the newest release.
    """
    if not settings.last_seen_version and not settings.tutorial_completed:
        return ("tutorial", [])
    releases = releases_since(settings.last_seen_version)
    if releases:
        return ("whats_new", releases)
    return ("", [])


class _WrapLabel(QLabel):
    """A word-wrapped label pinned to a known width, reporting the height it
    will actually need at that width.

    QLabel's own hint for wrapped text is a guess made at a width it picks
    itself - for these paragraphs it comes out roughly twice the real height,
    which inside a scroll area leaves a scrollbar hanging beside content that
    fits perfectly well. Pinning the width (these cards are fixed-size, so it
    is known up front) makes heightForWidth exact, and keeps the hint from
    chasing the label's own size - a hint derived from the current width
    ratchets: wider label, wider page, wider label, until the text runs off
    the card or the height spirals.
    """

    def __init__(self, text: str, width: int, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._wrap_width = max(1, width)
        self.setFixedWidth(self._wrap_width)
        policy = QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _hint(self) -> QSize:
        return QSize(self._wrap_width, self.heightForWidth(self._wrap_width))

    def sizeHint(self) -> QSize:
        return self._hint()

    def minimumSizeHint(self) -> QSize:
        return self._hint()


class _DialogHeader(QWidget):
    """Title strip that doubles as the drag handle, since these dialogs are
    frameless to match the app's own custom window chrome."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)


class _StepDots(QWidget):
    """The row of dots under the tutorial: how many steps there are, and which
    one you're on, without having to read a counter."""

    DOT = 8
    GAP = 7

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self._count = count
        self._index = 0
        self._on = QColor("#6c6cf0")
        self._off = QColor("#3a3a40")
        self.setFixedHeight(self.DOT + 4)
        self.setFixedWidth(count * self.DOT + (count - 1) * self.GAP)

    def set_colors(self, on: str, off: str):
        self._on = QColor(on)
        self._off = QColor(off)
        self.update()

    def set_index(self, index: int):
        self._index = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        y = (self.height() - self.DOT) / 2
        for i in range(self._count):
            painter.setBrush(QBrush(self._on if i == self._index else self._off))
            painter.drawEllipse(int(i * (self.DOT + self.GAP)), int(y), self.DOT, self.DOT)
        painter.end()


class _CardDialog(QDialog):
    """Shared shell: a frameless, themed, rounded card with a title strip, a
    scrolling body, and a button row - so the tutorial and the release notes
    read as the same object rather than two unrelated dialogs."""

    def __init__(self, palette: dict, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.palette = palette
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        self.card = QFrame()
        self.card.setObjectName("welcome_card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self.header = _DialogHeader()
        self.header.setObjectName("dialog_header")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(24, 16, 12, 14)
        header_layout.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 17, QFont.Bold))
        title_box.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setVisible(bool(subtitle))
        title_box.addWidget(self.subtitle_label)
        header_layout.addLayout(title_box, 1)

        self.close_btn = QPushButton()
        self.close_btn.setIconSize(ICON_SIZE)
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self.accept)
        header_layout.addWidget(self.close_btn, 0, Qt.AlignTop)

        card_layout.addWidget(self.header)

        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        card_layout.addWidget(self.body_scroll, 1)

        self.footer = QWidget()
        self.footer.setObjectName("dialog_footer")
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(24, 12, 24, 18)
        self.footer_layout.setSpacing(8)
        card_layout.addWidget(self.footer)

    # ---------------- shared content helpers ----------------

    # Card width minus the outer margin, the body's own left/right margins,
    # and room for a scrollbar: the width wrapped text really gets.
    _BODY_INSET = 18 * 2 + 24 * 2 + 16
    _BULLET_INDENT = 20  # dot column + its spacing

    def _text_width(self, indent: int = 0) -> int:
        """Only valid once the subclass has set the card's fixed size, which
        every one of them does before building its body."""
        return max(160, self.width() - self._BODY_INSET - indent)

    def _bullet_row(self, text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        dot = QLabel("•")
        dot.setProperty("cls", "bullet")
        dot.setFixedWidth(10)
        layout.addWidget(dot, 0, Qt.AlignTop)

        label = _WrapLabel(text, self._text_width(self._BULLET_INDENT))
        label.setTextFormat(Qt.RichText)
        label.setProperty("cls", "body")
        layout.addWidget(label, 1)
        return row

    def _apply_card_theme(self):
        p = self.palette
        self.card.setStyleSheet(widget_qss(p) + f"""
            QFrame#welcome_card {{
                background: {p['bg']};
                border: 1px solid {p['border']};
                border-radius: 10px;
            }}
            QLabel {{ background: transparent; color: {p['text']}; }}
            QLabel[cls="body"] {{ color: {p['text']}; font-size: 12px; }}
            QLabel[cls="lead"] {{ color: {p['text_dim']}; font-size: 13px; }}
            QLabel[cls="bullet"] {{ color: {p['accent']}; font-size: 13px; }}
            QLabel[cls="section"] {{ color: {p['accent']}; font-size: 11px; font-weight: bold; }}
            QLabel[cls="note"] {{ color: {p['text_faint']}; font-size: 11px; }}
            QLabel[cls="counter"] {{ color: {p['text_faint']}; font-size: 11px; }}
            QWidget#body_host {{ background: transparent; }}
        """)
        # Selector-scoped on purpose: a bare "background: ...; border-bottom:
        # ..." here would cascade into every child, underlining each label in
        # the strip and flattening the footer's primary button.
        self.header.setStyleSheet(f"""
            QWidget#dialog_header {{
                background: {p['header']};
                border-top-left-radius: 10px; border-top-right-radius: 10px;
                border-bottom: 1px solid {p['border']};
            }}
        """)
        self.title_label.setStyleSheet(f"color: {p['text']}; background: transparent;")
        self.subtitle_label.setStyleSheet(
            f"color: {p['text_dim']}; font-size: 12px; background: transparent;"
        )
        self.close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background-color: {p['selected']}; }}
        """)
        self.close_btn.setIcon(get_icon("x", p["text_faint"]))
        self.footer.setStyleSheet(f"""
            QWidget#dialog_footer {{
                background: {p['header']};
                border-top: 1px solid {p['border']};
                border-bottom-left-radius: 10px; border-bottom-right-radius: 10px;
            }}
        """)
        repolish(self)

    def center_on(self, parent: QWidget):
        if parent is not None and parent.isVisible():
            geo = parent.frameGeometry()
        else:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            geo = screen.availableGeometry()
        self.move(
            geo.center().x() - self.width() // 2,
            geo.center().y() - self.height() // 2,
        )


class WhatsNewDialog(_CardDialog):
    """The release notes, shown once after an update."""

    tutorial_requested = pyqtSignal()

    def __init__(self, palette: dict, releases: list, parent=None):
        headline = releases[0]["version"] if releases else APP_VERSION
        subtitle = f"Found It {headline}"
        if len(releases) > 1:
            subtitle += "  ·  including the updates you skipped"
        super().__init__(palette, "What's New", subtitle, parent)
        self.setFixedSize(660, 560)

        host = QWidget()
        host.setObjectName("body_host")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(6)

        if not releases:
            empty = _WrapLabel("You're on the latest version - nothing new to report.",
                               self._text_width())
            empty.setProperty("cls", "lead")
            layout.addWidget(empty)

        for index, release in enumerate(releases):
            if index > 0:
                layout.addSpacing(10)
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setProperty("cls", "sep")
                layout.addWidget(sep)
                layout.addSpacing(6)

            version_label = QLabel(f"Version {release['version']}")
            version_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
            layout.addWidget(version_label)

            if release.get("date"):
                date_label = QLabel(release["date"])
                date_label.setProperty("cls", "note")
                layout.addWidget(date_label)

            for heading, key in (("NEW", "added"), ("CHANGED", "changed")):
                entries = release.get(key) or []
                if not entries:
                    continue
                layout.addSpacing(10)
                section = QLabel(heading)
                section.setProperty("cls", "section")
                layout.addWidget(section)
                layout.addSpacing(2)
                for entry in entries:
                    layout.addWidget(self._bullet_row(entry))

        layout.addStretch()
        self.body_scroll.setWidget(host)

        self.tutorial_btn = QPushButton("Show me around")
        self.tutorial_btn.setProperty("cls", "secondary")
        self.tutorial_btn.setToolTip("Walk through the whole app step by step")
        self.tutorial_btn.clicked.connect(self._on_tutorial)
        self.footer_layout.addWidget(self.tutorial_btn)
        self.footer_layout.addStretch()

        self.ok_btn = QPushButton("Got it")
        self.ok_btn.setProperty("cls", "primary")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        self.footer_layout.addWidget(self.ok_btn)

        self._apply_card_theme()

    def _on_tutorial(self):
        self.accept()
        # Deferred a tick so this dialog's own modal loop has finished
        # unwinding before the tutorial opens its own, rather than nesting
        # one inside the other's teardown.
        QTimer.singleShot(0, self.tutorial_requested.emit)


class TutorialDialog(_CardDialog):
    """The walkthrough. Emits mode_requested so the window behind it follows
    along with whichever tab the current step is about."""

    mode_requested = pyqtSignal(str)

    def __init__(self, palette: dict, parent=None):
        super().__init__(palette, "Getting started", "A quick tour of Found It", parent)
        self.setFixedSize(680, 580)
        self._steps = TUTORIAL_STEPS

        self.pages = QStackedWidget()
        for step in self._steps:
            page = self._build_step(step)
            # A QStackedWidget normally reports the tallest page's height as
            # its own, which would leave a scrollbar showing on every short
            # step. Ignored on the hidden pages makes it report only the one
            # actually on screen; _go_to hands the policy to the new page.
            page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
            self.pages.addWidget(page)
        self.body_scroll.setWidget(self.pages)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setProperty("cls", "muted")
        self.skip_btn.clicked.connect(self.accept)
        self.footer_layout.addWidget(self.skip_btn)

        self.dots = _StepDots(len(self._steps))
        self.footer_layout.addSpacing(6)
        self.footer_layout.addWidget(self.dots)

        self.counter_label = QLabel("")
        self.counter_label.setProperty("cls", "counter")
        self.footer_layout.addSpacing(8)
        self.footer_layout.addWidget(self.counter_label)

        self.footer_layout.addStretch()

        self.back_btn = QPushButton("Back")
        self.back_btn.setProperty("cls", "secondary")
        self.back_btn.clicked.connect(self._on_back)
        self.footer_layout.addWidget(self.back_btn)

        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("cls", "primary")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._on_next)
        self.footer_layout.addWidget(self.next_btn)

        self._apply_card_theme()
        self.dots.set_colors(palette["accent"], palette["border"])
        self._go_to(0)

    def _build_step(self, step: dict) -> QWidget:
        page = QWidget()
        page.setObjectName("body_host")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(8)

        heading = _WrapLabel(step["title"], self._text_width())
        heading.setFont(QFont("Segoe UI", 15, QFont.Bold))
        layout.addWidget(heading)

        lead = _WrapLabel(step["lead"], self._text_width())
        lead.setProperty("cls", "lead")
        layout.addWidget(lead)

        layout.addSpacing(6)
        for bullet in step["bullets"]:
            layout.addWidget(self._bullet_row(bullet))

        if step.get("note"):
            layout.addSpacing(10)
            note = _WrapLabel(step["note"], self._text_width())
            note.setProperty("cls", "note")
            layout.addWidget(note)

        layout.addStretch()
        return page

    def _go_to(self, index: int):
        index = max(0, min(index, len(self._steps) - 1))
        leaving = self.pages.currentWidget()
        if leaving is not None:
            leaving.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.pages.setCurrentIndex(index)
        arriving = self.pages.currentWidget()
        if arriving is not None:
            arriving.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
            arriving.adjustSize()
        self.dots.set_index(index)
        self.counter_label.setText(f"Step {index + 1} of {len(self._steps)}")
        self.back_btn.setEnabled(index > 0)
        last = index == len(self._steps) - 1
        self.next_btn.setText("Finish" if last else "Next")
        self.skip_btn.setVisible(not last)
        self.body_scroll.verticalScrollBar().setValue(0)

        mode = self._steps[index].get("mode")
        if mode:
            self.mode_requested.emit(mode)

    def _on_back(self):
        self._go_to(self.pages.currentIndex() - 1)

    def _on_next(self):
        if self.pages.currentIndex() >= len(self._steps) - 1:
            self.accept()
            return
        self._go_to(self.pages.currentIndex() + 1)

    def keyPressEvent(self, event):
        # Left/right page the tour. Escape is left to QDialog, which closes
        # it - the same as Skip, and the caller records it either way.
        if event.key() in (Qt.Key_Right, Qt.Key_PageDown):
            self._on_next()
            return
        if event.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self._on_back()
            return
        super().keyPressEvent(event)
