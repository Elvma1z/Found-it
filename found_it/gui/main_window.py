from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QSplitter, QTabWidget,
    QPushButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from found_it.config import DETECTION_FRAME_SKIP, DEWARP_ENABLED, ITEM_INACTIVE_SECONDS
from found_it.camera.capture import CameraCapture
from found_it.camera.dewarp import FisheyeDewarp, EquirectangularDewarp
from found_it.detection.detector import ItemDetector
from found_it.detection.item_mapper import ItemMapper
from found_it.storage.database import Database
from found_it.storage.models import DetectedItem, RoomConfig
from found_it.utils.room_config import load_room_config
from found_it.gui.camera_view import CameraView
from found_it.gui.room_map import RoomMap
from found_it.gui.search_panel import SearchPanel
from found_it.gui.file_search_panel import FileSearchPanel
from found_it.gui.device_search_panel import DeviceSearchPanel
from found_it.gui.room_setup_panel import RoomSetupPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Found It")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 800)

        self.room_config = load_room_config()
        self.db = Database()
        self.detector = ItemDetector()
        self.mapper = ItemMapper(self.room_config)
        self.cameras = {}
        self.dewarpers = {}
        self.cam_views = {}
        self._frame_count = 0

        self._setup_ui()
        self._setup_timers()
        self._apply_camera_config()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        nav_bar = QWidget()
        nav_bar.setFixedHeight(48)
        nav_bar.setStyleSheet("background-color: #0d0d1a; border-bottom: 1px solid #222;")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(12, 0, 12, 0)

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

        self.content_layout.addWidget(self.room_widget)
        self.content_layout.addWidget(self.room_setup_panel)
        self.content_layout.addWidget(self.file_search_panel)
        self.content_layout.addWidget(self.device_search_panel)

        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()

        main_layout.addWidget(self.content_stack)

        self.statusBar().setStyleSheet("color: #666; background: #111;")
        self.statusBar().showMessage("Ready")

        self.setStyleSheet("""
            QMainWindow { background-color: #111122; }
            QSplitter::handle { background-color: #222; }
        """)

    def _build_room_view(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 4, 8)

        controls = QHBoxLayout()
        self.dewarp_check = QCheckBox("Dewarp")
        self.dewarp_check.setChecked(DEWARP_ENABLED)
        self.dewarp_check.setStyleSheet("color: #aaa;")
        controls.addWidget(self.dewarp_check)
        controls.addStretch()
        left_layout.addLayout(controls)

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
        left_layout.addWidget(self.cam_tabs)

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
        self.room_map.set_room_size(self.room_config.width_m, self.room_config.height_m)
        self.room_map.set_zones(self.room_config.zones)
        self.room_map.set_cameras(self.room_config.cameras)
        center_layout.addWidget(self.room_map)

        self.search_panel = SearchPanel()
        self.search_panel.item_selected.connect(self._on_item_selected)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(self.search_panel)
        splitter.setSizes([500, 500, 300])

        layout.addWidget(splitter)
        return widget

    def _switch_mode(self, mode):
        self.room_widget.hide()
        self.room_setup_panel.hide()
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.mode_room_btn.setChecked(False)
        self.mode_room_setup_btn.setChecked(False)
        self.mode_file_btn.setChecked(False)
        self.mode_device_btn.setChecked(False)

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

    def _on_room_updated(self):
        self.room_config = load_room_config()
        self.mapper.room = self.room_config
        self.room_map.set_room_size(self.room_config.width_m, self.room_config.height_m)
        self.room_map.set_zones(self.room_config.zones)
        self._apply_camera_config()

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

    def _apply_camera_config(self):
        for cam in self.cameras.values():
            cam.stop()
        self.cameras = {}
        self.dewarpers = {}
        self.cam_views = {}
        self.cam_tabs.clear()

        for cam_cfg in self.room_config.cameras:
            if not cam_cfg.get("enabled"):
                continue

            cam_id = cam_cfg["id"]
            label = cam_cfg.get("label", f"Camera {cam_id}")

            view = CameraView(cam_id)
            self.cam_tabs.addTab(view, label)
            self.cam_views[cam_id] = view

            cam = CameraCapture(cam_id)
            if not cam.start():
                self.statusBar().showMessage(f"Camera {cam_id} not found")
                continue

            self.cameras[cam_id] = cam
            self.statusBar().showMessage(f"Camera {cam_id} connected")

            if cam_cfg.get("is_360"):
                self.dewarpers[cam_id] = EquirectangularDewarp(fov=90.0, num_views=4)
            elif DEWARP_ENABLED:
                dewarper = FisheyeDewarp(cam_id)
                frame = cam.get_frame()
                if frame is not None:
                    h, w = frame.shape[:2]
                    dewarper.load_calibration((w, h))
                self.dewarpers[cam_id] = dewarper

        self.room_map.set_cameras(self.room_config.cameras)

    def _detection_cycle(self):
        self._frame_count += 1
        if self._frame_count % DETECTION_FRAME_SKIP != 0:
            return

        all_detections_per_cam = []

        for cam_id, cam in self.cameras.items():
            frame = cam.get_frame()
            if frame is None:
                continue

            if self.dewarp_check.isChecked() and cam_id in self.dewarpers:
                frame = self.dewarpers[cam_id].dewarp(frame)

            detections = self.detector.detect(frame, cam_id)
            all_detections_per_cam.append(detections)

        merged = self.mapper.merge_detections(all_detections_per_cam)

        for det in merged:
            existing = self.db.find_matching_item(
                det["label"], det["camera_id"],
                det["zone_x"], det["zone_y"]
            )

            if existing:
                self.db.update_item_position(
                    existing["id"], det["zone_x"], det["zone_y"],
                    det["confidence"]
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
                )
                self.db.insert_item(item)

        self.statusBar().showMessage(
            f"Detected {len(merged)} objects"
        )

    def _display_cycle(self):
        for cam_id, cam in self.cameras.items():
            frame = cam.get_frame()
            if frame is None:
                continue

            if self.dewarp_check.isChecked() and cam_id in self.dewarpers:
                frame = self.dewarpers[cam_id].dewarp(frame)

            view = self.cam_views.get(cam_id)
            if view is not None:
                view.update_frame(frame)

    def _cleanup_cycle(self):
        self.db.deactivate_old_items(ITEM_INACTIVE_SECONDS)

    def _refresh_display(self):
        active = self.db.get_active_items()

        map_items = []
        for item in active:
            room_x, room_y = self.mapper.pixel_to_room(
                item["zone_x"], item["zone_y"], item["camera_id"]
            )
            map_items.append({
                **item,
                "room_x": room_x,
                "room_y": room_y,
            })

        self.room_map.update_items(map_items)
        self.search_panel.show_all_items(active)
        self.status_indicator.setText(f"Tracking {len(active)} items")

    def _on_item_selected(self, item: dict):
        self.room_map.select_item(item.get("id"))

    def closeEvent(self, event):
        for cam in self.cameras.values():
            cam.stop()
        self.db.close()
        event.accept()
