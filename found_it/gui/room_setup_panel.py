from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QDoubleSpinBox, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush
from typing import List, Optional, Tuple

from found_it.utils.room_config import load_room_config, save_room_config
from found_it.storage.database import Database

INPUT_STYLE = """
    QLineEdit, QDoubleSpinBox {
        background-color: #2a2a3e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 4px;
        padding: 6px;
        font-size: 12px;
    }
    QLineEdit:focus, QDoubleSpinBox:focus { border: 1px solid #6c63ff; }
"""

BUTTON_STYLE = """
    QPushButton {
        background-color: #6c63ff;
        color: white; border: none;
        border-radius: 4px; padding: 6px 14px;
        font-weight: bold; font-size: 12px;
    }
    QPushButton:hover { background-color: #5a52d5; }
    QPushButton:disabled { background-color: #3a3a4e; color: #777; }
"""

SECONDARY_BUTTON_STYLE = """
    QPushButton {
        background-color: #2a2a3e;
        color: #ccc; border: 1px solid #444;
        border-radius: 4px; padding: 6px 14px;
        font-size: 12px;
    }
    QPushButton:hover { background-color: #35354e; }
    QPushButton:checked { background-color: #6c63ff; color: white; }
"""

LIST_STYLE = """
    QListWidget {
        background-color: #1a1a2e;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 4px;
    }
    QListWidget::item { padding: 6px; border-bottom: 1px solid #2a2a3e; }
    QListWidget::item:selected { background-color: #3a3a5e; }
    QListWidget::item:hover { background-color: #2a2a4e; }
"""


class RoomCanvas(QWidget):
    """Interactive canvas for laying out a room: drag to draw a named zone."""

    zone_drawn = pyqtSignal(float, float, float, float)
    zone_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.room_width = 4.0
        self.room_height = 4.0
        self.zones: List[dict] = []
        self.draw_mode = False
        self.selected_index: Optional[int] = None
        self._drag_start: Optional[Tuple[float, float]] = None
        self._drag_current: Optional[Tuple[float, float]] = None
        self._padding = 30

    def set_room_size(self, width: float, height: float):
        self.room_width = max(width, 0.1)
        self.room_height = max(height, 0.1)
        self.update()

    def set_zones(self, zones: List[dict]):
        self.zones = zones
        self.selected_index = None
        self.update()

    def set_draw_mode(self, enabled: bool):
        self.draw_mode = enabled
        self._drag_start = None
        self._drag_current = None
        self.update()

    def _draw_rect(self):
        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        return draw_w, draw_h

    def _px_to_m(self, px: int, py: int) -> Tuple[float, float]:
        draw_w, draw_h = self._draw_rect()
        x = (px - self._padding) / draw_w * self.room_width if draw_w else 0
        y = (py - self._padding) / draw_h * self.room_height if draw_h else 0
        x = max(0.0, min(self.room_width, x))
        y = max(0.0, min(self.room_height, y))
        return x, y

    def _m_to_px(self, x: float, y: float) -> Tuple[int, int]:
        draw_w, draw_h = self._draw_rect()
        px = self._padding + int(x / self.room_width * draw_w)
        py = self._padding + int(y / self.room_height * draw_h)
        return px, py

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.draw_mode:
            self._drag_start = self._px_to_m(event.x(), event.y())
            self._drag_current = self._drag_start
            self.update()
        else:
            mx, my = self._px_to_m(event.x(), event.y())
            for i, z in enumerate(self.zones):
                if z["x1"] <= mx <= z["x2"] and z["y1"] <= my <= z["y2"]:
                    self.selected_index = i
                    self.zone_selected.emit(i)
                    self.update()
                    return
            self.selected_index = None
            self.update()

    def mouseMoveEvent(self, event):
        if self.draw_mode and self._drag_start is not None:
            self._drag_current = self._px_to_m(event.x(), event.y())
            self.update()

    def mouseReleaseEvent(self, event):
        if self.draw_mode and self._drag_start is not None and event.button() == Qt.LeftButton:
            end = self._px_to_m(event.x(), event.y())
            x1, x2 = sorted((self._drag_start[0], end[0]))
            y1, y2 = sorted((self._drag_start[1], end[1]))
            self._drag_start = None
            self._drag_current = None
            self.update()
            if x2 - x1 >= 0.1 and y2 - y1 >= 0.1:
                self.zone_drawn.emit(x1, y1, x2, y2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        draw_w, draw_h = self._draw_rect()

        painter.setPen(QPen(QColor(60, 60, 80), 2))
        painter.setBrush(QBrush(QColor(20, 20, 35)))
        painter.drawRoundedRect(self._padding, self._padding, draw_w, draw_h, 6, 6)

        painter.setPen(QPen(QColor(80, 80, 100), 1, Qt.DashLine))
        for i in range(1, 4):
            x = self._padding + int(draw_w * i / 4)
            painter.drawLine(x, self._padding, x, self._padding + draw_h)
            y = self._padding + int(draw_h * i / 4)
            painter.drawLine(self._padding, y, self._padding + draw_w, y)

        for i, zone in enumerate(self.zones):
            x1, y1 = self._m_to_px(zone["x1"], zone["y1"])
            x2, y2 = self._m_to_px(zone["x2"], zone["y2"])
            selected = i == self.selected_index
            color = QColor(255, 210, 90) if selected else QColor(108, 99, 255)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)
            painter.setPen(QPen(QColor(230, 230, 230), 1))
            font = QFont("Segoe UI", 8, QFont.Bold)
            painter.setFont(font)
            painter.drawText(x1 + 4, y1 + 14, zone.get("name", "Zone"))

        if self.draw_mode and self._drag_start and self._drag_current:
            x1, y1 = self._m_to_px(*self._drag_start)
            x2, y2 = self._m_to_px(*self._drag_current)
            painter.setPen(QPen(QColor(100, 255, 180), 2, Qt.DashLine))
            painter.setBrush(QBrush(QColor(100, 255, 180, 40)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

        painter.end()


class RoomSetupPanel(QWidget):
    """Lets the user size their room, lay out named zones/furniture, and rename detected objects."""

    room_updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.room_config = load_room_config()
        self.zones: List[dict] = [dict(z) for z in self.room_config.zones]
        self._setup_ui()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_object_list()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("Room Setup")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        outer.addWidget(title)

        desc = QLabel("Set your bedroom's size, sketch out zones like the bed or desk, and rename detected objects.")
        desc.setStyleSheet("color: #888; font-size: 11px;")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        splitter = QSplitter(Qt.Horizontal)

        # --- Left: dimensions + canvas ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 4, 4, 4)

        dims_row = QHBoxLayout()
        dims_row.addWidget(self._label("Width (m)"))
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(1.0, 30.0)
        self.width_input.setSingleStep(0.1)
        self.width_input.setStyleSheet(INPUT_STYLE)
        self.width_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.width_input)

        dims_row.addWidget(self._label("Height (m)"))
        self.height_input = QDoubleSpinBox()
        self.height_input.setRange(1.0, 30.0)
        self.height_input.setSingleStep(0.1)
        self.height_input.setStyleSheet(INPUT_STYLE)
        self.height_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.height_input)
        dims_row.addStretch()
        left_layout.addLayout(dims_row)

        self.canvas = RoomCanvas()
        self.canvas.zone_drawn.connect(self._on_zone_drawn)
        self.canvas.zone_selected.connect(self._on_zone_selected_in_canvas)
        left_layout.addWidget(self.canvas)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c63ff; font-size: 11px;")
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left)

        # --- Right: zone list + object rename ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 0, 4)

        right_layout.addWidget(self._label("Zones / Furniture"))

        add_row = QHBoxLayout()
        self.zone_name_input = QLineEdit()
        self.zone_name_input.setPlaceholderText("e.g. Bed, Desk, Closet")
        self.zone_name_input.setStyleSheet(INPUT_STYLE)
        add_row.addWidget(self.zone_name_input)

        self.draw_zone_btn = QPushButton("Draw Zone")
        self.draw_zone_btn.setCheckable(True)
        self.draw_zone_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.draw_zone_btn.clicked.connect(self._on_draw_zone_clicked)
        add_row.addWidget(self.draw_zone_btn)
        right_layout.addLayout(add_row)

        self.zone_list = QListWidget()
        self.zone_list.setStyleSheet(LIST_STYLE)
        self.zone_list.itemClicked.connect(self._on_zone_list_clicked)
        right_layout.addWidget(self.zone_list)

        rename_row = QHBoxLayout()
        self.zone_rename_input = QLineEdit()
        self.zone_rename_input.setPlaceholderText("Rename selected zone")
        self.zone_rename_input.setStyleSheet(INPUT_STYLE)
        rename_row.addWidget(self.zone_rename_input)

        self.rename_zone_btn = QPushButton("Rename")
        self.rename_zone_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_zone_btn.clicked.connect(self._on_rename_zone)
        rename_row.addWidget(self.rename_zone_btn)

        self.delete_zone_btn = QPushButton("Delete")
        self.delete_zone_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.delete_zone_btn.clicked.connect(self._on_delete_zone)
        rename_row.addWidget(self.delete_zone_btn)
        right_layout.addLayout(rename_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #333;")
        right_layout.addWidget(separator)

        right_layout.addWidget(self._label("Detected Objects"))

        self.object_list = QListWidget()
        self.object_list.setStyleSheet(LIST_STYLE)
        self.object_list.itemClicked.connect(self._on_object_list_clicked)
        right_layout.addWidget(self.object_list)

        object_row = QHBoxLayout()
        self.object_rename_input = QLineEdit()
        self.object_rename_input.setPlaceholderText("Rename selected object")
        self.object_rename_input.setStyleSheet(INPUT_STYLE)
        object_row.addWidget(self.object_rename_input)

        self.rename_object_btn = QPushButton("Rename")
        self.rename_object_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_object_btn.clicked.connect(self._on_rename_object)
        object_row.addWidget(self.rename_object_btn)

        self.refresh_objects_btn = QPushButton("Refresh")
        self.refresh_objects_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.refresh_objects_btn.clicked.connect(self._refresh_object_list)
        object_row.addWidget(self.refresh_objects_btn)
        right_layout.addLayout(object_row)

        self.save_btn = QPushButton("Save Room")
        self.save_btn.setStyleSheet(BUTTON_STYLE)
        self.save_btn.clicked.connect(self._on_save)
        right_layout.addWidget(self.save_btn)

        splitter.addWidget(right)
        splitter.setSizes([550, 400])
        outer.addWidget(splitter)

        self._selected_zone_index: Optional[int] = None
        self._selected_object_id: Optional[int] = None

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        return lbl

    def _load_from_config(self):
        self.width_input.blockSignals(True)
        self.height_input.blockSignals(True)
        self.width_input.setValue(self.room_config.width_m)
        self.height_input.setValue(self.room_config.height_m)
        self.width_input.blockSignals(False)
        self.height_input.blockSignals(False)
        self.canvas.set_room_size(self.room_config.width_m, self.room_config.height_m)
        self.canvas.set_zones(self.zones)

    def _on_size_changed(self):
        self.canvas.set_room_size(self.width_input.value(), self.height_input.value())

    def _on_draw_zone_clicked(self, checked: bool):
        if checked and not self.zone_name_input.text().strip():
            self.status_label.setText("Enter a zone name first (e.g. Bed).")
            self.draw_zone_btn.setChecked(False)
            return
        self.canvas.set_draw_mode(checked)
        if checked:
            self.status_label.setText(f"Drag on the room to place \"{self.zone_name_input.text().strip()}\".")
        else:
            self.status_label.setText("")

    def _on_zone_drawn(self, x1: float, y1: float, x2: float, y2: float):
        name = self.zone_name_input.text().strip() or f"Zone {len(self.zones) + 1}"
        self.zones.append({"name": name, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self.zone_name_input.clear()
        self.draw_zone_btn.setChecked(False)
        self.canvas.set_draw_mode(False)
        self.status_label.setText(f"Added zone \"{name}\". Don't forget to Save Room.")

    def _refresh_zone_list(self):
        self.zone_list.clear()
        for i, zone in enumerate(self.zones):
            text = (f"{zone['name']}  "
                    f"({zone['x1']:.1f},{zone['y1']:.1f}) -> ({zone['x2']:.1f},{zone['y2']:.1f})")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, i)
            self.zone_list.addItem(item)

    def _on_zone_list_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        self._selected_zone_index = index
        self.canvas.selected_index = index
        self.canvas.update()
        self.zone_rename_input.setText(self.zones[index]["name"])

    def _on_zone_selected_in_canvas(self, index: int):
        self._selected_zone_index = index
        self.zone_list.setCurrentRow(index)
        self.zone_rename_input.setText(self.zones[index]["name"])

    def _on_rename_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to rename first.")
            return
        new_name = self.zone_rename_input.text().strip()
        if not new_name:
            return
        self.zones[self._selected_zone_index]["name"] = new_name
        self.canvas.set_zones(self.zones)
        self.canvas.selected_index = self._selected_zone_index
        self._refresh_zone_list()
        self.zone_list.setCurrentRow(self._selected_zone_index)
        self.status_label.setText(f"Renamed zone to \"{new_name}\". Don't forget to Save Room.")

    def _on_delete_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to delete first.")
            return
        removed = self.zones.pop(self._selected_zone_index)
        self._selected_zone_index = None
        self.zone_rename_input.clear()
        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self.status_label.setText(f"Deleted zone \"{removed['name']}\". Don't forget to Save Room.")

    def _on_save(self):
        self.room_config.width_m = self.width_input.value()
        self.room_config.height_m = self.height_input.value()
        self.room_config.zones = self.zones
        save_room_config(self.room_config)
        self.status_label.setText("Room saved.")
        self.room_updated.emit()

    def _refresh_object_list(self):
        db = Database()
        items = db.get_recent_items(100)
        db.close()

        self.object_list.clear()
        for item in items:
            label = item.get("label", "unknown")
            cam = item.get("camera_id", 0)
            last_seen = (item.get("last_seen") or "")[:16]
            text = f"{label}  (cam {cam})"
            if last_seen:
                text += f"  - {last_seen}"
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, item)
            self.object_list.addItem(list_item)

    def _on_object_list_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        self._selected_object_id = data.get("id")
        self.object_rename_input.setText(data.get("label", ""))

    def _on_rename_object(self):
        if self._selected_object_id is None:
            self.status_label.setText("Select an object to rename first.")
            return
        new_label = self.object_rename_input.text().strip()
        if not new_label:
            return
        db = Database()
        db.rename_item(self._selected_object_id, new_label)
        db.close()
        self._refresh_object_list()
        self.status_label.setText(f"Renamed object to \"{new_label}\".")
