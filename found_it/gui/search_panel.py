from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from typing import List

from found_it.config import CAMERA_LABELS
from found_it.utils.themes import get_palette, widget_qss, repolish


class SearchPanel(QWidget):
    item_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(400)
        self._room_names: dict = {}
        self.palette = get_palette("Indigo")
        self._setup_ui()
        self.apply_theme(self.palette)

    def set_room_names(self, room_names: dict):
        """room_id -> room name, so results can show which tracked room an item was found in."""
        self._room_names = room_names

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        repolish(self)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Find It")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Where are my keys?")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.setProperty("cls", "primary")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setProperty("cls", "sep")
        layout.addWidget(separator)

        self.results_label = QLabel("All detected items")
        self.results_label.setProperty("cls", "muted")
        layout.addWidget(self.results_label)

        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self._on_item_click)
        layout.addWidget(self.results_list)

        details_label = QLabel("Details")
        details_label.setProperty("cls", "muted")
        layout.addWidget(details_label)

        self.detail_label = QLabel("Select an item for details")
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("cls", "muted")
        layout.addWidget(self.detail_label)

        layout.addStretch()

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        from found_it.storage.database import Database
        db = Database()
        results = db.find_items(query)
        db.close()

        self._show_results(results, f"Results for \"{query}\"")

    def _on_item_click(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data:
            self._show_details(data)
            self.item_selected.emit(data)

    def _show_results(self, items: List[dict], header: str = "Results"):
        self.results_list.clear()
        self.results_label.setText(f"{header} ({len(items)})")

        for item in items:
            label = item.get("label", "unknown")
            conf = item.get("confidence", 0)
            cam = item.get("camera_id", 0)
            cam_label = CAMERA_LABELS.get(cam, f"cam{cam}")
            room_name = self._room_names.get(item.get("room_id"), item.get("room_id"))
            zone_name = item.get("zone_name")
            last_seen = item.get("last_seen", "")[:16]

            text = f"{label}  ({cam_label}, {conf:.0%})"
            if zone_name:
                text += f"\n  {zone_name[0].upper()}{zone_name[1:]}"
            if room_name:
                text += f"\n  Room: {room_name}"
            if last_seen:
                text += f"\n  Last seen: {last_seen}"

            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, item)
            self.results_list.addItem(list_item)

    def _show_details(self, item: dict):
        label = item.get("label", "unknown")
        conf = item.get("confidence", 0)
        cam = item.get("camera_id", 0)
        cam_label = CAMERA_LABELS.get(cam, f"cam{cam}")
        room_name = self._room_names.get(item.get("room_id"), item.get("room_id") or "unknown room")
        zone_name = item.get("zone_name") or "in an unmarked area"
        zx = item.get("zone_x", 0)
        zy = item.get("zone_y", 0)
        first = item.get("first_seen", "")[:16]
        last = item.get("last_seen", "")[:16]

        location = f"{zone_name[0].upper()}{zone_name[1:]}"

        details = (
            f"<b style='font-size: 13pt'>{label}: {location}</b><br>"
            f"Room: {room_name}<br>"
            f"Confidence: {conf:.1%}<br>"
            f"Camera: {cam_label}<br>"
            f"Position: ({zx:.2f}, {zy:.2f})<br>"
            f"First seen: {first}<br>"
            f"Last seen: {last}"
        )
        self.detail_label.setTextFormat(Qt.RichText)
        self.detail_label.setText(details)

    def show_all_items(self, items: List[dict]):
        self._show_results(items, "All detected items")
