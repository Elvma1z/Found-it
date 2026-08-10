import json
import os
import uuid
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QListWidget, QListWidgetItem,
    QStackedWidget, QPushButton, QDoubleSpinBox, QSpinBox, QCheckBox,
    QLineEdit, QFrame, QMessageBox, QFileDialog, QApplication, QButtonGroup,
    QAbstractItemView, QMainWindow, QDockWidget, QScrollArea, QTabWidget, QComboBox,
    QGraphicsScene, QGraphicsView
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSize, QObject, QEvent
from PyQt5.QtGui import QFont, QFontDatabase, QFontMetrics, QPainter, QColor

from found_it.config import DATA_DIR, DB_PATH, SNAPSHOTS_DIR
from found_it.storage.database import Database
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.saved_devices import load_saved_devices, save_saved_devices
from found_it.utils.room_profiles import load_room_profiles, save_room_profiles, profile_from_dict, profiles_to_list
from found_it.utils.themes import THEME_NAMES, get_palette, widget_qss, repolish
from found_it.device.adb_handler import ADBHandler
from found_it.gui.splash import create_notice_splash
from found_it.gui.search_panel import SearchPanel
from found_it.gui.room_map import RoomMap
from found_it.gui.room_setup_panel import RoomSetupPanel
from found_it.gui.file_search_panel import FileSearchPanel
from found_it.gui.device_search_panel import DeviceSearchPanel


class _InertFilter(QObject):
    """Swallows input on a widget tree so a real panel can be embedded in the
    Panel Customization preview purely for looks - clicking "Scan Room with
    Cameras" or deleting a room profile in there would silently mutate the
    user's real data, which a "preview" has no business doing."""

    _BLOCKED = (
        QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
        QEvent.KeyPress, QEvent.KeyRelease, QEvent.Wheel, QEvent.ContextMenu,
    )

    def eventFilter(self, obj, event):
        return event.type() in self._BLOCKED


NAV_TAB_KEYS_DEFAULT = ["room", "room_setup", "file", "device"]
NAV_TAB_LABELS = {
    "room": "Room Tracker",
    "room_setup": "Room Setup",
    "file": "File Search",
    "device": "Other Devices",
}

DOCK_PANEL_KEYS_DEFAULT = ["camera_dock", "found_items_dock"]
DOCK_PANEL_LABELS = {
    "camera_dock": "Cameras",
    "found_items_dock": "Found Items",
}

PREVIEW_WIDTH = 1350
PREVIEW_HEIGHT = 600
PREVIEW_SCALE = 0.62
SIDEBAR_WIDTH = 320
SIDEBAR_THUMBNAIL_WIDTH = 280


class SettingsPanel(QWidget):
    """App settings: detection/camera behavior, local data management, and saved ADB devices."""

    settings_updated = pyqtSignal()
    connect_device_requested = pyqtSignal(str)
    rooms_imported = pyqtSignal()
    find_shortcut_requested = pyqtSignal()

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

        if hasattr(self, "preview_frame"):
            self._apply_preview_theme(p)

        repolish(self)

    def _apply_preview_theme(self, p: dict):
        """Styles the Panel Customization preview to match main_window's
        _apply_theme() pixel-for-pixel, so it looks exactly like the real
        app's nav bar and Room Tracker instead of an approximation - and
        picks up the current theme/font every time this runs, since both
        are saved (and this gets re-invoked) together from Appearance."""
        self.preview_frame.setStyleSheet(f"border: 1px solid {p['border']};")

        family = self.app_settings.font_family
        self.preview_app_title.setFont(QFont(family, 14, QFont.Bold))
        self.preview_map_title.setFont(QFont(family, 12, QFont.Bold))
        for header in getattr(self, "_sidebar_category_headers", {}).values():
            header.setFont(QFont(family, 11, QFont.Bold))

        self.preview_navbar.setStyleSheet(f"background-color: {p['bg']}; border-bottom: 1px solid {p['border']};")
        self.preview_app_title.setStyleSheet(f"color: {p['accent']};")

        nav_button_style = f"""
            QPushButton {{
                background: transparent; color: {p['text_dim']};
                border: none; border-bottom: 2px solid transparent;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px;
            }}
            QPushButton:checked {{
                background-color: {p['selected']}; color: {p['text']};
                border-bottom: 2px solid {p['accent']};
            }}
        """
        self.hero_list.setStyleSheet(f"""
            QListWidget {{ background: transparent; border: none; padding: 0; outline: none; }}
            QListWidget::item {{
                color: {p['text_dim']};
                border: none; border-bottom: 2px solid transparent;
                padding: 8px 32px;
            }}
            QListWidget::item:selected {{
                background-color: {p['selected']}; color: {p['text']};
                border-bottom: 2px solid {p['accent']};
            }}
        """)
        self.preview_settings_btn.setStyleSheet(nav_button_style.replace(
            "padding: 8px 20px;", "padding: 8px; font-size: 16px;"
        ))

        window_btn_style = f"""
            QPushButton {{
                background: transparent; color: {p['text_faint']}; border: none;
                font-size: 13px; font-weight: bold;
            }}
        """
        self.preview_min_btn.setStyleSheet(window_btn_style)
        self.preview_max_btn.setStyleSheet(window_btn_style)
        self.preview_close_btn.setStyleSheet(window_btn_style)

        self.preview_window.setStyleSheet(f"""
            QMainWindow {{ background-color: {p['bg']}; }}
            QMainWindow::separator {{ background: {p['border']}; width: 4px; height: 4px; }}
            QDockWidget {{ color: {p['text']}; font-size: 12px; font-weight: bold; }}
            QDockWidget::title {{ background: {p['header']}; padding: 6px 8px; border-bottom: 1px solid {p['border']}; }}
            QTabBar {{ background: {p['header']}; }}
            QTabBar::tab {{
                background: {p['panel']}; color: {p['text_dim']};
                padding: 6px 16px; border: 1px solid {p['border']};
                border-bottom: none; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {p['selected']}; color: {p['text']}; }}
            QMenuBar {{ background: {p['header']}; color: {p['text_dim']}; border-bottom: 1px solid {p['border']}; }}
            QMenuBar::item {{ padding: 4px 10px; }}
            QMenuBar::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
            QMenu {{ background: {p['panel']}; color: {p['text_dim']}; border: 1px solid {p['border']}; }}
            QMenu::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
        """)

        self.preview_cam_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {p['border']}; background: {p['bg']}; }}
            QTabBar::tab {{
                background: {p['panel']}; color: {p['text_dim']};
                padding: 6px 16px; border: 1px solid {p['border']};
                border-bottom: none; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {p['selected']}; color: {p['text']}; }}
        """)
        self.preview_cam_tabs.widget(0).setStyleSheet(
            f"background-color: {p['panel']}; color: {p['text_dim']}; font-size: 11px;"
        )
        self.preview_main_room_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {p['selected']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 4px;
                padding: 4px 12px; font-size: 12px; font-weight: bold;
            }}
        """)
        self.preview_dewarp_check.setStyleSheet(f"color: {p['text_dim']};")
        self.preview_map_title.setStyleSheet(f"color: {p['text']};")

        self.preview_room_selector.setStyleSheet(f"""
            QComboBox {{
                background-color: {p['panel']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }}
        """)

        self.preview_search_panel.apply_theme(p)
        self.preview_room_map.apply_theme(p)

        if hasattr(self, "preview_screens"):
            real_panels = set(getattr(self, "_preview_real_panels", []))
            for key, screen in self.preview_screens.items():
                if key == "room":
                    continue
                if screen in real_panels:
                    # Real panels theme themselves fully (widget_qss + repolish) -
                    # overwriting their stylesheet here would blank that out.
                    screen.apply_theme(p)
                else:
                    screen.setStyleSheet(f"background-color: {p['bg']};")

        if hasattr(self, "preview_view"):
            self.preview_view.setStyleSheet(f"border: 1px solid {p['border']}; border-radius: 6px;")
            self.preview_view.scene().setBackgroundBrush(QColor(p["bg"]))

            self.preview_sidebar.setStyleSheet(f"""
                QFrame {{ background-color: {p['panel']}; border: 1px solid {p['border']}; border-radius: 6px; }}
            """)
            self.sidebar_scroll.setStyleSheet("background: transparent; border: none;")
            self.sidebar_scroll.viewport().setStyleSheet("background: transparent;")
            for header in self._sidebar_category_headers.values():
                header.setStyleSheet(f"color: {p['text']};")
            for sep in self._sidebar_category_seps:
                sep.setStyleSheet(f"background-color: {p['border']};")

        for blank in getattr(self, "_preview_blank_widgets", []):
            blank.setStyleSheet(f"background-color: {p['bg']};")

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
        self.nav_list.addItem(QListWidgetItem("Customization"))
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
        self.pages.addWidget(self._build_customization_page())
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
        elif row == 4:
            self._refresh_customization_status()

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

    # ---------------- Customization page ----------------

    def _build_customization_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        page = QWidget()
        scroll.setWidget(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(8)

        layout.addWidget(self._page_title("Customization"))
        desc = QLabel(
            "Turn the \"Found It\" title in the nav bar into a shortcut for the "
            "button you use most."
        )
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.current_shortcut_label = self._label("")
        layout.addWidget(self.current_shortcut_label)

        find_row = QHBoxLayout()
        find_shortcut_btn = QPushButton("Find Shortcut")
        find_shortcut_btn.setProperty("cls", "primary")
        find_shortcut_btn.clicked.connect(self.find_shortcut_requested.emit)
        find_row.addWidget(find_shortcut_btn)

        clear_shortcut_btn = QPushButton("Clear Shortcut")
        clear_shortcut_btn.setProperty("cls", "secondary")
        clear_shortcut_btn.clicked.connect(self._on_clear_shortcut)
        find_row.addWidget(clear_shortcut_btn)
        find_row.addStretch()
        layout.addLayout(find_row)

        find_hint = QLabel(
            "This takes you back to the app. Double-click any button there to bind it. "
            "Clicking the tabs across the top still switches tabs as normal — it won't "
            "be picked up as the shortcut."
        )
        find_hint.setProperty("cls", "hint")
        find_hint.setWordWrap(True)
        layout.addWidget(find_hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        self._build_panel_customization_section(layout)

        layout.addStretch()

        return scroll

    def _refresh_customization_status(self):
        self.app_settings = load_app_settings()
        action = self.app_settings.title_hotkey_action
        if action.startswith("button:"):
            label = self.app_settings.title_hotkey_label or action[len("button:"):]
            self.current_shortcut_label.setText(f"Currently bound to: {label}")
        else:
            self.current_shortcut_label.setText("No shortcut set.")
        self._reload_panel_customization_preview()

    def _on_clear_shortcut(self):
        self.app_settings.title_hotkey_action = "none"
        self.app_settings.title_hotkey_label = ""
        save_app_settings(self.app_settings)
        self._refresh_customization_status()
        self.settings_updated.emit()

    # ---------------- Panel Customization subsection ----------------

    def _build_panel_customization_section(self, layout: QVBoxLayout):
        self._sidebar_category_headers = {}
        self._sidebar_category_seps = []
        self._preview_blank_widgets = []
        self._panels_cleared = False

        pc_title = QLabel("Panel Customization")
        pc_title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        pc_title.setProperty("cls", "title")
        layout.addWidget(pc_title)

        pc_desc = QLabel(
            "A live, working replica of the app, boxed to a fixed size so it stays out of the "
            "way. Drag the tabs or the Cameras / Found Items panels around inside it to try out "
            "a layout — nothing in the real app changes until you click \"Save Project\"."
        )
        pc_desc.setProperty("cls", "muted")
        pc_desc.setWordWrap(True)
        layout.addWidget(pc_desc)

        room_profiles = load_room_profiles()
        active_profile = room_profiles[0] if room_profiles else None

        self.preview_frame = QFrame()
        self.preview_frame.setFixedSize(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        # ================= mini nav / title bar - mirrors TitleBar exactly =================
        self.preview_navbar = QWidget()
        self.preview_navbar.setFixedHeight(48)
        nav_row = QHBoxLayout(self.preview_navbar)
        nav_row.setContentsMargins(12, 0, 0, 0)
        nav_row.setSpacing(0)

        self.preview_app_title = QLabel("Found It")
        nav_row.addWidget(self.preview_app_title)

        nav_row.addSpacing(24)

        self.hero_list = QListWidget()
        self.hero_list.setFlow(QListWidget.LeftToRight)
        self.hero_list.setWrapping(False)
        self.hero_list.setResizeMode(QListWidget.Adjust)
        self.hero_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.hero_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.hero_list.setFrameShape(QFrame.NoFrame)
        self.hero_list.setFixedHeight(48)
        # Qt's flow layout puts a leading gap (equal to spacing) above the
        # first row before drawing items - with the spacing this row used to
        # have, that pushed items far enough down to clip their text out of
        # this fixed 48px row entirely. A spacing that exactly makes up the
        # difference (48 - item height 40) keeps the row fully visible.
        self.hero_list.setSpacing(8)
        self.hero_list.setMinimumWidth(1080)
        self.hero_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hero_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hero_list.model().rowsMoved.connect(self._on_panel_customization_changed)
        self.hero_list.itemClicked.connect(self._on_hero_tab_clicked)
        nav_row.addWidget(self.hero_list)

        nav_row.addStretch()

        self.preview_settings_btn = QPushButton("⚙")
        self.preview_settings_btn.setCheckable(True)
        self.preview_settings_btn.setChecked(True)
        self.preview_settings_btn.setEnabled(False)
        self.preview_settings_btn.setFixedWidth(36)
        nav_row.addWidget(self.preview_settings_btn)

        nav_row.addSpacing(12)

        self.preview_min_btn = QPushButton("─")
        self.preview_min_btn.setFixedSize(44, 48)
        self.preview_min_btn.setEnabled(False)
        nav_row.addWidget(self.preview_min_btn)

        self.preview_max_btn = QPushButton("☐")
        self.preview_max_btn.setFixedSize(44, 48)
        self.preview_max_btn.setEnabled(False)
        nav_row.addWidget(self.preview_max_btn)

        self.preview_close_btn = QPushButton("✕")
        self.preview_close_btn.setFixedSize(44, 48)
        self.preview_close_btn.setEnabled(False)
        nav_row.addWidget(self.preview_close_btn)

        preview_layout.addWidget(self.preview_navbar)

        # ================= mini Room Tracker - real QMainWindow + docks =================
        self.preview_window = QMainWindow()
        self.preview_window.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
        )
        self.preview_view_menu = self.preview_window.menuBar().addMenu("View")

        # --- Cameras dock: real camera-tab chrome around a placeholder feed ---
        camera_widget = QWidget()
        camera_layout = QVBoxLayout(camera_widget)
        camera_layout.setContentsMargins(8, 8, 8, 8)

        controls = QHBoxLayout()
        self.preview_dewarp_check = QCheckBox("Dewarp")
        self.preview_dewarp_check.setEnabled(False)
        controls.addWidget(self.preview_dewarp_check)
        controls.addStretch()
        camera_layout.addLayout(controls)

        self.preview_cam_tabs = QTabWidget()
        cam_feed = QLabel("Live Feed")
        cam_feed.setAlignment(Qt.AlignCenter)
        self.preview_cam_tabs.addTab(cam_feed, "Camera 0")

        self.preview_main_room_btn = QPushButton(active_profile.name if active_profile else "Main Room")
        self.preview_main_room_btn.setEnabled(False)
        self.preview_cam_tabs.setCornerWidget(self.preview_main_room_btn, Qt.TopRightCorner)
        camera_layout.addWidget(self.preview_cam_tabs)

        self.preview_camera_dock = QDockWidget("Cameras", self.preview_window)
        self.preview_camera_dock.setObjectName("preview_camera_dock")
        self.preview_camera_dock.setWidget(camera_widget)
        self.preview_camera_dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.preview_camera_dock.dockLocationChanged.connect(self._on_panel_customization_changed)
        self.preview_view_menu.addAction(self.preview_camera_dock.toggleViewAction())

        # --- Found Items dock: the real SearchPanel widget, empty of results ---
        self.preview_search_panel = SearchPanel()
        self.preview_search_panel.show_all_items([])
        if room_profiles:
            self.preview_search_panel.set_room_names({p.id: p.name for p in room_profiles})

        self.preview_found_dock = QDockWidget("Found Items", self.preview_window)
        self.preview_found_dock.setObjectName("preview_found_dock")
        self.preview_found_dock.setWidget(self.preview_search_panel)
        self.preview_found_dock.setFeatures(QDockWidget.DockWidgetMovable)
        self.preview_found_dock.dockLocationChanged.connect(self._on_panel_customization_changed)
        self.preview_view_menu.addAction(self.preview_found_dock.toggleViewAction())

        # --- Room Map: the real RoomMap widget, fixed central area ---
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(4, 8, 4, 8)

        map_header = QHBoxLayout()
        self.preview_map_title = QLabel("Room Map")
        map_header.addWidget(self.preview_map_title)

        self.preview_room_selector = QComboBox()
        self.preview_room_selector.setMinimumWidth(140)
        self.preview_room_selector.setEnabled(False)
        for profile in room_profiles:
            self.preview_room_selector.addItem(profile.name)
        map_header.addWidget(self.preview_room_selector)

        map_header.addStretch()

        self.preview_status_indicator = QLabel("Scanning...")
        self.preview_status_indicator.setStyleSheet("color: #4caf50; font-size: 11px;")
        map_header.addWidget(self.preview_status_indicator)
        center_layout.addLayout(map_header)

        self.preview_room_map = RoomMap()
        if active_profile:
            self.preview_room_map.set_room_size(active_profile.width_m, active_profile.height_m)
            self.preview_room_map.set_zones(active_profile.zones)
            self.preview_room_map.set_cameras(active_profile.cameras)
        center_layout.addWidget(self.preview_room_map)

        self.preview_window.setCentralWidget(center_panel)

        # ================= other tabs' screens, shown when their tab is clicked =================
        # The real panels, so these look pixel-identical to the default app -
        # but made inert (see _InertFilter) since they're editors/scanners
        # with real side effects (deleting a room, renaming a face, writing
        # to the file index), not passive displays like Room Tracker's docks.
        self.preview_screens = {"room": self.preview_window}
        self.preview_screens["room_setup"] = self._build_preview_real_screen(
            RoomSetupPanel, "Room Setup", "Add rooms, position cameras, and draw zones on the floor plan."
        )
        self.preview_screens["file"] = self._build_preview_real_screen(
            FileSearchPanel, "Search", "Search and People tabs for finding files and faces across your index."
        )
        self.preview_screens["device"] = self._build_preview_real_screen(
            DeviceSearchPanel, "Other Devices", "Scan and browse files on phones connected over ADB."
        )

        self.preview_stack = QStackedWidget()
        for screen in self.preview_screens.values():
            self.preview_stack.addWidget(screen)
        preview_layout.addWidget(self.preview_stack, 1)

        # ================= scale the whole container down =================
        # preview_frame keeps its real, fully-readable internal size (font
        # metrics/sizing all key off of that) - a QGraphicsView just displays
        # it shrunk, forwarding clicks/drags through the same transform, so
        # none of that sizing work has to be redone at a smaller scale.
        scaled_w = round(PREVIEW_WIDTH * PREVIEW_SCALE)
        scaled_h = round(PREVIEW_HEIGHT * PREVIEW_SCALE)

        scene = QGraphicsScene(self)
        scene.addWidget(self.preview_frame)
        scene.setSceneRect(0, 0, PREVIEW_WIDTH, PREVIEW_HEIGHT)

        self.preview_view = QGraphicsView(scene)
        self.preview_view.setFixedSize(scaled_w, scaled_h)
        self.preview_view.setFrameShape(QFrame.NoFrame)
        self.preview_view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.preview_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_view.scale(PREVIEW_SCALE, PREVIEW_SCALE)

        # ================= sidebar: empty until "Clear Panels" fills it =================
        # Cleared panels land here as the real (scaled-down) widgets - not
        # text - grouped under a header for whichever tab they came from.
        sidebar = QFrame()
        sidebar.setFixedSize(SIDEBAR_WIDTH, scaled_h)
        sidebar_outer = QVBoxLayout(sidebar)
        sidebar_outer.setContentsMargins(0, 0, 0, 0)
        sidebar_outer.setSpacing(0)

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        sidebar_content = QWidget()
        self.sidebar_content_layout = QVBoxLayout(sidebar_content)
        self.sidebar_content_layout.setContentsMargins(10, 10, 10, 10)
        self.sidebar_content_layout.setSpacing(10)
        self.sidebar_content_layout.addStretch()
        self.sidebar_scroll.setWidget(sidebar_content)
        sidebar_outer.addWidget(self.sidebar_scroll)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        preview_row.addWidget(self.preview_view)
        preview_row.addWidget(sidebar)
        preview_row.addStretch()
        layout.addLayout(preview_row)

        self.preview_sidebar = sidebar
        self._reload_panel_customization_preview()

        self.panel_customization_status_label = QLabel("")
        self.panel_customization_status_label.setProperty("cls", "status")
        layout.addWidget(self.panel_customization_status_label)

        buttons_row = QHBoxLayout()
        save_project_btn = QPushButton("Save Project")
        save_project_btn.setProperty("cls", "primary")
        save_project_btn.clicked.connect(self._on_save_project)
        buttons_row.addWidget(save_project_btn, 1)

        clear_panels_btn = QPushButton("Clear Panels")
        clear_panels_btn.setProperty("cls", "secondary")
        clear_panels_btn.clicked.connect(self._on_clear_panels)
        buttons_row.addWidget(clear_panels_btn)
        layout.addLayout(buttons_row)

    def _build_preview_real_screen(self, panel_cls, title: str, desc: str) -> QWidget:
        """Instantiates the mode's actual panel class so the preview looks
        pixel-identical to the default app, made input-inert with
        _InertFilter, and its own apply_theme() re-run whenever the preview's
        theme changes. Falls back to a plain title/description placeholder
        if the real panel fails to construct (e.g. no ADB / camera hardware
        on this machine) so a Settings page can't be broken by it."""
        try:
            panel = panel_cls()
        except Exception:
            return self._build_preview_placeholder_screen(title, desc)

        guard = _InertFilter(panel)
        panel._preview_inert_guard = guard
        for w in [panel] + panel.findChildren(QWidget):
            w.installEventFilter(guard)

        if not hasattr(self, "_preview_real_panels"):
            self._preview_real_panels = []
        self._preview_real_panels.append(panel)
        return panel

    def _build_preview_placeholder_screen(self, title: str, desc: str) -> QWidget:
        """A lightweight stand-in for a mode's real panel - same title/description
        chrome, used only if that panel's real widget fails to construct."""
        screen = QWidget()
        screen_layout = QVBoxLayout(screen)
        screen_layout.setContentsMargins(16, 12, 16, 12)
        screen_layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setFont(QFont(self.app_settings.font_family, 16, QFont.Bold))
        title_label.setProperty("cls", "title")
        screen_layout.addWidget(title_label)

        desc_label = QLabel(desc)
        desc_label.setProperty("cls", "muted")
        desc_label.setWordWrap(True)
        screen_layout.addWidget(desc_label)

        screen_layout.addStretch()
        return screen

    def _on_hero_tab_clicked(self, item: QListWidgetItem):
        key = item.data(Qt.UserRole)
        screen = self.preview_screens.get(key)
        if screen is not None:
            self.preview_stack.setCurrentWidget(screen)

    def _get_nav_tab_order(self) -> list:
        raw = self.app_settings.nav_tab_order
        if raw:
            try:
                order = json.loads(raw)
                if sorted(order) == sorted(NAV_TAB_KEYS_DEFAULT):
                    return order
            except (ValueError, TypeError):
                pass
        return list(NAV_TAB_KEYS_DEFAULT)

    def _get_dock_panel_order(self) -> list:
        raw = self.app_settings.dock_panel_order
        if raw:
            try:
                order = json.loads(raw)
                if sorted(order) == sorted(DOCK_PANEL_KEYS_DEFAULT):
                    return order
            except (ValueError, TypeError):
                pass
        return list(DOCK_PANEL_KEYS_DEFAULT)

    def _reload_panel_customization_preview(self):
        self.hero_list.blockSignals(True)
        self.hero_list.clear()
        # Match the app's actual current font (which the user can change in
        # Appearance) rather than hardcoding one - measuring with a font
        # other than the one that ends up painted is what was truncating
        # labels with "..." even though the size hint "fit".
        item_font = QFont(QApplication.font())
        item_font.setBold(True)
        item_font.setPixelSize(13)
        metrics = QFontMetrics(item_font)
        for key in self._get_nav_tab_order():
            label = NAV_TAB_LABELS[key]
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            item.setTextAlignment(Qt.AlignCenter)
            item.setFont(item_font)
            # QSS padding alone doesn't reliably drive this QListWidget's item
            # sizing - without an explicit hint, items came out taller than
            # the fixed-height nav row and their text got clipped out of view.
            item.setSizeHint(QSize(metrics.horizontalAdvance(label) + 72, 40))
            self.hero_list.addItem(item)
        if self.hero_list.count():
            self.hero_list.setCurrentRow(0)
            if hasattr(self, "preview_stack"):
                self.preview_stack.setCurrentWidget(self.preview_screens["room"])
        self.hero_list.blockSignals(False)

        # dockLocationChanged can fire asynchronously (after the layout
        # settles, not synchronously inside addDockWidget), so a plain
        # disconnect/reconnect around this loop can still let a change we
        # caused ourselves slip through and falsely mark the preview dirty.
        # A guard flag that only gets cleared once the event loop has caught
        # up avoids that race.
        self._panel_customization_loading = True

        # Once cleared, the docks live as thumbnails in the sidebar - re-adding
        # them here (e.g. because the user left and re-opened Customization)
        # would yank them straight back out of those thumbnails.
        if not getattr(self, "_panels_cleared", False):
            order = self._get_dock_panel_order()
            areas = [Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea]
            docks = {"camera_dock": self.preview_camera_dock, "found_items_dock": self.preview_found_dock}
            for area, key in zip(areas, order):
                dock = docks.get(key)
                if dock is not None:
                    self.preview_window.addDockWidget(area, dock)

        self._panel_customization_dirty = False
        if hasattr(self, "panel_customization_status_label"):
            self.panel_customization_status_label.setText("")

        QTimer.singleShot(0, self._finish_panel_customization_reload)

    def _finish_panel_customization_reload(self):
        self._panel_customization_loading = False

    def _on_panel_customization_changed(self, *_args):
        if getattr(self, "_panel_customization_loading", False):
            return
        self._panel_customization_dirty = True
        self.panel_customization_status_label.setText(
            "Unsaved layout changes — the app looks the same until you save."
        )

    def _current_dock_panel_order(self) -> list:
        area = self.preview_window.dockWidgetArea(self.preview_camera_dock)
        if area == Qt.RightDockWidgetArea:
            return ["found_items_dock", "camera_dock"]
        return ["camera_dock", "found_items_dock"]

    def _wrap_as_thumbnail(self, widget: QWidget, size: QSize = None,
                            target_width: int = SIDEBAR_THUMBNAIL_WIDTH) -> QGraphicsView:
        """Shrinks a real widget to sidebar width the same way the main
        preview is scaled down, so a cleared panel (even a whole real one
        like Room Setup) still reads as itself instead of an unusable sliver."""
        if size is None or size.width() <= 0 or size.height() <= 0:
            size = widget.size()
        if size.width() <= 0 or size.height() <= 0:
            size = widget.sizeHint()
        width = max(size.width(), 1)
        height = max(size.height(), 1)
        scale = target_width / width
        target_height = max(round(height * scale), 30)

        scene = QGraphicsScene(self)
        scene.addWidget(widget)
        scene.setSceneRect(0, 0, width, height)

        view = QGraphicsView(scene)
        view.setFixedSize(target_width, target_height)
        view.setFrameShape(QFrame.NoFrame)
        view.setRenderHint(QPainter.SmoothPixmapTransform)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.scale(scale, scale)
        view.setStyleSheet(f"border: 1px solid {self.palette['border']}; border-radius: 4px;")
        return view

    def _blank_panel(self) -> QWidget:
        blank = QWidget()
        blank.setStyleSheet(f"background-color: {self.palette['bg']};")
        self._preview_blank_widgets.append(blank)
        return blank

    def _add_to_sidebar_category(self, category: str, items: list):
        """items: list of (widget, size) - size captured before the widget
        was detached from its old layout, since a hidden/reparented widget
        can no longer be trusted to report its own size."""
        insert_at = self.sidebar_content_layout.count() - 1  # keep the trailing stretch last

        if category not in self._sidebar_category_headers:
            if self._sidebar_category_headers:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet(f"background-color: {self.palette['border']};")
                self._sidebar_category_seps.append(sep)
                self.sidebar_content_layout.insertWidget(insert_at, sep)
                insert_at += 1

            header = QLabel(category)
            header.setFont(QFont(self.app_settings.font_family, 11, QFont.Bold))
            header.setStyleSheet(f"color: {self.palette['text']};")
            self._sidebar_category_headers[category] = header
            self.sidebar_content_layout.insertWidget(insert_at, header)
            insert_at += 1

        for widget, size in items:
            thumb = self._wrap_as_thumbnail(widget, size=size)
            self.sidebar_content_layout.insertWidget(insert_at, thumb)
            insert_at += 1

    def _on_clear_panels(self):
        if self._panels_cleared:
            return
        self._panels_cleared = True

        # --- Room Tracker: its 3 real panels, individually ---
        cam_size = self.preview_camera_dock.size()
        found_size = self.preview_found_dock.size()
        center = self.preview_window.centralWidget()
        center_size = center.size()

        self.preview_window.removeDockWidget(self.preview_camera_dock)
        self.preview_window.removeDockWidget(self.preview_found_dock)
        self.preview_window.setCentralWidget(self._blank_panel())

        self._add_to_sidebar_category("Room Tracker", [
            (self.preview_camera_dock, cam_size),
            (self.preview_found_dock, found_size),
            (center, center_size),
        ])

        # --- the other tabs: one whole panel each ---
        for key in ("room_setup", "file", "device"):
            screen = self.preview_screens.get(key)
            if screen is None:
                continue
            screen_size = screen.size()
            idx = self.preview_stack.indexOf(screen)
            self.preview_stack.insertWidget(idx, self._blank_panel())
            self.preview_stack.removeWidget(screen)
            self.preview_screens[key] = self.preview_stack.widget(idx)
            self._add_to_sidebar_category(NAV_TAB_LABELS[key], [(screen, screen_size)])

        self.preview_stack.setCurrentWidget(self.preview_screens["room"])
        if self.hero_list.count():
            self.hero_list.setCurrentRow(0)

        self.panel_customization_status_label.setText(
            "Panels moved to the sidebar, grouped by tab — the real app is untouched either way."
        )

    def _on_save_project(self):
        hero_order = [self.hero_list.item(i).data(Qt.UserRole) for i in range(self.hero_list.count())]
        panel_order = self._current_dock_panel_order()

        self.app_settings.nav_tab_order = json.dumps(hero_order)
        self.app_settings.dock_panel_order = json.dumps(panel_order)
        save_app_settings(self.app_settings)

        self._panel_customization_dirty = False
        self.panel_customization_status_label.setText("Saved. Applying new layout...")
        self.settings_updated.emit()

        splash = create_notice_splash(
            self.palette,
            "Layout Changed",
            "Saving a project layout completely changes how Found It looks. "
            "You can customize it again anytime from here.",
        )
        splash.show()
        QApplication.processEvents()
        QTimer.singleShot(2200, splash.close)
