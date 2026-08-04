import os
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox,
    QLineEdit, QFrame, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from found_it.config import DATA_DIR, DB_PATH, SNAPSHOTS_DIR
from found_it.storage.database import Database
from found_it.storage.models import AppSettings
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.saved_devices import load_saved_devices, save_saved_devices
from found_it.device.adb_handler import ADBHandler
from found_it.gui.room_setup_panel import INPUT_STYLE, BUTTON_STYLE, SECONDARY_BUTTON_STYLE, LIST_STYLE

NAV_STYLE = """
    QListWidget {
        background-color: #15152a;
        color: #ccc;
        border: none;
        padding: 6px;
        outline: none;
    }
    QListWidget::item { padding: 10px 12px; border-radius: 4px; margin: 2px 0; }
    QListWidget::item:selected { background-color: #6c63ff; color: white; }
    QListWidget::item:hover:!selected { background-color: #2a2a3e; }
"""


class SettingsPanel(QWidget):
    """App settings: detection/camera behavior, local data management, and saved ADB devices."""

    settings_updated = pyqtSignal()
    connect_device_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_settings = load_app_settings()
        self.saved_devices = load_saved_devices()
        self._detected_devices = []
        self._selected_saved_index: Optional[int] = None
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        outer.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setStyleSheet(NAV_STYLE)
        self.nav_list.setFixedWidth(170)
        self.nav_list.addItem(QListWidgetItem("Camera"))
        self.nav_list.addItem(QListWidgetItem("Data & Security"))
        self.nav_list.addItem(QListWidgetItem("Saved Devices"))
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        body.addWidget(self.nav_list)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #333;")
        body.addWidget(sep)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_camera_page())
        self.pages.addWidget(self._build_data_page())
        self.pages.addWidget(self._build_devices_page())
        body.addWidget(self.pages, 1)

        outer.addLayout(body, 1)

        self.nav_list.setCurrentRow(0)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        return lbl

    def _page_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl.setStyleSheet("color: #e0e0e0;")
        return lbl

    def _on_nav_changed(self, row: int):
        if row < 0:
            return
        self.pages.setCurrentIndex(row)
        if row == 1:
            self._refresh_data_stats()
        elif row == 2:
            self._refresh_detected_devices()
            self._refresh_saved_list()

    # ---------------- Camera page ----------------

    def _build_camera_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Camera"))
        desc = QLabel(
            "Tune how detection runs across your cameras. To add, position, enable, "
            "or rotate the physical cameras themselves, use the Room Setup tab."
        )
        desc.setStyleSheet("color: #888; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        conf_row = QHBoxLayout()
        conf_row.addWidget(self._label("Detection confidence"))
        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.05, 0.95)
        self.confidence_input.setSingleStep(0.05)
        self.confidence_input.setValue(self.app_settings.detection_confidence)
        self.confidence_input.setStyleSheet(INPUT_STYLE)
        conf_row.addWidget(self.confidence_input)
        conf_row.addStretch()
        layout.addLayout(conf_row)
        conf_hint = QLabel("Higher = fewer false positives, but may miss partially hidden items.")
        conf_hint.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(conf_hint)

        skip_row = QHBoxLayout()
        skip_row.addWidget(self._label("Detect every N frames"))
        self.frame_skip_input = QSpinBox()
        self.frame_skip_input.setRange(1, 15)
        self.frame_skip_input.setValue(self.app_settings.detection_frame_skip)
        self.frame_skip_input.setStyleSheet(INPUT_STYLE)
        skip_row.addWidget(self.frame_skip_input)
        skip_row.addStretch()
        layout.addLayout(skip_row)
        skip_hint = QLabel("Higher = less CPU usage, slower to notice new items.")
        skip_hint.setStyleSheet("color: #666; font-size: 10px;")
        layout.addWidget(skip_hint)

        self.dewarp_default_check = QCheckBox("Enable fisheye/360° dewarping by default")
        self.dewarp_default_check.setChecked(self.app_settings.dewarp_default)
        self.dewarp_default_check.setStyleSheet("color: #ccc;")
        layout.addWidget(self.dewarp_default_check)

        layout.addStretch()

        self.camera_status_label = QLabel("")
        self.camera_status_label.setStyleSheet("color: #6c63ff; font-size: 11px;")
        layout.addWidget(self.camera_status_label)

        save_btn = QPushButton("Save Camera Settings")
        save_btn.setStyleSheet(BUTTON_STYLE)
        save_btn.clicked.connect(self._on_save_camera_settings)
        layout.addWidget(save_btn)

        return page

    def _on_save_camera_settings(self):
        self.app_settings = AppSettings(
            detection_confidence=self.confidence_input.value(),
            detection_frame_skip=self.frame_skip_input.value(),
            dewarp_default=self.dewarp_default_check.isChecked(),
        )
        save_app_settings(self.app_settings)
        self.camera_status_label.setText("Saved. Applies immediately.")
        self.settings_updated.emit()

    # ---------------- Data & Security page ----------------

    def _build_data_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Data & Security"))
        desc = QLabel("Everything below is stored only on this machine. Nothing is uploaded anywhere.")
        desc.setStyleSheet("color: #888; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.data_dir_label = QLabel(f"Data folder: {DATA_DIR}")
        self.data_dir_label.setStyleSheet("color: #ccc; font-size: 11px;")
        self.data_dir_label.setWordWrap(True)
        self.data_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.data_dir_label)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #ccc; font-size: 11px;")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        clear_history_btn = QPushButton("Clear Detection History")
        clear_history_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        clear_history_btn.clicked.connect(self._on_clear_history)
        layout.addWidget(clear_history_btn)

        clear_snapshots_btn = QPushButton("Delete All Snapshots")
        clear_snapshots_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        clear_snapshots_btn.clicked.connect(self._on_clear_snapshots)
        layout.addWidget(clear_snapshots_btn)

        layout.addStretch()

        self.data_status_label = QLabel("")
        self.data_status_label.setStyleSheet("color: #6c63ff; font-size: 11px;")
        layout.addWidget(self.data_status_label)

        return page

    def _refresh_data_stats(self):
        db = Database()
        item_count = db.count_items()
        db.close()

        snap_count = 0
        snap_bytes = 0
        if SNAPSHOTS_DIR.exists():
            for f in SNAPSHOTS_DIR.iterdir():
                if f.is_file():
                    snap_count += 1
                    snap_bytes += f.stat().st_size

        snap_mb = snap_bytes / (1024 * 1024)
        self.stats_label.setText(
            f"Detected item records: {item_count}\n"
            f"Snapshot images: {snap_count} ({snap_mb:.1f} MB)\n"
            f"Database file: {DB_PATH}"
        )

    def _on_clear_history(self):
        confirm = QMessageBox.question(
            self, "Clear Detection History",
            "This permanently deletes all tracked item records from the database. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        db = Database()
        db.clear_all_items()
        db.close()
        self._refresh_data_stats()
        self.data_status_label.setText("Detection history cleared.")

    def _on_clear_snapshots(self):
        confirm = QMessageBox.question(
            self, "Delete All Snapshots",
            "This permanently deletes every saved snapshot image on disk. Continue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        deleted = 0
        if SNAPSHOTS_DIR.exists():
            for f in SNAPSHOTS_DIR.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        deleted += 1
                    except OSError:
                        pass
        self._refresh_data_stats()
        self.data_status_label.setText(f"Deleted {deleted} snapshot(s).")

    # ---------------- Saved Devices page ----------------

    def _build_devices_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Saved Devices"))
        desc = QLabel(
            "Devices currently visible over ADB (USB-C, debugging enabled) can be saved "
            "with a nickname so you can reconnect from here without rescanning."
        )
        desc.setStyleSheet("color: #888; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addWidget(self._label("Detected right now"))
        self.detected_list = QListWidget()
        self.detected_list.setStyleSheet(LIST_STYLE)
        self.detected_list.setMaximumHeight(90)
        layout.addWidget(self.detected_list)

        detect_row = QHBoxLayout()
        self.refresh_detected_btn = QPushButton("Refresh")
        self.refresh_detected_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.refresh_detected_btn.clicked.connect(self._refresh_detected_devices)
        detect_row.addWidget(self.refresh_detected_btn)

        self.nickname_input = QLineEdit()
        self.nickname_input.setPlaceholderText("Nickname (e.g. My Phone)")
        self.nickname_input.setStyleSheet(INPUT_STYLE)
        detect_row.addWidget(self.nickname_input)

        self.save_device_btn = QPushButton("Save Selected")
        self.save_device_btn.setStyleSheet(BUTTON_STYLE)
        self.save_device_btn.clicked.connect(self._on_save_device)
        detect_row.addWidget(self.save_device_btn)
        layout.addLayout(detect_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        layout.addWidget(self._label("Saved"))
        self.saved_list = QListWidget()
        self.saved_list.setStyleSheet(LIST_STYLE)
        self.saved_list.itemClicked.connect(self._on_saved_list_clicked)
        layout.addWidget(self.saved_list)

        saved_row = QHBoxLayout()
        self.connect_saved_btn = QPushButton("Connect")
        self.connect_saved_btn.setStyleSheet(BUTTON_STYLE)
        self.connect_saved_btn.clicked.connect(self._on_connect_saved)
        saved_row.addWidget(self.connect_saved_btn)

        self.remove_saved_btn = QPushButton("Remove")
        self.remove_saved_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.remove_saved_btn.clicked.connect(self._on_remove_saved)
        saved_row.addWidget(self.remove_saved_btn)
        layout.addLayout(saved_row)

        self.devices_status_label = QLabel("")
        self.devices_status_label.setStyleSheet("color: #6c63ff; font-size: 11px;")
        layout.addWidget(self.devices_status_label)

        return page

    def _refresh_detected_devices(self):
        adb = ADBHandler()
        self.detected_list.clear()
        if not adb.is_available():
            self.devices_status_label.setText("ADB not found — install Android platform-tools.")
            self._detected_devices = []
            return

        self._detected_devices = adb.get_devices()
        for dev in self._detected_devices:
            self.detected_list.addItem(QListWidgetItem(f"{dev.model}  ({dev.serial})"))

        if not self._detected_devices:
            self.devices_status_label.setText("No devices found. Connect via USB-C with debugging enabled.")
        else:
            self.devices_status_label.setText("")

    def _on_save_device(self):
        row = self.detected_list.currentRow()
        if row < 0 or row >= len(self._detected_devices):
            self.devices_status_label.setText("Select a detected device first.")
            return

        dev = self._detected_devices[row]
        nickname = self.nickname_input.text().strip() or dev.model

        existing = next((d for d in self.saved_devices if d["serial"] == dev.serial), None)
        if existing:
            existing["nickname"] = nickname
        else:
            self.saved_devices.append({"serial": dev.serial, "nickname": nickname})

        save_saved_devices(self.saved_devices)
        self._refresh_saved_list()
        self.nickname_input.clear()
        self.devices_status_label.setText(f"Saved \"{nickname}\".")

    def _refresh_saved_list(self):
        self.saved_list.clear()
        for i, dev in enumerate(self.saved_devices):
            item = QListWidgetItem(f"{dev['nickname']}  ({dev['serial']})")
            item.setData(Qt.UserRole, i)
            self.saved_list.addItem(item)
        self._selected_saved_index = None

    def _on_saved_list_clicked(self, item: QListWidgetItem):
        self._selected_saved_index = item.data(Qt.UserRole)

    def _on_connect_saved(self):
        if self._selected_saved_index is None:
            self.devices_status_label.setText("Select a saved device first.")
            return
        serial = self.saved_devices[self._selected_saved_index]["serial"]
        self.connect_device_requested.emit(serial)
        self.devices_status_label.setText("Connecting from Other Devices tab...")

    def _on_remove_saved(self):
        if self._selected_saved_index is None:
            self.devices_status_label.setText("Select a saved device first.")
            return
        removed = self.saved_devices.pop(self._selected_saved_index)
        save_saved_devices(self.saved_devices)
        self._refresh_saved_list()
        self.devices_status_label.setText(f"Removed \"{removed['nickname']}\".")
