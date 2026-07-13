from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from typing import List

from found_it.config import CAMERA_LABELS


class SearchPanel(QWidget):
    item_selected = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self.setMaximumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Find It")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        layout.addWidget(title)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Where are my keys?")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a3e;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #6c63ff;
            }
        """)
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.search_btn = QPushButton("Search")
        self.search_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c63ff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5a52d5; }
        """)
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #333;")
        layout.addWidget(separator)

        self.results_label = QLabel("All detected items")
        self.results_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.results_label)

        self.results_list = QListWidget()
        self.results_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a2e;
                color: #e0e0e0;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2a2a3e;
            }
            QListWidget::item:selected {
                background-color: #3a3a5e;
            }
            QListWidget::item:hover {
                background-color: #2a2a4e;
            }
        """)
        self.results_list.itemClicked.connect(self._on_item_click)
        layout.addWidget(self.results_list)

        details_label = QLabel("Details")
        details_label.setStyleSheet("color: #888; font-size: 11px; margin-top: 4px;")
        layout.addWidget(details_label)

        self.detail_label = QLabel("Select an item for details")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("""
            QLabel {
                background-color: #1a1a2e;
                color: #ccc;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 10px;
                font-size: 12px;
            }
        """)
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
            zone_name = item.get("zone_name")
            last_seen = item.get("last_seen", "")[:16]

            text = f"{label}  ({cam_label}, {conf:.0%})"
            if zone_name:
                text += f"\n  In: {zone_name}"
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
        zone_name = item.get("zone_name") or "unmarked area"
        zx = item.get("zone_x", 0)
        zy = item.get("zone_y", 0)
        first = item.get("first_seen", "")[:16]
        last = item.get("last_seen", "")[:16]

        details = (
            f"Item: {label}\n"
            f"Confidence: {conf:.1%}\n"
            f"In: {zone_name}\n"
            f"Camera: {cam_label}\n"
            f"Position: ({zx:.2f}, {zy:.2f})\n"
            f"First seen: {first}\n"
            f"Last seen: {last}"
        )
        self.detail_label.setText(details)

    def show_all_items(self, items: List[dict]):
        self._show_results(items, "All detected items")
