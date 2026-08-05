from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QTabWidget,
    QPushButton, QMenu, QDockWidget
)
from PyQt5.QtCore import Qt, QTimer, QByteArray, QEvent
from PyQt5.QtGui import QFont

WINDOW_BTN_STYLE = """
    QPushButton {
        background: transparent; color: #999; border: none;
        font-size: 13px; font-weight: bold;
    }
    QPushButton:hover { background-color: #2a2a3e; color: #e0e0e0; }
"""

WINDOW_CLOSE_BTN_STYLE = """
    QPushButton {
        background: transparent; color: #999; border: none;
        font-size: 13px; font-weight: bold;
    }
    QPushButton:hover { background-color: #e53935; color: white; }
"""


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
from found_it.gui.camera_view import CameraView
from found_it.gui.room_map import RoomMap
from found_it.gui.search_panel import SearchPanel
from found_it.gui.file_search_panel import FileSearchPanel
from found_it.gui.device_search_panel import DeviceSearchPanel
from found_it.gui.room_setup_panel import RoomSetupPanel
from found_it.gui.settings_panel import SettingsPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Found It")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self.room_profiles = load_room_profiles()
        self.app_settings = load_app_settings()
        self.active_room_id = self._resolve_active_room_id()
        self.db = Database()
        self.detector = ItemDetector()
        self.room_mappers = {}
        self.room_cameras = {}
        self.room_dewarpers = {}
        self.cam_views = {}
        self._frame_count = 0

        self._setup_ui()
        self._setup_timers()
        self._start_all_room_cameras()

    def _get_profile(self, room_id):
        return next((p for p in self.room_profiles if p.id == room_id), None)

    def _resolve_active_room_id(self) -> str:
        if any(p.id == self.app_settings.active_room_id for p in self.room_profiles):
            return self.app_settings.active_room_id
        return self.room_profiles[0].id

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        nav_bar = TitleBar()
        nav_bar.setFixedHeight(48)
        nav_bar.setStyleSheet("background-color: #0d0d1a; border-bottom: 1px solid #222;")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(12, 0, 0, 0)

        app_title = QLabel("Found It")
        app_title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        app_title.setStyleSheet("color: #6c63ff;")
        nav_layout.addWidget(app_title)

        nav_layout.addSpacing(24)

        self.mode_room_btn = QPushButton("Room Tracker")
        self.mode_room_btn.setCheckable(True)
        self.mode_room_btn.setChecked(True)
        self.mode_room_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888; border: none;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:checked { background-color: #2a2a3e; color: #e0e0e0; }
            QPushButton:hover { color: #ccc; }
        """)
        self.mode_room_btn.clicked.connect(lambda: self._switch_mode("room"))
        nav_layout.addWidget(self.mode_room_btn)

        self.mode_room_setup_btn = QPushButton("Room Setup")
        self.mode_room_setup_btn.setCheckable(True)
        self.mode_room_setup_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888; border: none;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:checked { background-color: #2a2a3e; color: #e0e0e0; }
            QPushButton:hover { color: #ccc; }
        """)
        self.mode_room_setup_btn.clicked.connect(lambda: self._switch_mode("room_setup"))
        nav_layout.addWidget(self.mode_room_setup_btn)

        self.mode_file_btn = QPushButton("File Search")
        self.mode_file_btn.setCheckable(True)
        self.mode_file_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888; border: none;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:checked { background-color: #2a2a3e; color: #e0e0e0; }
            QPushButton:hover { color: #ccc; }
        """)
        self.mode_file_btn.clicked.connect(lambda: self._switch_mode("file"))
        nav_layout.addWidget(self.mode_file_btn)

        self.mode_device_btn = QPushButton("Other Devices")
        self.mode_device_btn.setCheckable(True)
        self.mode_device_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888; border: none;
                padding: 8px 20px; font-size: 13px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:checked { background-color: #2a2a3e; color: #e0e0e0; }
            QPushButton:hover { color: #ccc; }
        """)
        self.mode_device_btn.clicked.connect(lambda: self._switch_mode("device"))
        nav_layout.addWidget(self.mode_device_btn)

        nav_layout.addStretch()

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFixedWidth(36)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888; border: none;
                padding: 8px; font-size: 16px; font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:checked { background-color: #2a2a3e; color: #e0e0e0; }
            QPushButton:hover { color: #ccc; }
        """)
        self.settings_btn.clicked.connect(lambda: self._switch_mode("settings"))
        nav_layout.addWidget(self.settings_btn)

        nav_layout.addSpacing(12)

        self.minimize_btn = QPushButton("─")
        self.minimize_btn.setFixedSize(44, 48)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.setStyleSheet(WINDOW_BTN_STYLE)
        self.minimize_btn.clicked.connect(self.showMinimized)
        nav_layout.addWidget(self.minimize_btn)

        self.maximize_btn = QPushButton("☐")
        self.maximize_btn.setFixedSize(44, 48)
        self.maximize_btn.setToolTip("Maximize")
        self.maximize_btn.setStyleSheet(WINDOW_BTN_STYLE)
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        nav_layout.addWidget(self.maximize_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(44, 48)
        self.close_btn.setToolTip("Close")
        self.close_btn.setStyleSheet(WINDOW_CLOSE_BTN_STYLE)
        self.close_btn.clicked.connect(self.close)
        nav_layout.addWidget(self.close_btn)

        main_layout.addWidget(nav_bar)

        self.content_stack = QWidget()
        self.content_layout = QVBoxLayout(self.content_stack)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.room_widget = self._build_room_view()
        self.room_setup_panel = RoomSetupPanel()
        self.room_setup_panel.room_updated.connect(self._on_room_updated)
        self.file_search_panel = FileSearchPanel()
        self.device_search_panel = DeviceSearchPanel()
        self.settings_panel = SettingsPanel()
        self.settings_panel.settings_updated.connect(self._on_settings_updated)
        self.settings_panel.connect_device_requested.connect(self._on_connect_saved_device)
        self.settings_panel.rooms_imported.connect(self._on_rooms_imported)

        self.content_layout.addWidget(self.room_widget)
        self.content_layout.addWidget(self.room_setup_panel)
        self.content_layout.addWidget(self.file_search_panel)
        self.content_layout.addWidget(self.device_search_panel)
        self.content_layout.addWidget(self.settings_panel)

        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.settings_panel.hide()

        main_layout.addWidget(self.content_stack)

        self.statusBar().setStyleSheet("color: #666; background: #111;")
        self.statusBar().showMessage("Ready")

        self.setStyleSheet("""
            QMainWindow { background-color: #111122; }
            QSplitter::handle { background-color: #222; }
        """)

    def _build_room_view(self):
        tracker = QMainWindow()
        tracker.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
        )
        tracker.setStyleSheet("""
            QMainWindow::separator { background: #222; width: 4px; height: 4px; }
            QMainWindow::separator:hover { background: #6c63ff; }
            QDockWidget { color: #e0e0e0; font-size: 12px; font-weight: bold; }
            QDockWidget::title { background: #0d0d1a; padding: 6px 8px; border-bottom: 1px solid #222; }
            QMenuBar { background: #0d0d1a; color: #aaa; border-bottom: 1px solid #222; }
            QMenuBar::item { padding: 4px 10px; }
            QMenuBar::item:selected { background: #2a2a3e; color: #e0e0e0; }
            QMenu { background: #1a1a2e; color: #ccc; border: 1px solid #333; }
            QMenu::item:selected { background: #2a2a3e; color: #e0e0e0; }
        """)

        view_menu = tracker.menuBar().addMenu("View")

        # --- Cameras dock: movable, floatable, closable - drag it wherever ---
        camera_widget = QWidget()
        camera_layout = QVBoxLayout(camera_widget)
        camera_layout.setContentsMargins(8, 8, 8, 8)

        controls = QHBoxLayout()
        self.dewarp_check = QCheckBox("Dewarp")
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        self.dewarp_check.setStyleSheet("color: #aaa;")
        controls.addWidget(self.dewarp_check)
        controls.addStretch()
        camera_layout.addLayout(controls)

        self.cam_tabs = QTabWidget()
        self.cam_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333; background: #111; }
            QTabBar::tab {
                background: #1a1a2e; color: #888;
                padding: 6px 16px; border: 1px solid #333;
                border-bottom: none; border-radius: 4px 4px 0 0;
            }
            QTabBar::tab:selected { background: #2a2a3e; color: #e0e0e0; }
        """)

        active_profile = self._get_profile(self.active_room_id)
        self.main_room_btn = QPushButton(active_profile.name)
        self.main_room_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a3e; color: #e0e0e0;
                border: 1px solid #444; border-radius: 4px;
                padding: 4px 12px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #3a3a5e; }
            QPushButton::menu-indicator { width: 0px; }
        """)
        self.main_room_btn.clicked.connect(self._show_room_menu)
        self.cam_tabs.setCornerWidget(self.main_room_btn, Qt.TopRightCorner)
        camera_layout.addWidget(self.cam_tabs)

        self.camera_dock = QDockWidget("Cameras", tracker)
        self.camera_dock.setObjectName("camera_dock")
        self.camera_dock.setWidget(camera_widget)
        self.camera_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        tracker.addDockWidget(Qt.LeftDockWidgetArea, self.camera_dock)
        view_menu.addAction(self.camera_dock.toggleViewAction())

        # --- Found Items dock: movable, floatable, closable ---
        self.search_panel = SearchPanel()
        self.search_panel.item_selected.connect(self._on_item_selected)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})

        self.found_items_dock = QDockWidget("Found Items", tracker)
        self.found_items_dock.setObjectName("found_items_dock")
        self.found_items_dock.setWidget(self.search_panel)
        self.found_items_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        tracker.addDockWidget(Qt.RightDockWidgetArea, self.found_items_dock)
        view_menu.addAction(self.found_items_dock.toggleViewAction())

        # --- Room Map: fixed central area ---
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(4, 8, 4, 8)

        map_header = QHBoxLayout()
        map_title = QLabel("Room Map")
        map_title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        map_title.setStyleSheet("color: #e0e0e0;")
        map_header.addWidget(map_title)
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

        self._restore_room_tracker_layout(tracker)

        return tracker

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange and hasattr(self, "maximize_btn"):
            self.maximize_btn.setText("❐" if self.isMaximized() else "☐")
            self.maximize_btn.setToolTip("Restore" if self.isMaximized() else "Maximize")
        super().changeEvent(event)

    def _switch_mode(self, mode):
        self.room_widget.hide()
        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.settings_panel.hide()
        self.mode_room_btn.setChecked(False)
        self.mode_room_setup_btn.setChecked(False)
        self.mode_file_btn.setChecked(False)
        self.mode_device_btn.setChecked(False)
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
        elif mode == "settings":
            self.settings_panel.show()
            self.settings_btn.setChecked(True)

    def _show_room_menu(self):
        menu = QMenu(self)
        for profile in self.room_profiles:
            action = menu.addAction(profile.name)
            action.setCheckable(True)
            action.setChecked(profile.id == self.active_room_id)
            action.triggered.connect(lambda checked, rid=profile.id: self._switch_display_room(rid))
        menu.exec_(self.main_room_btn.mapToGlobal(self.main_room_btn.rect().bottomLeft()))

    def _switch_display_room(self, room_id: str):
        if room_id == self.active_room_id or self._get_profile(room_id) is None:
            return
        self.active_room_id = room_id
        self.app_settings.active_room_id = room_id
        save_app_settings(self.app_settings)
        self._refresh_display_room_ui()

    def _on_settings_updated(self):
        self.app_settings = load_app_settings()
        self.dewarp_check.setChecked(self.app_settings.dewarp_default)
        self._start_all_room_cameras()

    def _on_connect_saved_device(self, serial: str):
        self._switch_mode("device")
        self.device_search_panel.connect_saved_device(serial)

    def _on_room_updated(self):
        self.room_profiles = load_room_profiles()
        if self._get_profile(self.active_room_id) is None:
            self.active_room_id = self.room_profiles[0].id
            self.app_settings.active_room_id = self.active_room_id
            save_app_settings(self.app_settings)
        self.search_panel.set_room_names({p.id: p.name for p in self.room_profiles})
        self._start_all_room_cameras()

    def _on_rooms_imported(self):
        self._on_room_updated()
        self.room_setup_panel.reload_profiles()

    def _setup_timers(self):
        self._detect_timer = QTimer()
        self._detect_timer.timeout.connect(self._detection_cycle)
        self._detect_timer.start(100)

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

        self.room_cameras = {}
        self.room_dewarpers = {}
        self.room_mappers = {}
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
                elif self.app_settings.dewarp_default:
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
            view = CameraView(cam_id)
            self.cam_tabs.addTab(view, label)
            self.cam_views[cam_id] = view

        self.room_map.set_room_size(profile.width_m, profile.height_m)
        self.room_map.set_zones(profile.zones)
        self.room_map.set_cameras(profile.cameras)
        self.main_room_btn.setText(profile.name)

    def _detection_cycle(self):
        self._frame_count += 1
        if self._frame_count % self.app_settings.detection_frame_skip != 0:
            return

        total_detections = 0

        for profile in self.room_profiles:
            cams = self.room_cameras.get(profile.id, {})
            if not cams:
                continue
            dewarpers = self.room_dewarpers.get(profile.id, {})
            mapper = self.room_mappers.get(profile.id)
            if mapper is None:
                continue

            all_detections_per_cam = []
            for cam_id, cam in cams.items():
                frame = cam.get_frame()
                if frame is None:
                    continue

                if self.dewarp_check.isChecked() and cam_id in dewarpers:
                    frame = dewarpers[cam_id].dewarp(frame)

                detections = self.detector.detect(frame, cam_id, confidence=self.app_settings.detection_confidence)
                all_detections_per_cam.append(detections)

            merged = mapper.merge_detections(all_detections_per_cam)
            total_detections += len(merged)

            for det in merged:
                room_x, room_y = mapper.pixel_to_room(
                    det["zone_x"], det["zone_y"], det["camera_id"]
                )
                zone_name = mapper.get_zone_name(room_x, room_y)

                existing = self.db.find_matching_item(
                    det["label"], det["camera_id"],
                    det["zone_x"], det["zone_y"], profile.id
                )

                if existing:
                    self.db.update_item_position(
                        existing["id"], det["zone_x"], det["zone_y"],
                        det["confidence"], zone_name
                    )
                else:
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
                        snapshot_path=det.get("snapshot_path"),
                        zone_name=zone_name,
                        room_id=profile.id,
                    )
                    self.db.insert_item(item)

        self.statusBar().showMessage(
            f"Detected {total_detections} objects across {len(self.room_profiles)} room(s)"
        )

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
        if item.get("room_id") == self.active_room_id:
            self.room_map.select_item(item.get("id"))

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
        for cams in self.room_cameras.values():
            for cam in cams.values():
                cam.stop()
        self.db.close()
        event.accept()
