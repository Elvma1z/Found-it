"""components/navigation/CommandPalette - Ctrl+K search across room items,
saved devices and actions, drawn over a scrim that covers the window."""

from typing import Callable, List, Optional

from PyQt5.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from found_it.gui import ds
from found_it.gui.icons import get_pixmap


class PaletteEntry:
    def __init__(self, group: str, title: str, subtitle: str = "", icon: str = "search",
                 run: Optional[Callable] = None, color: Optional[str] = None):
        self.group, self.title, self.subtitle, self.icon, self.run, self.color = (
            group, title, subtitle, icon, run, color)


_ENTRY = Qt.UserRole + 7


class _Delegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        entry = index.data(_ENTRY)
        return QSize(option.rect.width(), 44 if entry is not None else 30)

    def paint(self, painter: QPainter, option, index):
        p = ds.pal()
        entry: Optional[PaletteEntry] = index.data(_ENTRY)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect)
        if entry is None:
            painter.setPen(QColor(p["text3"]))
            f = ds.font(11, 600)
            f.setLetterSpacing(f.PercentageSpacing, 106)
            painter.setFont(f)
            painter.drawText(r.adjusted(10, 8, -10, 0), Qt.AlignLeft | Qt.AlignVCenter,
                             index.data(Qt.DisplayRole).upper())
            painter.restore()
            return
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(p["surface3"]))
            painter.drawRoundedRect(r, 8, 8)
        tile = QRectF(r.left() + 10, r.center().y() - 14, 28, 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ds.mix(entry.color, 0.16) if entry.color else QColor(p["surface2"]))
        painter.drawRoundedRect(tile, 7, 7)
        painter.drawPixmap(QPointF(tile.left() + 6.5, tile.top() + 6.5),
                           get_pixmap(entry.icon, entry.color or p["text2"], 15))
        x = tile.right() + 12
        right = r.right() - (34 if selected else 10)
        painter.setFont(ds.font(13.5))
        fm = painter.fontMetrics()
        title_w = min(fm.horizontalAdvance(entry.title), int(right - x))
        painter.setPen(QColor(p["text"]))
        painter.drawText(QRectF(x, r.top(), title_w, r.height()), Qt.AlignVCenter,
                         fm.elidedText(entry.title, Qt.ElideRight, title_w))
        if entry.subtitle and x + title_w + 10 < right:
            painter.setFont(ds.font(12.5))
            painter.setPen(QColor(p["text3"]))
            sx = x + title_w + 10
            painter.drawText(QRectF(sx, r.top(), right - sx, r.height()), Qt.AlignVCenter,
                             painter.fontMetrics().elidedText(entry.subtitle, Qt.ElideRight, int(right - sx)))
        if selected:
            painter.drawPixmap(QPointF(r.right() - 24, r.center().y() - 7),
                               get_pixmap("corner-down-left", p["text3"], 14))
        painter.restore()


class CommandPalette(QWidget):
    """An overlay child of the main window (not a separate dialog), so the
    scrim dims the app behind it exactly like the kit."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.hide()
        self._entries: List[PaletteEntry] = []
        parent.installEventFilter(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("paletteCard")
        self.card.setFixedWidth(640)
        self.card.setAttribute(Qt.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(64)
        shadow.setOffset(0, 24)
        shadow.setColor(QColor(0, 0, 0, 128))
        self.card.setGraphicsEffect(shadow)
        row.addWidget(self.card)
        row.addStretch(1)
        self._top = QWidget()
        outer.addWidget(self._top)
        outer.addLayout(row)
        outer.addStretch(1)

        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget()
        head.setObjectName("paletteHead")
        head.setFixedHeight(56)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 0, 18, 0)
        hl.setSpacing(12)
        hl.addWidget(ds.IconLabel("search", "text3", 18))
        self.input = ds.TextInput("Search items, files, devices, or type a command…")
        self.input.setProperty("bare", "true")
        self.input.setStyleSheet("font-size: 16px;")
        self.input.textChanged.connect(self._refill)
        self.input.installEventFilter(self)
        hl.addWidget(self.input, 1)
        hl.addWidget(ds.Kbd("Esc"))
        lay.addWidget(head)

        self.list = QListWidget()
        self.list.setItemDelegate(_Delegate(self.list))
        self.list.setProperty("cls", "rows")
        self.list.setMaximumHeight(380)
        self.list.setMinimumHeight(120)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setMouseTracking(True)
        self.list.itemClicked.connect(self._run_item)
        self.list.itemEntered.connect(lambda it: self.list.setCurrentItem(it) if it.data(_ENTRY) else None)
        self.list.setContentsMargins(8, 8, 8, 8)
        self.list.setViewportMargins(8, 8, 8, 8)
        lay.addWidget(self.list)
        self.empty = ds.text("", "caption")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setContentsMargins(0, 28, 0, 28)
        self.empty.setStyleSheet("font-size: 13.5px;")
        lay.addWidget(self.empty)

        foot = QWidget()
        foot.setObjectName("paletteFoot")
        foot.setFixedHeight(38)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(18, 0, 18, 0)
        fl.setSpacing(6)
        fl.addWidget(ds.Kbd("↑"))
        fl.addWidget(ds.Kbd("↓"))
        fl.addWidget(ds.text("Navigate", "caption"))
        fl.addSpacing(10)
        fl.addWidget(ds.Kbd("↵"))
        fl.addWidget(ds.text("Open", "caption"))
        fl.addStretch(1)
        lay.addWidget(foot)

        ds.on_theme(self, self._style)

    def _style(self, p):
        self.card.setStyleSheet(f"""
            QFrame#paletteCard {{ background: {p['pop']}; border: 1px solid {p['border_strong']}; border-radius: 16px; }}
            QWidget#paletteHead {{ border-bottom: 1px solid {p['border']}; }}
            QWidget#paletteFoot {{ border-top: 1px solid {p['border']}; }}
        """)
        self.update()

    def apply_theme(self, _p=None):
        pass

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(ds.pal()["scrim"]))
        painter.end()

    def open_with(self, entries: List[PaletteEntry]):
        self._entries = entries
        parent = self.parentWidget()
        self.setGeometry(parent.rect())
        self._top.setFixedHeight(int(parent.height() * 0.12))
        self.input.clear()
        self._refill("")
        self.show()
        self.raise_()
        self.input.setFocus()

    def close_palette(self):
        self.hide()
        if self.parentWidget() is not None:
            self.parentWidget().setFocus()

    def _refill(self, query: str):
        q = query.strip().lower()
        self.list.clear()
        group = None
        count = 0
        for entry in self._entries:
            if q and q not in f"{entry.title} {entry.subtitle}".lower():
                continue
            if entry.group != group:
                group = entry.group
                header = QListWidgetItem(group)
                header.setFlags(Qt.NoItemFlags)
                self.list.addItem(header)
            item = QListWidgetItem(entry.title)
            item.setData(_ENTRY, entry)
            self.list.addItem(item)
            count += 1
        rows = sum(self.list.sizeHintForRow(i) for i in range(self.list.count()))
        self.list.setFixedHeight(min(rows + 18, 380))
        self.empty.setText(f'No matches for "{query}"')
        self.empty.setVisible(count == 0)
        self.list.setVisible(count > 0)
        for i in range(self.list.count()):
            if self.list.item(i).data(_ENTRY) is not None:
                self.list.setCurrentRow(i)
                break

    def _step(self, delta: int):
        row = self.list.currentRow()
        while 0 <= row + delta < self.list.count():
            row += delta
            if self.list.item(row).data(_ENTRY) is not None:
                self.list.setCurrentRow(row)
                return

    def _run_item(self, item: QListWidgetItem):
        entry = item.data(_ENTRY)
        if entry is None:
            return
        self.close_palette()
        if entry.run is not None:
            entry.run()

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.pos()):
            self.close_palette()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(obj.rect())
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Down:
                self._step(1)
                return True
            if key == Qt.Key_Up:
                self._step(-1)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                current = self.list.currentItem()
                if current is not None:
                    self._run_item(current)
                return True
            if key == Qt.Key_Escape:
                self.close_palette()
                return True
        return super().eventFilter(obj, event)
