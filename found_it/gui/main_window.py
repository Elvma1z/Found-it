import json
import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QTabWidget,
    QPushButton, QMenu, QDockWidget, QComboBox, QApplication
)
from PyQt5.QtCore import Qt, QTimer, QThread, QByteArray, QEvent, pyqtSignal
from PyQt5.QtGui import QFont

NAV_TAB_KEYS_DEFAULT = ["room", "room_setup", "file", "device"]
DOCK_PANEL_KEYS_DEFAULT = ["camera_dock", "found_items_dock"]

# Panels are pinned where they are in the live app: no Movable (drag to a
# different edge), no Floatable (tear off into its own window). Rearranging
# them is done deliberately, in Settings > Customization, against a preview -
# so an accidental drag on the title bar can't scramble the workspace.
# Closable stays on so a panel can still be hidden and brought back from the
# View menu, which doesn't change where anything sits.
LOCKED_DOCK_FEATURES = QDockWidget.DockWidgetClosable


class ClickableLabel(QLabel):
    """A QLabel that emits clicked() and swallows the press so it doesn't
    also trigger the parent TitleBar's window-drag handling."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class TitleBar(QWidget):
    """The nav bar doubles as the window's title bar: dragging empty space
    on it moves the (frameless) window, double-clicking toggles maximize."""

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            window = self.window()
            if window.isMaximized():
                window.showNormal()
            else:
                window.showMaximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

from found_it.config import ITEM_INACTIVE_SECONDS
from found_it.camera.capture import CameraCapture
from found_it.camera.dewarp import FisheyeDewarp, EquirectangularDewarp
from found_it.detection.detector import ItemDetector
from found_it.detection.item_mapper import ItemMapper
from found_it.storage.database import Database
from found_it.storage.models import DetectedItem
from found_it.utils.room_profiles import load_room_profiles
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.themes import get_palette, repolish
from found_it.gui.icons import get_icon, ICON_SIZE
from found_it.gui.camera_view import CameraView
from found_it.gui.room_map import RoomMap
from found_it.gui.search_panel import SearchPanel
from found_it.gui.file_search_panel import FileSearchPanel
from found_it.gui.device_search_panel import DeviceSearchPanel
from found_it.gui.room_setup_panel import RoomSetupPanel
from found_it.gui.settings_panel import SettingsPanel
from found_it.gui.camera_settings_panel import CameraSettingsPanel
from found_it.gui.detection_worker import DetectionWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Found It")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self._binding_shortcut = False

        self.room_profiles = load_room_profiles()
        self.app_settings = load_app_settings()
        self.palette = get_palette(self.app_settings.theme)
        self.active_room_id = self._resolve_active_room_id()
        self.db = Database()
        self.detector = ItemDetector()
        self.room_mappers = {}
        self.room_cameras = {}
        self.room_dewarpers = {}
        self.cam_views = {}
        self._tracked_item_id = None
        self._tracked_view = None

        self._setup_ui()
        self._setup_timers()
        self._start_all_room_cameras()

    def _get_profile(self, room_id):
        return next((p for p in self.room_profiles if p.id == room_id), None)

    def _resolve_active_room_id(self) -> str:
        if any(p.id == self.app_settings.active_room_id for p in self.room_profiles):
            return self.app_settings.active_room_id
        return self.room_profiles[0].id

    def _nav_button_style(self, extra: str = "") -> str:
        p = self.palette
        return f"""
            QPushButton {{
                background: transparent; color: {p['text_dim']};
                border: none; border-bottom: 2px solid transparent;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px; {extra}
            }}
            QPushButton:checked {{
                background-color: {p['selected']}; color: {p['text']};
                border-bottom: 2px solid {p['accent']};
            }}
            QPushButton:hover {{ color: {p['text']}; }}
        """

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.nav_bar = TitleBar()
        self.nav_bar.setFixedHeight(48)
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(12, 0, 0, 0)
        self.nav_layout = nav_layout

        self.app_title = ClickableLabel("Found It")
        self.app_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.app_title.clicked.connect(self._on_title_clicked)
        nav_layout.addWidget(self.app_title)

        nav_layout.addSpacing(24)
        nav_layout.addStretch()

        self.mode_room_btn = QPushButton("Room Tracker")
        self.mode_room_btn.setCheckable(True)
        self.mode_room_btn.setChecked(True)
        self.mode_room_btn.clicked.connect(lambda: self._switch_mode("room"))

        self.mode_room_setup_btn = QPushButton("Room Setup")
        self.mode_room_setup_btn.setCheckable(True)
        self.mode_room_setup_btn.clicked.connect(lambda: self._switch_mode("room_setup"))

        self.mode_file_btn = QPushButton("File Search")
        self.mode_file_btn.setCheckable(True)
        self.mode_file_btn.clicked.connect(lambda: self._switch_mode("file"))

        self.mode_device_btn = QPushButton("Other Devices")
        self.mode_device_btn.setCheckable(True)
        self.mode_device_btn.clicked.connect(lambda: self._switch_mode("device"))

        self.nav_mode_buttons = {
            "room": self.mode_room_btn,
            "room_setup": self.mode_room_setup_btn,
            "file": self.mode_file_btn,
            "device": self.mode_device_btn,
        }
        self._nav_tabs_insert_index = nav_layout.count()
        self._apply_nav_tab_order()

        self.mode_cameras_btn = QPushButton("Cameras")
        self.mode_cameras_btn.setCheckable(True)
        self.mode_cameras_btn.clicked.connect(lambda: self._switch_mode("cameras"))
        room_setup_index = nav_layout.indexOf(self.mode_room_setup_btn)
        nav_layout.insertWidget(room_setup_index + 1, self.mode_cameras_btn)

        nav_layout.addStretch()

        self.settings_btn = QPushButton()
        self.settings_btn.setIconSize(ICON_SIZE)
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedWidth(36)
        self.settings_btn.clicked.connect(lambda: self._switch_mode("settings"))
        nav_layout.addWidget(self.settings_btn)

        nav_layout.addSpacing(12)

        self.minimize_btn = QPushButton()
        self.minimize_btn.setIconSize(ICON_SIZE)
        self.minimize_btn.setFixedSize(44, 48)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.clicked.connect(self.showMinimized)
        nav_layout.addWidget(self.minimize_btn)

        self.maximize_btn = QPushButton()
        self.maximize_btn.setIconSize(ICON_SIZE)
        self.maximize_btn.setFixedSize(44, 48)
        self.maximize_btn.setToolTip("Maximize")
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        nav_layout.addWidget(self.maximize_btn)

        self.close_btn = QPushButton()
        self.close_btn.setIconSize(ICON_SIZE)
        self.close_btn.setFixedSize(44, 48)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self.close)
        nav_layout.addWidget(self.close_btn)

        main_layout.addWidget(self.nav_bar)

        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.room_widget = self._build_room_view()
        self.room_setup_panel = RoomSetupPanel()
        self.room_setup_panel.room_updated.connect(self._on_room_updated)
        self.file_search_panel = FileSearchPanel()
        self.device_search_panel = DeviceSearchPanel()
        self.camera_settings_panel = CameraSettingsPanel()
        self.camera_settings_panel.settings_updated.connect(self._on_camera_settings_updated)
        self.settings_panel = SettingsPanel()
        self.settings_panel.settings_updated.connect(self._on_settings_updated)
        self.settings_panel.connect_device_requested.connect(self._on_connect_saved_device)
        self.settings_panel.rooms_imported.connect(self._on_rooms_imported)
        self.settings_panel.find_shortcut_requested.connect(self.start_shortcut_binding)

        self.content_layout.addWidget(self.room_widget)
        self.content_layout.addWidget(self.room_setup_panel)
        self.content_layout.addWidget(self.file_search_panel)
        self.content_layout.addWidget(self.device_search_panel)
        self.content_layout.addWidget(self.camera_settings_panel)
        self.content_layout.addWidget(self.settings_panel)

        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.camera_settings_panel.hide()
        self.settings_panel.hide()

        main_layout.addWidget(self.content_stack)

        self.statusBar().showMessage("Ready")

        self._apply_theme()

    def _apply_theme(self):
        p = self.palette

        self.nav_bar.setStyleSheet(f"background-color: {p['bg']}; border-bottom: 1px solid {p['border']};")
        self.app_title.setStyleSheet(f"color: {p['accent']};")
        self._refresh_title_hotkey()

        nav_style = self._nav_button_style()
        for btn in (self.mode_room_btn, self.mode_room_setup_btn, self.mode_file_btn,
                    self.mode_device_btn, self.mode_cameras_btn):
            btn.setStyleSheet(nav_style)
        self.settings_btn.setStyleSheet(self._nav_button_style("padding: 8px;"))
        self.settings_btn.setIcon(get_icon("settings", p["text_faint"]))

        window_btn_style = f"""
            QPushButton {{
                background: transparent; border: none;
            }}
            QPushButton:hover {{ background-color: {p['selected']}; }}
        """
        self.minimize_btn.setStyleSheet(window_btn_style)
        self.maximize_btn.setStyleSheet(window_btn_style)
        self.close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
            }}
            QPushButton:hover {{ background-color: #e53935; }}
        """)
        self.minimize_btn.setIcon(get_icon("minus", p["text_faint"]))
        self.maximize_btn.setIcon(get_icon("copy" if self.isMaximized() else "square", p["text_faint"]))
        self.close_btn.setIcon(get_icon("x", p["text_faint"]))

        self.statusBar().setStyleSheet(f"color: {p['text_faint']}; background: {p['header']};")

        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {p['bg']}; }}
            QSplitter::handle {{ background-color: {p['border']}; }}
        """)

        self.room_widget.setStyleSheet(f"""
            QMainWindow::separator {{ background: {p['border']}; width: 4px; height: 4px; }}
            QMainWindow::separator:hover {{ background: {p['accent']}; }}
            QDockWidget {{ color: {p['text']}; font-size: 12px; font-weight: bold; }}
            QDockWidget::title {{ background: {p['header']}; padding: 6px 8px; border-bottom: 1px solid {p['border']}; }}
            QTabBar {{ background: {p['header']}; }}
            QTabBar::tab {{
                background: {p['panel']}; color: {p['text_dim']};
                padding: 6px 16px; border: 1px solid {p['border']};
                border-bottom: none; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {p['selected']}; color: {p['text']}; }}
            QTabBar::tab:hover {{ color: {p['text']}; }}
            QMenuBar {{ background: {p['header']}; color: {p['text_dim']}; border-bottom: 1px solid {p['border']}; }}
            QMenuBar::item {{ padding: 4px 10px; }}
            QMenuBar::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
            QMenu {{ background: {p['panel']}; color: {p['text_dim']}; border: 1px solid {p['border']}; }}
            QMenu::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
        """)

        self.cam_tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: 1px solid {p['border']}; background: {p['bg']}; }}
            QTabBar::tab {{
                background: {p['panel']}; color: {p['text_dim']};
                padding: 6px 16px; border: 1px solid {p['border']};
                border-bottom: none; border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{ background: {p['selected']}; color: {p['text']}; }}
        """)

        self.main_room_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {p['selected']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 4px;
                padding: 4px 12px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {p['hover']}; }}
            QPushButton::menu-indicator {{ width: 0px; }}
        """)

        self.dewarp_check.setStyleSheet(f"color: {p['text_dim']};")
        self.map_title.setStyleSheet(f"color: {p['text']};")

        self.room_map_selector.setStyleSheet(f"""
            QComboBox {{
                background-color: {p['panel']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }}
            QComboBox:hover {{ background-color: {p['hover']}; }}
            QComboBox QAbstractItemView {{
                background-color: {p['panel']}; color: {p['text']};
                border: 1px solid {p['border']};
                selection-background-color: {p['selected']};
                selection-color: {p['text']};
                outline: none;
            }}
        """)

        self.room_map.apply_theme(p)
        self.search_panel.apply_theme(p)
        self.room_setup_panel.apply_theme(p)
        self.file_search_panel.apply_theme(p)
        self.device_search_panel.apply_theme(p)
        self.camera_settings_panel.apply_theme(p)
        self.settings_panel.apply_theme(p)
        for view in self.cam_views.values():
            view.apply_theme(p)

        repolish(self)

    def _build_room_view(self):
        tracker = QMainWindow()
        tracker.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
        )

        view_menu = tracker.menuBar().addMenu("View")

        # --- Cameras dock: position fixed, see LOCKED_DOCK_FEATURES ---
        camera_widget = QWidget()
        camera_layout = QVBoxLayout(camera_widget)
        camera_layout.setContentsMargins(8, 8, 8, 8)

        controls = QHBoxLayout()
        self.dewarp_check = QCheckBox("Dewarp")
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        controls.addWidget(self.dewarp_check)
        controls.addStretch()
        camera_layout.addLayout(controls)

        self.cam_tabs = QTabWidget()

        active_profile = self._get_profile(self.active_room_id)
        self.main_room_btn = QPushButton(active_profile.name)
        self.main_room_btn.clicked.connect(self._show_room_menu)
        self.cam_tabs.setCornerWidget(self.main_room_btn, Qt.TopRightCorner)
        camera_layout.addWidget(self.cam_tabs)

        self.camera_dock = QDockWidget("Cameras", tracker)
        self.camera_dock.setObjectName("camera_dock")
        self.camera_dock.setWidget(camera_widget)
        self.camera_dock.setFeatures(LOCKED_DOCK_FEATURES)
        tracker.addDockWidget(Qt.LeftDockWidgetArea, self.camera_dock)
        view_menu.addAction(self.camera_dock.toggleViewAction())

        # --- Found Items dock: position fixed, see LOCKED_DOCK_FEATURES ---
        self.search_panel = SearchPanel()
        self.search_panel.item_selected.connect(self._on_item_selected)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})

        self.found_items_dock = QDockWidget("Found Items", tracker)
        self.found_items_dock.setObjectName("found_items_dock")
        self.found_items_dock.setWidget(self.search_panel)
        self.found_items_dock.setFeatures(LOCKED_DOCK_FEATURES)
        tracker.addDockWidget(Qt.RightDockWidgetArea, self.found_items_dock)
        view_menu.addAction(self.found_items_dock.toggleViewAction())

        # --- Room Map: fixed central area ---
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(4, 8, 4, 8)

        map_header = QHBoxLayout()
        self.map_title = QLabel("Room Map")
        self.map_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        map_header.addWidget(self.map_title)

        self.room_map_selector = QComboBox()
        self.room_map_selector.setMinimumWidth(140)
        self._refresh_room_map_selector()
        self.room_map_selector.currentIndexChanged.connect(self._on_room_map_selector_changed)
        map_header.addWidget(self.room_map_selector)

        map_header.addStretch()

        self.status_indicator = QLabel("Scanning...")
        self.status_indicator.setStyleSheet("color: #4caf50; font-size: 11px;")
        map_header.addWidget(self.status_indicator)
        center_layout.addLayout(map_header)

        self.room_map = RoomMap()
        self.room_map.set_room_size(active_profile.width_m, active_profile.height_m)
        self.room_map.set_zones(active_profile.zones)
        self.room_map.set_cameras(active_profile.cameras)
        center_layout.addWidget(self.room_map)

        tracker.setCentralWidget(center_panel)

        self.room_widget = tracker

        self._restore_room_tracker_layout(tracker)
        # Applied *after* the restore, not before: the saved state describes
        # wherever the docks last sat, which for a layout saved back when they
        # were draggable can contradict - or float away from - the arrangement
        # set in Customization. Customization is the only way to move panels
        # now, so it gets the last word and the restore only carries sizes.
        self._apply_dock_panel_order()

        return tracker

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

    def _apply_nav_tab_order(self):
        order = self._get_nav_tab_order()
        for btn in self.nav_mode_buttons.values():
            self.nav_layout.removeWidget(btn)
        for i, key in enumerate(order):
            btn = self.nav_mode_buttons.get(key)
            if btn is not None:
                self.nav_layout.insertWidget(self._nav_tabs_insert_index + i, btn)

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

    def _apply_dock_panel_order(self):
        order = self._get_dock_panel_order()
        docks = {"camera_dock": self.camera_dock, "found_items_dock": self.found_items_dock}
        areas = [Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea]
        for area, key in zip(areas, order):
            dock = docks.get(key)
            if dock is not None:
                # A layout saved while the dock was torn off would otherwise
                # leave it floating with no way to drag it back.
                dock.setFloating(False)
                self.room_widget.addDockWidget(area, dock)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and hasattr(self, "maximize_btn"):
            self.maximize_btn.setIcon(get_icon("copy" if self.isMaximized() else "square", self.palette["text_faint"]))
            self.maximize_btn.setToolTip("Restore" if self.isMaximized() else "Maximize")
        super().changeEvent(event)

    def _switch_mode(self, mode):
        self.room_widget.hide()
        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.camera_settings_panel.hide()
        self.settings_panel.hide()
        self.mode_room_btn.setChecked(False)
        self.mode_room_setup_btn.setChecked(False)
        self.mode_file_btn.setChecked(False)
        self.mode_device_btn.setChecked(False)
        self.mode_cameras_btn.setChecked(False)
        self.settings_btn.setChecked(False)

        if mode == "room":
            self.room_widget.show()
            self.mode_room_btn.setChecked(True)
        elif mode == "room_setup":
            self.room_setup_panel.show()
            self.mode_room_setup_btn.setChecked(True)
        elif mode == "file":
            self.file_search_panel.show()
            self.mode_file_btn.setChecked(True)
        elif mode == "device":
            self.device_search_panel.show()
            self.mode_device_btn.setChecked(True)
        elif mode == "cameras":
            self.camera_settings_panel.show()
            self.mode_cameras_btn.setChecked(True)
        elif mode == "settings":
            self.settings_panel.show()
            self.settings_btn.setChecked(True)

    # ---------------- Title shortcut: bind "Found It" to any button ----------------

    def _build_shortcut_registry(self):
        """Map every QPushButton reachable from self via attributes (recursing
        into nested panels/tabs) to a dotted path, e.g. "room_setup_panel.scan_room_btn".
        Rebuilt lazily so buttons created after startup (rare) still get picked up."""
        self._shortcut_paths = {}
        self._shortcut_buttons = {}
        self._collect_button_paths(self, "", set(), self._shortcut_paths, self._shortcut_buttons)

    def _collect_button_paths(self, root, prefix, seen, paths, buttons, depth=0):
        if depth > 6 or id(root) in seen:
            return
        seen.add(id(root))
        try:
            items = list(vars(root).items())
        except TypeError:
            return
        for name, value in items:
            if name.startswith("_"):
                continue
            path = f"{prefix}.{name}" if prefix else name
            if isinstance(value, QPushButton):
                paths[path] = value
                buttons[id(value)] = path
            elif isinstance(value, QWidget):
                self._collect_button_paths(value, path, seen, paths, buttons, depth + 1)

    def _shortcut_excluded_buttons(self):
        return {
            self.mode_room_btn, self.mode_room_setup_btn, self.mode_file_btn,
            self.mode_device_btn, self.settings_btn,
            self.minimize_btn, self.maximize_btn, self.close_btn,
        }

    def start_shortcut_binding(self):
        self._build_shortcut_registry()
        self._binding_shortcut = True
        self._switch_mode("room")
        self.statusBar().showMessage(
            "Double-click any button to make it the \"Found It\" shortcut. Tabs still work "
            "normally. Press Esc to cancel."
        )
        QApplication.instance().installEventFilter(self)

    def _stop_shortcut_binding(self):
        self._binding_shortcut = False
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, event):
        if getattr(self, "_binding_shortcut", False):
            if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self._stop_shortcut_binding()
                self.statusBar().showMessage("Shortcut selection cancelled.", 3000)
                return True
            if event.type() == QEvent.MouseButtonDblClick and isinstance(obj, QPushButton):
                if obj in self._shortcut_excluded_buttons():
                    return False
                path = self._shortcut_buttons.get(id(obj))
                self._stop_shortcut_binding()
                if path is not None:
                    self.app_settings.title_hotkey_action = f"button:{path}"
                    self.app_settings.title_hotkey_label = obj.text() or path.rsplit(".", 1)[-1]
                    save_app_settings(self.app_settings)
                    self._refresh_title_hotkey()
                    self.statusBar().showMessage(
                        f"\"Found It\" now opens: {self.app_settings.title_hotkey_label}", 4000
                    )
                else:
                    self.statusBar().showMessage("That button can't be used as a shortcut.", 4000)
                return True
        return super().eventFilter(obj, event)

    def _refresh_title_hotkey(self):
        action = self.app_settings.title_hotkey_action
        if action.startswith("button:"):
            self.app_title.setCursor(Qt.PointingHandCursor)
            label = self.app_settings.title_hotkey_label or action[len("button:"):]
            self.app_title.setToolTip(f"Shortcut: {label}")
        else:
            self.app_title.setCursor(Qt.ArrowCursor)
            self.app_title.setToolTip("")

    def _on_title_clicked(self):
        action = self.app_settings.title_hotkey_action
        if not action.startswith("button:"):
            return
        path = action[len("button:"):]
        if not hasattr(self, "_shortcut_paths"):
            self._build_shortcut_registry()
        btn = self._shortcut_paths.get(path)
        if btn is None:
            self._build_shortcut_registry()
            btn = self._shortcut_paths.get(path)
        if btn is not None:
            self._reveal_and_click(btn)

    def _reveal_and_click(self, btn: QPushButton):
        # Show whichever nested QTabWidget page(s) the button lives inside.
        for tabs in self.findChildren(QTabWidget):
            if tabs.isAncestorOf(btn):
                for i in range(tabs.count()):
                    if tabs.widget(i) is btn or tabs.widget(i).isAncestorOf(btn):
                        tabs.setCurrentIndex(i)
                        break

        # Show whichever top-level mode panel the button lives inside.
        panels = {
            "room": self.room_widget,
            "room_setup": self.room_setup_panel,
            "file": self.file_search_panel,
            "device": self.device_search_panel,
            "cameras": self.camera_settings_panel,
            "settings": self.settings_panel,
        }
        for mode, panel in panels.items():
            if panel.isAncestorOf(btn):
                self._switch_mode(mode)
                break

        btn.click()

    def _show_room_menu(self):
        menu = QMenu(self)
        for profile in self.room_profiles:
            action = menu.addAction(profile.name)
            action.setCheckable(True)
            action.setChecked(profile.id == self.active_room_id)
            action.triggered.connect(lambda checked, rid=profile.id: self._switch_display_room(rid))
        menu.exec_(self.main_room_btn.mapToGlobal(self.main_room_btn.rect().bottomLeft()))

    def _refresh_room_map_selector(self):
        """Repopulate the room dropdown next to the "Room Map" heading from
        the rooms currently defined in Room Setup, and select whichever one
        is being displayed."""
        self.room_map_selector.blockSignals(True)
        self.room_map_selector.clear()
        for profile in self.room_profiles:
            self.room_map_selector.addItem(profile.name, profile.id)
        index = self.room_map_selector.findData(self.active_room_id)
        if index >= 0:
            self.room_map_selector.setCurrentIndex(index)
        self.room_map_selector.blockSignals(False)

    def _on_room_map_selector_changed(self, index: int):
        room_id = self.room_map_selector.itemData(index)
        if room_id is not None:
            self._switch_display_room(room_id)

    def _switch_display_room(self, room_id: str):
        if room_id == self.active_room_id or self._get_profile(room_id) is None:
            return
        self.active_room_id = room_id
        self.app_settings.active_room_id = room_id
        save_app_settings(self.app_settings)
        self._refresh_display_room_ui()

    def _on_settings_updated(self):
        self.app_settings = load_app_settings()
        # load_app_settings() returns a new object each time, so the
        # detection worker thread (which was handed the old one) needs its
        # reference refreshed too, or it'd keep using stale confidence/
        # frame-skip/dewarp values forever.
        self.detection_worker.app_settings = self.app_settings
        self.palette = get_palette(self.app_settings.theme)
        self._apply_theme()
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        self._apply_nav_tab_order()
        self._apply_dock_panel_order()
        self._start_all_room_cameras()

    def _on_connect_saved_device(self, serial: str):
        self._switch_mode("device")
        self.device_search_panel.connect_saved_device(serial)

    def _on_room_updated(self):
        # Mutate the existing list in place rather than rebinding
        # self.room_profiles - the detection worker thread holds a direct
        # reference to this same list object so it always sees current
        # rooms without needing to be re-wired every time they change.
        self.room_profiles[:] = load_room_profiles()
        if self._get_profile(self.active_room_id) is None:
            self.active_room_id = self.room_profiles[0].id
            self.app_settings.active_room_id = self.active_room_id
            save_app_settings(self.app_settings)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})
        self._start_all_room_cameras()
        # Room Setup's own Save writes camera position/removal changes made
        # by dragging on its canvas - keep the Cameras tab's in-memory copy
        # from going stale and clobbering those on its next Save.
        self.camera_settings_panel.reload_profiles()

    def _on_camera_settings_updated(self):
        self._on_settings_updated()
        # The Cameras tab's own Save writes camera add/rename/toggle/remove
        # changes - keep Room Setup's in-memory copy (and its canvas) from
        # going stale and clobbering those on its next Save Room.
        self.room_setup_panel.reload_profiles()

    def _on_rooms_imported(self):
        self._on_room_updated()
        self.room_setup_panel.reload_profiles()

    def _setup_timers(self):
        # Detection (camera capture -> dewarp -> YOLO inference -> merge)
        # runs on its own QThread so a slow inference pass doesn't freeze
        # the UI. Results come back via cycle_done, handled on this
        # (the GUI) thread since DB writes and widget updates must be.
        self.detection_worker = DetectionWorker(self.detector, self.app_settings)
        self.detection_worker.room_profiles = self.room_profiles
        self.detection_worker.room_cameras = self.room_cameras
        self.detection_worker.room_dewarpers = self.room_dewarpers
        self.detection_worker.room_mappers = self.room_mappers
        self.detection_worker.dewarp_enabled = self.dewarp_check.isChecked()
        self.detection_worker.cycle_done.connect(self._on_detection_cycle_done)
        self.dewarp_check.toggled.connect(self._on_dewarp_toggled)

        self._detection_thread = QThread(self)
        self.detection_worker.moveToThread(self._detection_thread)
        self._detection_thread.started.connect(self.detection_worker.start)
        self._detection_thread.start()

        self._display_timer = QTimer()
        self._display_timer.timeout.connect(self._display_cycle)
        self._display_timer.start(50)

        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup_cycle)
        self._cleanup_timer.start(30000)

        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_display)
        self._refresh_timer.start(2000)

    def _start_all_room_cameras(self):
        """(Re)start every saved room profile's cameras so all of them keep
        tracking in the background, regardless of which one is displayed."""
        for cams in self.room_cameras.values():
            for cam in cams.values():
                cam.stop()

        # Clear in place rather than rebinding - the detection worker
        # thread holds direct references to these same dict objects, so
        # replacing them here would leave it watching stale, empty dicts.
        self.room_cameras.clear()
        self.room_dewarpers.clear()
        self.room_mappers.clear()
        used_device_ids = {}

        for profile in self.room_profiles:
            self.room_mappers[profile.id] = ItemMapper(profile)
            cams = {}
            dewarpers = {}

            for cam_cfg in profile.cameras:
                if not cam_cfg.get("enabled"):
                    continue

                cam_id = cam_cfg["id"]
                if cam_id in used_device_ids:
                    self.statusBar().showMessage(
                        f"Camera {cam_id} in \"{profile.name}\" skipped - already in use by "
                        f"\"{used_device_ids[cam_id]}\". Give each room's cameras distinct IDs."
                    )
                    continue

                cam = CameraCapture(cam_id)
                if not cam.start():
                    continue

                used_device_ids[cam_id] = profile.name
                cams[cam_id] = cam

                if cam_cfg.get("is_360"):
                    dewarpers[cam_id] = EquirectangularDewarp(fov=90.0, num_views=4)
                elif cam_cfg.get("is_180") or self.app_settings.dewarp_default:
                    # A 180 deg lens is a fisheye lens - its barrel distortion
                    # is severe enough at the edges that it's always worth
                    # correcting, regardless of the app-wide dewarp default.
                    dewarper = FisheyeDewarp(cam_id)
                    frame = cam.get_frame()
                    if frame is not None:
                        h, w = frame.shape[:2]
                        dewarper.load_calibration((w, h))
                    dewarpers[cam_id] = dewarper

            self.room_cameras[profile.id] = cams
            self.room_dewarpers[profile.id] = dewarpers

        self._refresh_display_room_ui()

    def _refresh_display_room_ui(self):
        """Rebuild the camera tabs and room map for whichever room is
        currently selected as the displayed "Main Room" - the underlying
        camera captures for every room keep running regardless."""
        self.cam_tabs.clear()
        self.cam_views = {}

        profile = self._get_profile(self.active_room_id)
        if profile is None:
            return

        cams = self.room_cameras.get(profile.id, {})
        for cam_cfg in profile.cameras:
            if not cam_cfg.get("enabled"):
                continue
            cam_id = cam_cfg["id"]
            if cam_id not in cams:
                continue
            label = cam_cfg.get("label", f"Camera {cam_id}")
            view = CameraView(cam_id, palette=self.palette)
            self.cam_tabs.addTab(view, label)
            self.cam_views[cam_id] = view

        self.room_map.set_room_size(profile.width_m, profile.height_m)
        self.room_map.set_zones(profile.zones)
        self.room_map.set_cameras(profile.cameras)
        self.main_room_btn.setText(profile.name)
        self._refresh_room_map_selector()

    def _on_dewarp_toggled(self, checked: bool):
        self.detection_worker.dewarp_enabled = checked

    @staticmethod
    def _one_detection_per_label(merged: list) -> list:
        """Collapse a cycle's detections down to the best-scoring one per
        label.

        Only one row per (label, room) can be active at a time - see
        Database.deactivate_other_positions - so two detections of the same
        label reaching the database individually cannot both be stored. What
        happened instead was that each one failed to find the other's row,
        inserted its own, wrote a snapshot, and deactivated its rival, over
        and over at the detection frame rate. Picking a winner here settles
        that in memory rather than letting the two fight on disk.

        The one-instance-per-label limit is the existing data model, not
        something introduced here: telling two objects of the same class
        apart needs real tracking IDs, which the detector doesn't produce.
        """
        best: dict = {}
        for det in merged:
            key = det["label"].lower()
            if key not in best or det["confidence"] > best[key]["confidence"]:
                best[key] = det
        return list(best.values())

    @staticmethod
    def _delete_snapshots(paths) -> None:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                # Already gone, or held open by a viewer - the row's
                # reference to it has been cleared either way.
                pass

    def _on_detection_cycle_done(self, results: list, total_detections: int):
        """Runs on the GUI thread (queued signal from the detection worker
        thread) - this is where DB writes and status text updates happen,
        since sqlite connections and widgets aren't thread-safe to touch
        from the worker."""
        for profile_id, merged, frames_by_cam in results:
            mapper = self.room_mappers.get(profile_id)
            if mapper is None:
                continue

            # Re-anchor this room's camera->room mapping before computing
            # positions this cycle, using whichever detections match
            # furniture already placed on the room map.
            mapper.calibrate_from_items(merged)

            for det in self._one_detection_per_label(merged):
                room_x, room_y = mapper.pixel_to_room(
                    det["zone_x"], det["zone_y"], det["camera_id"]
                )
                zone_name = mapper.get_zone_name(room_x, room_y)

                existing = self.db.find_active_item(det["label"], profile_id)

                if existing:
                    bbox = (det["bbox_x1"], det["bbox_y1"], det["bbox_x2"], det["bbox_y2"])
                    self.db.update_item_position(
                        existing["id"], det["zone_x"], det["zone_y"],
                        det["confidence"], zone_name, bbox=bbox,
                        camera_id=det["camera_id"],
                    )
                    self.db.deactivate_other_positions(det["label"], profile_id, existing["id"])
                else:
                    # Only a genuinely new sighting is worth the disk write. An
                    # already-tracked item takes the update branch above, which
                    # leaves its existing snapshot in place.
                    snapshot_path = None
                    cam_frame = frames_by_cam.get(det["camera_id"])
                    if cam_frame is not None:
                        snapshot_path = self.detector.save_snapshot(
                            cam_frame, det["bbox_y1"], det["bbox_y2"],
                            det["bbox_x1"], det["bbox_x2"], det["label"], det["camera_id"]
                        )
                    if snapshot_path is not None:
                        # Now that a replacement exists, drop the images from
                        # this object's earlier sightings - deleted only after
                        # the new one is safely written, so a failed capture
                        # never leaves the item with no snapshot at all.
                        self._delete_snapshots(
                            self.db.take_previous_snapshots(det["label"], profile_id)
                        )
                    item = DetectedItem(
                        label=det["label"],
                        confidence=det["confidence"],
                        camera_id=det["camera_id"],
                        zone_x=det["zone_x"],
                        zone_y=det["zone_y"],
                        bbox_x1=det["bbox_x1"],
                        bbox_y1=det["bbox_y1"],
                        bbox_x2=det["bbox_x2"],
                        bbox_y2=det["bbox_y2"],
                        snapshot_path=snapshot_path,
                        zone_name=zone_name,
                        room_id=profile_id,
                    )
                    new_id = self.db.insert_item(item)
                    self.db.deactivate_other_positions(det["label"], profile_id, new_id)

        self.statusBar().showMessage(
            f"Detected {total_detections} objects across {len(self.room_profiles)} room(s)"
        )
        self._update_tracked_highlight()

    def _display_cycle(self):
        cams = self.room_cameras.get(self.active_room_id, {})
        dewarpers = self.room_dewarpers.get(self.active_room_id, {})

        for cam_id, cam in cams.items():
            frame = cam.get_frame()
            if frame is None:
                continue

            if self.dewarp_check.isChecked() and cam_id in dewarpers:
                frame = dewarpers[cam_id].dewarp(frame)

            view = self.cam_views.get(cam_id)
            if view is not None:
                view.update_frame(frame)

        self._display_camera_settings_previews()

    def _display_camera_settings_previews(self):
        """Feed live frames into the Cameras tab's grid thumbnails / detail
        preview - it tracks its own "which room am I editing" state
        (independent of the displayed room above), so it's kept live here
        rather than folding it into the loop over the active display room."""
        if not self.camera_settings_panel.isVisible():
            return

        panel = self.camera_settings_panel
        cams = self.room_cameras.get(panel.active_profile_id, {})
        dewarpers = self.room_dewarpers.get(panel.active_profile_id, {})

        for cam_id, view in panel.live_views.items():
            cam = cams.get(cam_id)
            if cam is None:
                continue
            frame = cam.get_frame()
            if frame is None:
                continue
            if cam_id in dewarpers:
                frame = dewarpers[cam_id].dewarp(frame)
            view.update_frame(frame)

    def _cleanup_cycle(self):
        self.db.deactivate_old_items(ITEM_INACTIVE_SECONDS)

    def _refresh_display(self):
        active_room_items = self.db.get_active_items(room_id=self.active_room_id)
        mapper = self.room_mappers.get(self.active_room_id)

        map_items = []
        if mapper is not None:
            for item in active_room_items:
                room_x, room_y = mapper.pixel_to_room(
                    item["zone_x"], item["zone_y"], item["camera_id"]
                )
                map_items.append({
                    **item,
                    "room_x": room_x,
                    "room_y": room_y,
                })
        self.room_map.update_items(map_items)

        all_active_items = self.db.get_active_items()
        self.search_panel.show_all_items(all_active_items)
        self.status_indicator.setText(
            f"Tracking {len(all_active_items)} item(s) across {len(self.room_profiles)} room(s)"
        )

    def _on_item_selected(self, item: dict):
        room_id = item.get("room_id")
        if room_id is not None:
            self._switch_display_room(room_id)

        cam_id = item.get("camera_id")
        view = self.cam_views.get(cam_id)
        if view is None:
            return

        tab_index = self.cam_tabs.indexOf(view)
        if tab_index != -1:
            self.cam_tabs.setCurrentIndex(tab_index)

        if self._tracked_view is not None and self._tracked_view is not view:
            self._tracked_view.clear_highlight()

        bbox = (
            item.get("bbox_x1"), item.get("bbox_y1"),
            item.get("bbox_x2"), item.get("bbox_y2"),
        )
        if None not in bbox:
            view.set_highlight(bbox, item.get("label"), persistent=True)
            self._tracked_item_id = item.get("id")
            self._tracked_view = view

    def _update_tracked_highlight(self):
        """Keeps the highlight on a selected item following it live as new
        detection cycles come in - including handing off to a different
        camera's tab if it walks into another camera's view. Once it's no
        longer active (moved out of every camera's view, or picked up),
        stop chasing it but deliberately leave the box drawn at wherever it
        was last seen instead of clearing it."""
        if self._tracked_item_id is None:
            return

        item = self.db.get_item(self._tracked_item_id)
        if item is None or not item.get("is_active") or item.get("room_id") != self.active_room_id:
            self._tracked_item_id = None
            return

        bbox = (item.get("bbox_x1"), item.get("bbox_y1"), item.get("bbox_x2"), item.get("bbox_y2"))
        if None in bbox:
            return

        view = self.cam_views.get(item.get("camera_id"))
        if view is None:
            return

        if view is not self._tracked_view:
            if self._tracked_view is not None:
                self._tracked_view.clear_highlight()
            tab_index = self.cam_tabs.indexOf(view)
            if tab_index != -1:
                self.cam_tabs.setCurrentIndex(tab_index)
            self._tracked_view = view

        view.set_highlight(bbox, item.get("label"), persistent=True)

    def _restore_room_tracker_layout(self, tracker: QMainWindow):
        state_b64 = self.app_settings.room_tracker_layout
        if not state_b64:
            return
        try:
            state = QByteArray.fromBase64(state_b64.encode())
            tracker.restoreState(state)
        except Exception:
            pass

    def _save_room_tracker_layout(self):
        state = self.room_widget.saveState()
        self.app_settings.room_tracker_layout = bytes(state.toBase64()).decode()
        save_app_settings(self.app_settings)

    def closeEvent(self, event):
        self._save_room_tracker_layout()
        self.room_setup_panel.save_layout()
        self._detection_thread.quit()
        self._detection_thread.wait(2000)
        for cams in self.room_cameras.values():
            for cam in cams.values():
                cam.stop()
        self.db.close()
        event.accept()
