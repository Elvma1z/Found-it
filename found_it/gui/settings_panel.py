import json
import os
import uuid
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox,
    QLineEdit, QFrame, QMessageBox, QFileDialog, QApplication, QButtonGroup
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase

from found_it.config import DATA_DIR, DB_PATH, SNAPSHOTS_DIR
from found_it.storage.database import Database
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.saved_devices import load_saved_devices, save_saved_devices
from found_it.utils.room_profiles import load_room_profiles, save_room_profiles, profile_from_dict, profiles_to_list
from found_it.utils.themes import THEME_NAMES, get_palette, widget_qss, repolish
from found_it.device.adb_handler import ADBHandler


class SettingsPanel(QWidget):
    """App settings: detection/camera behavior, local data management, and saved ADB devices."""

    settings_updated = pyqtSignal()
    connect_device_requested = pyqtSignal(str)
    rooms_imported = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_settings = load_app_settings()
        self.saved_devices = load_saved_devices()
        self._detected_devices = []
        self._selected_saved_index: Optional[int] = None
        self.palette = get_palette("Indigo")
        self._setup_ui()
        self.apply_theme(self.palette)

    def apply_theme(self, palette: dict):
        self.palette = palette
        p = palette
        self.setStyleSheet(widget_qss(palette))
        self.nav_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {p['header']};
                color: {p['text_dim']};
                border: none;
                padding: 6px;
                outline: none;
            }}
            QListWidget::item {{ padding: 10px 12px; border-radius: 4px; margin: 2px 0; }}
            QListWidget::item:selected {{ background-color: {p['accent']}; color: white; }}
            QListWidget::item:hover:!selected {{ background-color: {p['panel']}; }}
        """)
        repolish(self)

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        outer.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(170)
        self.nav_list.addItem(QListWidgetItem("Camera"))
        self.nav_list.addItem(QListWidgetItem("Appearance"))
        self.nav_list.addItem(QListWidgetItem("Data & Security"))
        self.nav_list.addItem(QListWidgetItem("Saved Devices"))
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        body.addWidget(self.nav_list)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setProperty("cls", "sep")
        body.addWidget(sep)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_camera_page())
        self.pages.addWidget(self._build_appearance_page())
        self.pages.addWidget(self._build_data_page())
        self.pages.addWidget(self._build_devices_page())
        body.addWidget(self.pages, 1)

        outer.addLayout(body, 1)

        self.nav_list.setCurrentRow(0)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("cls", "muted")
        return lbl

    def _page_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl.setProperty("cls", "title")
        return lbl

    def _on_nav_changed(self, row: int):
        if row < 0:
            return
        self.pages.setCurrentIndex(row)
        if row == 2:
            self._refresh_data_stats()
        elif row == 3:
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
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        conf_row = QHBoxLayout()
        conf_row.addWidget(self._label("Detection confidence"))
        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.05, 0.95)
        self.confidence_input.setSingleStep(0.05)
        self.confidence_input.setValue(self.app_settings.detection_confidence)
        conf_row.addWidget(self.confidence_input)
        conf_row.addStretch()
        layout.addLayout(conf_row)
        conf_hint = QLabel("Higher = fewer false positives, but may miss partially hidden items.")
        conf_hint.setProperty("cls", "hint")
        layout.addWidget(conf_hint)

        skip_row = QHBoxLayout()
        skip_row.addWidget(self._label("Detect every N frames"))
        self.frame_skip_input = QSpinBox()
        self.frame_skip_input.setRange(1, 15)
        self.frame_skip_input.setValue(self.app_settings.detection_frame_skip)
        skip_row.addWidget(self.frame_skip_input)
        skip_row.addStretch()
        layout.addLayout(skip_row)
        skip_hint = QLabel("Higher = less CPU usage, slower to notice new items.")
        skip_hint.setProperty("cls", "hint")
        layout.addWidget(skip_hint)

        self.dewarp_default_check = QCheckBox("Enable fisheye/360° dewarping by default")
        self.dewarp_default_check.setChecked(self.app_settings.dewarp_default)
        layout.addWidget(self.dewarp_default_check)

        layout.addStretch()

        self.camera_status_label = QLabel("")
        self.camera_status_label.setProperty("cls", "status")
        layout.addWidget(self.camera_status_label)

        save_btn = QPushButton("Save Camera Settings")
        save_btn.setProperty("cls", "primary")
        save_btn.clicked.connect(self._on_save_camera_settings)
        layout.addWidget(save_btn)

        return page

    def _on_save_camera_settings(self):
        self.app_settings.detection_confidence = self.confidence_input.value()
        self.app_settings.detection_frame_skip = self.frame_skip_input.value()
        self.app_settings.dewarp_default = self.dewarp_default_check.isChecked()
        save_app_settings(self.app_settings)
        self.camera_status_label.setText("Saved. Applies immediately.")
        self.settings_updated.emit()

    # ---------------- Appearance page ----------------

    def _build_appearance_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Appearance"))
        desc = QLabel("Pick the font used throughout the app, from what's installed on this machine.")
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.font_filter_input = QLineEdit()
        self.font_filter_input.setPlaceholderText("Filter fonts...")
        self.font_filter_input.textChanged.connect(self._on_font_filter_changed)
        layout.addWidget(self.font_filter_input)

        self.font_list = QListWidget()
        self._populate_font_list()
        layout.addWidget(self.font_list)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        themes_title = QLabel("Themes")
        themes_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        themes_title.setProperty("cls", "title")
        layout.addWidget(themes_title)

        themes_desc = QLabel(
            "Each theme colors the nav bar, docks, tabs, and buttons with shades of one color."
        )
        themes_desc.setProperty("cls", "muted")
        themes_desc.setWordWrap(True)
        layout.addWidget(themes_desc)

        themes_grid = QGridLayout()
        themes_grid.setSpacing(8)
        self.theme_button_group = QButtonGroup(self)
        self.theme_button_group.setExclusive(True)
        for i, name in enumerate(THEME_NAMES):
            btn = self._build_theme_swatch(name)
            self.theme_button_group.addButton(btn)
            themes_grid.addWidget(btn, i // 4, i % 4)
        layout.addLayout(themes_grid)

        layout.addStretch()

        self.appearance_status_label = QLabel("")
        self.appearance_status_label.setProperty("cls", "status")
        layout.addWidget(self.appearance_status_label)

        save_btn = QPushButton("Save Appearance Settings")
        save_btn.setProperty("cls", "primary")
        save_btn.clicked.connect(self._on_save_appearance_settings)
        layout.addWidget(save_btn)

        return page

    def _populate_font_list(self, filter_text: str = ""):
        self.font_list.clear()
        families = [f for f in QFontDatabase().families() if not f.startswith("@")]
        filter_text = filter_text.strip().lower()
        current_row = -1
        for family in families:
            if filter_text and filter_text not in family.lower():
                continue
            item = QListWidgetItem(f"{family}  —  The quick brown fox jumps over the lazy dog")
            item.setFont(QFont(family, 12))
            item.setData(Qt.UserRole, family)
            self.font_list.addItem(item)
            if family == self.app_settings.font_family:
                current_row = self.font_list.count() - 1
        if current_row >= 0:
            self.font_list.setCurrentRow(current_row)

    def _on_font_filter_changed(self, text: str):
        self._populate_font_list(text)

    def _build_theme_swatch(self, name: str) -> QPushButton:
        p = get_palette(name)
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setChecked(name == self.app_settings.theme)
        btn.setMinimumHeight(48)
        btn.setProperty("theme_name", name)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {p['panel']}, stop:0.33 {p['selected']},
                    stop:0.66 {p['hover']}, stop:1 {p['accent']});
                border: 2px solid {p['border']}; border-radius: 6px;
                color: {p['text']}; font-weight: bold; font-size: 12px;
                padding: 6px;
            }}
            QPushButton:checked {{ border: 2px solid {p['accent']}; }}
            QPushButton:hover {{ border: 2px solid {p['accent_hover']}; }}
        """)
        return btn

    def _on_save_appearance_settings(self):
        item = self.font_list.currentItem()
        if item is None:
            return
        family = item.data(Qt.UserRole)
        self.app_settings.font_family = family

        theme_btn = self.theme_button_group.checkedButton()
        if theme_btn is not None:
            self.app_settings.theme = theme_btn.property("theme_name")

        save_app_settings(self.app_settings)

        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont(family, 10))

        self.appearance_status_label.setText("Saved. Some titles pick up the new font on next launch.")
        self.settings_updated.emit()

    # ---------------- Data & Security page ----------------

    def _build_data_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Data & Security"))
        desc = QLabel("Everything below is stored only on this machine. Nothing is uploaded anywhere.")
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.data_dir_label = QLabel(f"Data folder: {DATA_DIR}")
        self.data_dir_label.setProperty("cls", "muted")
        self.data_dir_label.setWordWrap(True)
        self.data_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.data_dir_label)

        self.stats_label = QLabel("")
        self.stats_label.setProperty("cls", "muted")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        clear_history_btn = QPushButton("Clear Detection History")
        clear_history_btn.setProperty("cls", "secondary")
        clear_history_btn.clicked.connect(self._on_clear_history)
        layout.addWidget(clear_history_btn)

        clear_snapshots_btn = QPushButton("Delete All Snapshots")
        clear_snapshots_btn.setProperty("cls", "secondary")
        clear_snapshots_btn.clicked.connect(self._on_clear_snapshots)
        layout.addWidget(clear_snapshots_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setProperty("cls", "sep")
        layout.addWidget(sep2)

        room_data_hint = QLabel(
            "Room data (every saved room's size, zones, and cameras) is always kept in "
            "data/room_profiles.json. Export it to a .json file as a backup or to move your "
            "rooms to another computer; import adds the rooms from a file without touching "
            "what you already have."
        )
        room_data_hint.setProperty("cls", "hint")
        room_data_hint.setWordWrap(True)
        layout.addWidget(room_data_hint)

        room_data_row = QHBoxLayout()
        export_rooms_btn = QPushButton("Export Room Data...")
        export_rooms_btn.setProperty("cls", "secondary")
        export_rooms_btn.clicked.connect(self._on_export_rooms)
        room_data_row.addWidget(export_rooms_btn)

        import_rooms_btn = QPushButton("Import Room Data...")
        import_rooms_btn.setProperty("cls", "secondary")
        import_rooms_btn.clicked.connect(self._on_import_rooms)
        room_data_row.addWidget(import_rooms_btn)
        layout.addLayout(room_data_row)

        layout.addStretch()

        self.data_status_label = QLabel("")
        self.data_status_label.setProperty("cls", "status")
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

    def _on_export_rooms(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Room Data", "found_it_rooms.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            profiles = load_room_profiles()
            with open(path, "w") as f:
                json.dump(profiles_to_list(profiles), f, indent=2)
            self.data_status_label.setText(f"Exported {len(profiles)} room(s) to {path}.")
        except OSError as e:
            self.data_status_label.setText(f"Couldn't export: {e}")

    def _on_import_rooms(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Room Data", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r") as f:
                data = json.load(f)
            imported = [profile_from_dict(p) for p in data]
        except (OSError, ValueError) as e:
            self.data_status_label.setText(f"Couldn't read that file: {e}")
            return

        if not imported:
            self.data_status_label.setText("That file has no rooms in it.")
            return

        existing = load_room_profiles()
        existing_ids = {p.id for p in existing}
        existing_names = {p.name for p in existing}

        for profile in imported:
            if profile.id in existing_ids:
                profile.id = uuid.uuid4().hex[:8]
            name = profile.name
            suffix = 2
            while name in existing_names:
                name = f"{profile.name} ({suffix})"
                suffix += 1
            profile.name = name
            existing_ids.add(profile.id)
            existing_names.add(name)
            existing.append(profile)

        save_room_profiles(existing)
        self.data_status_label.setText(f"Imported {len(imported)} room(s) as new profiles.")
        self.rooms_imported.emit()

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
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addWidget(self._label("Detected right now"))
        self.detected_list = QListWidget()
        self.detected_list.setMaximumHeight(90)
        layout.addWidget(self.detected_list)

        detect_row = QHBoxLayout()
        self.refresh_detected_btn = QPushButton("Refresh")
        self.refresh_detected_btn.setProperty("cls", "secondary")
        self.refresh_detected_btn.clicked.connect(self._refresh_detected_devices)
        detect_row.addWidget(self.refresh_detected_btn)

        self.nickname_input = QLineEdit()
        self.nickname_input.setPlaceholderText("Nickname (e.g. My Phone)")
        detect_row.addWidget(self.nickname_input)

        self.save_device_btn = QPushButton("Save Selected")
        self.save_device_btn.setProperty("cls", "primary")
        self.save_device_btn.clicked.connect(self._on_save_device)
        detect_row.addWidget(self.save_device_btn)
        layout.addLayout(detect_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        layout.addWidget(self._label("Saved"))
        self.saved_list = QListWidget()
        self.saved_list.itemClicked.connect(self._on_saved_list_clicked)
        layout.addWidget(self.saved_list)

        saved_row = QHBoxLayout()
        self.connect_saved_btn = QPushButton("Connect")
        self.connect_saved_btn.setProperty("cls", "primary")
        self.connect_saved_btn.clicked.connect(self._on_connect_saved)
        saved_row.addWidget(self.connect_saved_btn)

        self.remove_saved_btn = QPushButton("Remove")
        self.remove_saved_btn.setProperty("cls", "secondary")
        self.remove_saved_btn.clicked.connect(self._on_remove_saved)
        saved_row.addWidget(self.remove_saved_btn)
        layout.addLayout(saved_row)

        self.devices_status_label = QLabel("")
        self.devices_status_label.setProperty("cls", "status")
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
