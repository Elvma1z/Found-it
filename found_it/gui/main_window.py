from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QCheckBox, QSplitter, QTabWidget,
    QPushButton, QButtonGroup
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from found_it.config import (
    CAMERA_IDS, CENTER_CAMERA_ENABLED, CENTER_CAMERA_ID,
    DETECTION_FRAME_SKIP, DEWARP_ENABLED, ITEM_INACTIVE_SECONDS
)
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
        self._frame_count = 0

        self._setup_ui()
        self._setup_timers()
        self._start_cameras()

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
        self.file_search_panel = FileSearchPanel()
        self.device_search_panel = DeviceSearchPanel()

        self.content_layout.addWidget(self.room_widget)
        self.content_layout.addWidget(self.file_search_panel)
        self.content_layout.addWidget(self.device_search_panel)

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

        self.center_cam_check = QCheckBox("360 Cam")
        self.center_cam_check.setChecked(CENTER_CAMERA_ENABLED)
        self.center_cam_check.setStyleSheet("color: #aaa;")
        self.center_cam_check.stateChanged.connect(self._on_center_cam_toggle)
        controls.addWidget(self.center_cam_check)
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

        self.cam_view_0 = CameraView(0)
        self.cam_view_1 = CameraView(1)
        self.cam_view_2 = CameraView(2)

        self.cam_tabs.addTab(self.cam_view_0, "Cam 0 (Corner)")
        self.cam_tabs.addTab(self.cam_view_1, "Cam 1 (Corner)")
        self.cam_tabs.addTab(self.cam_view_2, "360 (Center)")

        if CENTER_CAMERA_ENABLED:
            self.cam_tabs.setTabVisible(0, False)
            self.cam_tabs.setTabVisible(1, False)
        else:
            self.cam_tabs.setTabVisible(2, False)

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
        self.room_map.set_center_camera(CENTER_CAMERA_ENABLED)
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
        self.file_search_panel.hide()
        self.device_search_panel.hide()
        self.mode_room_btn.setChecked(False)
        self.mode_file_btn.setChecked(False)
        self.mode_device_btn.setChecked(False)

        if mode == "room":
            self.room_widget.show()
            self.mode_room_btn.setChecked(True)
        elif mode == "file":
            self.file_search_panel.show()
            self.mode_file_btn.setChecked(True)
        elif mode == "device":
            self.device_search_panel.show()
            self.mode_device_btn.setChecked(True)

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

    def _start_cameras(self):
        active_ids = [] if CENTER_CAMERA_ENABLED else list(CAMERA_IDS)
        if CENTER_CAMERA_ENABLED:
            active_ids.append(CENTER_CAMERA_ID)

        for cam_id in active_ids:
            cam = CameraCapture(cam_id)
            if cam.start():
                self.cameras[cam_id] = cam
                self.statusBar().showMessage(f"Camera {cam_id} connected")
            else:
                self.statusBar().showMessage(f"Camera {cam_id} not found")

        if DEWARP_ENABLED:
            for cam_id in CAMERA_IDS:
                if cam_id in self.cameras:
                    dewarper = FisheyeDewarp(cam_id)
                    frame = self.cameras[cam_id].get_frame()
                    if frame is not None:
                        h, w = frame.shape[:2]
                        dewarper.load_calibration((w, h))
                    self.dewarpers[cam_id] = dewarper

        if CENTER_CAMERA_ENABLED and CENTER_CAMERA_ID in self.cameras:
            self.dewarpers[CENTER_CAMERA_ID] = EquirectangularDewarp(
                fov=90.0, num_views=4
            )

    def _on_center_cam_toggle(self, state):
        enabled = state == Qt.Checked
        self.room_map.set_center_camera(enabled)
        self.cam_tabs.setTabVisible(2, enabled)
        self.cam_tabs.setTabVisible(0, not enabled)
        self.cam_tabs.setTabVisible(1, not enabled)

        if enabled and CENTER_CAMERA_ID not in self.cameras:
            cam = CameraCapture(CENTER_CAMERA_ID)
            if cam.start():
                self.cameras[CENTER_CAMERA_ID] = cam
                self.dewarpers[CENTER_CAMERA_ID] = EquirectangularDewarp(
                    fov=90.0, num_views=4
                )
        elif not enabled and CENTER_CAMERA_ID in self.cameras:
            self.cameras[CENTER_CAMERA_ID].stop()
            del self.cameras[CENTER_CAMERA_ID]
            if CENTER_CAMERA_ID in self.dewarpers:
                del self.dewarpers[CENTER_CAMERA_ID]

        if enabled:
            for cam_id in CAMERA_IDS:
                if cam_id in self.cameras:
                    self.cameras[cam_id].stop()
                    del self.cameras[cam_id]
                if cam_id in self.dewarpers:
                    del self.dewarpers[cam_id]
        else:
            for cam_id in CAMERA_IDS:
                if cam_id not in self.cameras:
                    cam = CameraCapture(cam_id)
                    if cam.start():
                        self.cameras[cam_id] = cam
                        self.statusBar().showMessage(f"Camera {cam_id} connected")
                        if DEWARP_ENABLED:
                            dewarper = FisheyeDewarp(cam_id)
                            frame = cam.get_frame()
                            if frame is not None:
                                h, w = frame.shape[:2]
                                dewarper.load_calibration((w, h))
                            self.dewarpers[cam_id] = dewarper
                    else:
                        self.statusBar().showMessage(f"Camera {cam_id} not found")

    def _detection_cycle(self):
        self._frame_count += 1
        if self._frame_count % DETECTION_FRAME_SKIP != 0:
            return

        all_detections_per_cam = []

        for cam_id in [0, 1]:
            cam = self.cameras.get(cam_id)
            if cam is None:
                all_detections_per_cam.append([])
                continue

            frame = cam.get_frame()
            if frame is None:
                all_detections_per_cam.append([])
                continue

            if self.dewarp_check.isChecked() and cam_id in self.dewarpers:
                frame = self.dewarpers[cam_id].dewarp(frame)

            detections = self.detector.detect(frame, cam_id)
            all_detections_per_cam.append(detections)

        if CENTER_CAMERA_ENABLED and CENTER_CAMERA_ID in self.cameras:
            cam = self.cameras[CENTER_CAMERA_ID]
            frame = cam.get_frame()
            if frame is not None:
                if self.dewarp_check.isChecked() and CENTER_CAMERA_ID in self.dewarpers:
                    frame = self.dewarpers[CENTER_CAMERA_ID].dewarp(frame)
                detections = self.detector.detect(frame, CENTER_CAMERA_ID)
                all_detections_per_cam.append(detections)
            else:
                all_detections_per_cam.append([])

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
        view_map = {0: self.cam_view_0, 1: self.cam_view_1, 2: self.cam_view_2}

        for cam_id, cam in self.cameras.items():
            frame = cam.get_frame()
            if frame is None:
                continue

            if self.dewarp_check.isChecked() and cam_id in self.dewarpers:
                frame = self.dewarpers[cam_id].dewarp(frame)

            view = view_map.get(cam_id)
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
