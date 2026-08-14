from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton,
    QComboBox, QLineEdit, QListWidget, QListWidgetItem, QMenu
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.room_profiles import load_room_profiles, save_room_profiles
from found_it.storage.models import RoomConfig
from found_it.camera.capture import CameraDiscovery
from found_it.utils.themes import get_palette, widget_qss, repolish


class CameraSettingsPanel(QWidget):
    # Emitted whenever a camera is added/renamed/toggled/removed and saved,
    # or the detection settings are saved - main_window uses this to refresh
    # everything else that reads room profiles / app settings (Room Setup's
    # own in-memory copy included, since these two panels edit the same
    # on-disk cameras independently).
    settings_updated = pyqtSignal()

    # Emitted from the background scan thread - queued automatically onto
    # this widget's own (GUI) thread since the connected slot below lives
    # here, so it's safe to pop up a QMenu from it even though the scan
    # itself runs elsewhere.
    _camera_discovery_progress = pyqtSignal(str)
    _camera_discovery_finished = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_settings = load_app_settings()
        self.profiles: List[RoomConfig] = load_room_profiles()
        self._active_profile_index = 0
        self.cameras: List[dict] = [dict(c) for c in self.profiles[0].cameras]
        self._selected_camera_index: Optional[int] = None
        self._updating_camera_list = False
        self.palette = get_palette("Indigo")
        self._camera_discovery = CameraDiscovery()
        self._camera_discovery_progress.connect(self._on_camera_discovery_progress)
        self._camera_discovery_finished.connect(self._on_camera_discovery_finished)
        self._setup_ui()
        self._refresh_profile_list()
        self._refresh_camera_list()
        self.apply_theme(self.palette)

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.setStyleSheet(widget_qss(palette))
        repolish(self)

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("cls", "muted")
        return lbl

    def _active_profile(self) -> RoomConfig:
        return self.profiles[self._active_profile_index]

    def reload_profiles(self):
        """Re-read room profiles from disk - for camera position/removal
        changes made on the Room Setup canvas, or room profiles added/
        renamed/deleted there, so this panel doesn't keep editing a stale
        in-memory copy and clobber those changes on next Save."""
        self.profiles = load_room_profiles()
        if self._active_profile_index >= len(self.profiles):
            self._active_profile_index = 0
        self.cameras = [dict(c) for c in self._active_profile().cameras]
        self._selected_camera_index = None
        self.camera_rename_input.clear()
        self._refresh_profile_list()
        self._refresh_camera_list()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Cameras")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        desc = QLabel(
            "Add, discover, rename, enable/disable, or remove cameras below. Once a "
            "camera's added, switch to the Room Setup tab and drag its marker into "
            "place on the room."
        )
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        profile_row.addWidget(self._label("Editing Room"))
        self.profile_selector = QComboBox()
        self.profile_selector.currentIndexChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_selector, 1)
        layout.addLayout(profile_row)

        profile_hint = QLabel(
            "Every saved room tracks its own cameras, so each room needs cameras with "
            "their own distinct IDs. Rooms themselves are created/renamed from the "
            "Room Setup tab."
        )
        profile_hint.setProperty("cls", "hint")
        profile_hint.setWordWrap(True)
        layout.addWidget(profile_hint)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("cls", "sep")
        layout.addWidget(sep)

        camera_add_row = QHBoxLayout()
        camera_add_row.setSpacing(8)
        self.camera_id_input = QSpinBox()
        self.camera_id_input.setRange(0, 9)
        self.camera_id_input.setPrefix("ID ")
        camera_add_row.addWidget(self.camera_id_input)

        self.camera_label_input = QLineEdit()
        self.camera_label_input.setPlaceholderText("e.g. Desk Cam")
        camera_add_row.addWidget(self.camera_label_input)

        self.add_camera_btn = QPushButton("Add Camera")
        self.add_camera_btn.setProperty("cls", "secondary")
        self.add_camera_btn.clicked.connect(self._on_add_camera)
        camera_add_row.addWidget(self.add_camera_btn)
        layout.addLayout(camera_add_row)

        discover_row = QHBoxLayout()
        discover_row.setSpacing(8)
        self.discover_cameras_btn = QPushButton("Discover Cameras")
        self.discover_cameras_btn.setProperty("cls", "secondary")
        self.discover_cameras_btn.clicked.connect(self._on_discover_cameras)
        discover_row.addWidget(self.discover_cameras_btn)
        layout.addLayout(discover_row)

        discover_hint = QLabel("Scans this PC for cameras that aren't in the list yet, so you don't have "
                                "to guess an ID. Already-added or currently in-use cameras are skipped.")
        discover_hint.setProperty("cls", "hint")
        discover_hint.setWordWrap(True)
        layout.addWidget(discover_hint)

        self.camera_list = QListWidget()
        self.camera_list.setMinimumHeight(100)
        self.camera_list.itemClicked.connect(self._on_camera_list_clicked)
        self.camera_list.itemChanged.connect(self._on_camera_item_changed)
        layout.addWidget(self.camera_list)

        camera_edit_row = QHBoxLayout()
        camera_edit_row.setSpacing(8)
        self.camera_rename_input = QLineEdit()
        self.camera_rename_input.setPlaceholderText("Rename selected camera")
        camera_edit_row.addWidget(self.camera_rename_input)

        self.rename_camera_btn = QPushButton("Rename")
        self.rename_camera_btn.setProperty("cls", "primary")
        self.rename_camera_btn.clicked.connect(self._on_rename_camera)
        camera_edit_row.addWidget(self.rename_camera_btn)
        layout.addLayout(camera_edit_row)

        camera_action_row = QHBoxLayout()
        camera_action_row.setSpacing(8)
        self.toggle_360_btn = QPushButton("Toggle 360°")
        self.toggle_360_btn.setProperty("cls", "secondary")
        self.toggle_360_btn.clicked.connect(self._on_toggle_360)
        camera_action_row.addWidget(self.toggle_360_btn)

        self.remove_camera_btn = QPushButton("Remove")
        self.remove_camera_btn.setProperty("cls", "secondary")
        self.remove_camera_btn.clicked.connect(self._on_remove_camera)
        camera_action_row.addWidget(self.remove_camera_btn)
        layout.addLayout(camera_action_row)

        self.camera_status_label = QLabel("")
        self.camera_status_label.setProperty("cls", "status")
        layout.addWidget(self.camera_status_label)

        save_cameras_btn = QPushButton("💾 Save Cameras")
        save_cameras_btn.setProperty("cls", "primary")
        save_cameras_btn.clicked.connect(self._on_save_cameras)
        layout.addWidget(save_cameras_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setProperty("cls", "sep")
        layout.addWidget(sep2)

        layout.addWidget(self._page_title("Detection"))
        detection_desc = QLabel("Tune how detection runs across your cameras.")
        detection_desc.setProperty("cls", "muted")
        detection_desc.setWordWrap(True)
        layout.addWidget(detection_desc)

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

        self.detection_status_label = QLabel("")
        self.detection_status_label.setProperty("cls", "status")
        layout.addWidget(self.detection_status_label)

        save_detection_btn = QPushButton("💾 Save Detection Settings")
        save_detection_btn.setProperty("cls", "primary")
        save_detection_btn.clicked.connect(self._on_save_detection_settings)
        layout.addWidget(save_detection_btn)

    def _page_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl.setProperty("cls", "title")
        return lbl

    # ---------------- Room profile selection ----------------

    def _refresh_profile_list(self):
        self.profile_selector.blockSignals(True)
        self.profile_selector.clear()
        for profile in self.profiles:
            self.profile_selector.addItem(profile.name)
        self.profile_selector.setCurrentIndex(self._active_profile_index)
        self.profile_selector.blockSignals(False)

    def _on_profile_selected(self, index: int):
        if index < 0 or index >= len(self.profiles):
            return
        self._active_profile_index = index
        self.cameras = [dict(c) for c in self._active_profile().cameras]
        self._selected_camera_index = None
        self.camera_rename_input.clear()
        self._refresh_camera_list()
        self.camera_status_label.setText(f"Editing \"{self._active_profile().name}\".")

    # ---------------- Camera list ----------------

    def _refresh_camera_list(self):
        self._updating_camera_list = True
        self.camera_list.clear()
        for i, cam in enumerate(self.cameras):
            tag = ", 360°" if cam.get("is_360") else ""
            text = f"{cam['label']}  (id {cam['id']}{tag})"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if cam.get("enabled") else Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.camera_list.addItem(item)
        self._updating_camera_list = False

    def _add_camera(self, cam_id: int, label: str = ""):
        if any(c["id"] == cam_id for c in self.cameras):
            self.camera_status_label.setText(f"Camera ID {cam_id} is already in the list.")
            return
        label = label.strip() or f"Camera {cam_id}"
        profile = self._active_profile()
        self.cameras.append({
            "id": cam_id,
            "label": label,
            "enabled": True,
            "x": profile.width_m / 2.0,
            "y": profile.height_m / 2.0,
            "is_360": False,
        })
        self._refresh_camera_list()
        self.camera_status_label.setText(
            f"Added \"{label}\". Save, then drag it into place from the Room Setup tab."
        )

    def _on_add_camera(self):
        self._add_camera(self.camera_id_input.value(), self.camera_label_input.text())
        self.camera_label_input.clear()

    def _on_discover_cameras(self):
        if self._camera_discovery.is_scanning():
            return
        self.discover_cameras_btn.setEnabled(False)
        self.camera_status_label.setText("Scanning for cameras...")
        exclude_ids = {c["id"] for c in self.cameras}
        self._camera_discovery.start_scan(
            max_index=10, exclude_ids=exclude_ids,
            progress_callback=self._camera_discovery_progress.emit,
            done_callback=self._camera_discovery_finished.emit,
        )

    def _on_camera_discovery_progress(self, message: str):
        self.camera_status_label.setText(message)

    def _on_camera_discovery_finished(self, found: list):
        self.discover_cameras_btn.setEnabled(True)
        if not found:
            self.camera_status_label.setText(
                "No additional cameras found. Already-added or in-use IDs are skipped."
            )
            return

        menu = QMenu(self)
        for info in found:
            action = menu.addAction(f"Camera {info['id']} ({info['width']}x{info['height']})")
            action.triggered.connect(lambda checked, cid=info["id"]: self._add_camera(cid))
        self.camera_status_label.setText(f"Found {len(found)} camera(s) - pick one to add.")
        menu.exec_(self.discover_cameras_btn.mapToGlobal(self.discover_cameras_btn.rect().bottomLeft()))

    def _on_camera_list_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        self._selected_camera_index = index
        self.camera_rename_input.setText(self.cameras[index]["label"])

    def _on_camera_item_changed(self, item: QListWidgetItem):
        if self._updating_camera_list:
            return
        index = item.data(Qt.UserRole)
        if index is None:
            return
        self.cameras[index]["enabled"] = item.checkState() == Qt.Checked
        self.camera_status_label.setText("Don't forget to Save Cameras.")

    def _on_rename_camera(self):
        if self._selected_camera_index is None:
            self.camera_status_label.setText("Select a camera to rename first.")
            return
        new_label = self.camera_rename_input.text().strip()
        if not new_label:
            return
        self.cameras[self._selected_camera_index]["label"] = new_label
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(self._selected_camera_index)
        self.camera_status_label.setText(f"Renamed camera to \"{new_label}\". Don't forget to Save Cameras.")

    def _on_toggle_360(self):
        if self._selected_camera_index is None:
            self.camera_status_label.setText("Select a camera first.")
            return
        cam = self.cameras[self._selected_camera_index]
        cam["is_360"] = not cam.get("is_360", False)
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(self._selected_camera_index)
        state = "a 360°" if cam["is_360"] else "a standard"
        self.camera_status_label.setText(f"\"{cam['label']}\" is now {state} camera. Don't forget to Save Cameras.")

    def _on_remove_camera(self):
        if self._selected_camera_index is None:
            self.camera_status_label.setText("Select a camera to remove first.")
            return
        removed = self.cameras.pop(self._selected_camera_index)
        self._selected_camera_index = None
        self.camera_rename_input.clear()
        self._refresh_camera_list()
        self.camera_status_label.setText(f"Removed \"{removed['label']}\". Don't forget to Save Cameras.")

    def _on_save_cameras(self):
        profile = self._active_profile()
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)
        self.camera_status_label.setText(f"Saved cameras for \"{profile.name}\".")
        self.settings_updated.emit()

    # ---------------- Detection settings ----------------

    def _on_save_detection_settings(self):
        self.app_settings.detection_confidence = self.confidence_input.value()
        self.app_settings.detection_frame_skip = self.frame_skip_input.value()
        self.app_settings.dewarp_default = self.dewarp_default_check.isChecked()
        save_app_settings(self.app_settings)
        self.detection_status_label.setText("Saved. Applies immediately.")
        self.settings_updated.emit()
