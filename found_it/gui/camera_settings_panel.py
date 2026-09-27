from typing import List, Optional, Dict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton,
    QComboBox, QLineEdit, QMenu, QScrollArea, QInputDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.utils.room_profiles import load_room_profiles, save_room_profiles
from found_it.storage.models import RoomConfig
from found_it.camera.capture import CameraDiscovery
from found_it.utils.themes import DEFAULT_THEME, get_palette
from found_it.gui import ds
from found_it.gui.camera_view import CameraView
from found_it.gui.icons import get_icon, get_pixmap, ICON_SIZE
from found_it.gui.help_info import HelpInfoMixin

CAMERA_TYPES = ["Standard", "180°", "360°"]
GRID_COLUMNS = 3  # reference column count TILE_SCALE is measured against
GRID_SPACING = 12
TILE_MARGIN = 10
CAMERA_TILE_ASPECT = 16 / 9  # width:height of the live preview inside a tile
MIN_TILE_VIEW_WIDTH = 160
TILE_SCALE = 0.99  # how much bigger tiles are than "3 fit across the tab"


class CameraTile(QFrame):
    """One cell in the camera grid: a live CameraView plus name, ID/type and
    an On switch. Clicking anywhere except the switch opens that camera's
    settings screen."""

    clicked = pyqtSignal(int)
    enabled_toggled = pyqtSignal(int, bool)

    def __init__(self, index: int, cam: dict, palette: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("cameraTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        # Fixed rather than just a minimum - otherwise the grid stretches
        # tiles (and the video inside) to fill leftover space, which upscales
        # the live feed and makes it look blurry.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(10)

        self.view = CameraView(cam["id"], label=cam.get("label", ""))
        self.view.setFixedSize(280, 120)
        layout.addWidget(self.view)

        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.name_label = ds.text("")
        self.name_label.setStyleSheet("font-weight: 500;")
        col.addWidget(self.name_label)
        self.meta_label = ds.text("", "mono")
        col.addWidget(self.meta_label)
        info_row.addLayout(col, 1)
        self.enabled_check = ds.Switch("On")
        self.enabled_check.stateChanged.connect(
            lambda state: self.enabled_toggled.emit(self.index, state == Qt.Checked)
        )
        info_row.addWidget(self.enabled_check)
        layout.addLayout(info_row)

        self.set_camera(cam)
        ds.on_theme(self, self.apply_theme)

    def set_view_size(self, width: int, height: int):
        self.view.setFixedSize(width, height)
        self.updateGeometry()

    def set_camera(self, cam: dict):
        if cam.get("is_360"):
            tag = "360°"
        elif cam.get("is_180"):
            tag = f"180° · facing {cam.get('facing_deg', 0.0):.0f}°"
        else:
            tag = "Standard"
        self.name_label.setText(cam["label"])
        self.view.label = cam["label"]
        self.meta_label.setText(f"ID {cam['id']} · {tag}")
        self.enabled_check.blockSignals(True)
        self.enabled_check.setChecked(bool(cam.get("enabled")))
        self.enabled_check.blockSignals(False)

    def apply_theme(self, palette: dict):
        p = ds.pal()
        self.setStyleSheet(f"""
            QFrame#cameraTile {{ background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 12px; }}
            QFrame#cameraTile:hover {{ border-color: {p['border_strong']}; background: {p['surface3']}; }}
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class AddCameraTile(QFrame):
    """Sits right after the last camera in the grid. Click it to scan for
    and pick a new camera - picking one adds it and opens its settings."""

    clicked = pyqtSignal()

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("addCameraTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(280, 178)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addStretch()
        self._plus_label = QLabel()
        self._plus_label.setFixedSize(40, 40)
        self._plus_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._plus_label, alignment=Qt.AlignHCenter)
        self._text_label = ds.text("Add camera", "small")
        self._text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._text_label)
        layout.addStretch()
        ds.on_theme(self, self.apply_theme)

    def set_size(self, width: int, height: int):
        self.setFixedSize(width, height)
        self.updateGeometry()

    def apply_theme(self, palette: dict):
        p = ds.pal()
        self.setStyleSheet(f"""
            QFrame#addCameraTile {{ background: transparent; border: 1px dashed {p['border_strong']}; border-radius: 12px; }}
            QFrame#addCameraTile:hover {{ border-color: {p['accent']}; background: {p['surface2']}; }}
        """)
        self._plus_label.setStyleSheet(f"background: {p['accent_soft']}; border-radius: 20px;")
        self._plus_label.setPixmap(get_pixmap("plus", p["accent_text"], 20))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CameraSettingsPanel(QWidget, HelpInfoMixin):
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
        self.palette = get_palette(DEFAULT_THEME)
        self._icon_registry = []
        self._camera_discovery = CameraDiscovery()
        self._camera_discovery_progress.connect(self._on_camera_discovery_progress)
        self._camera_discovery_finished.connect(self._on_camera_discovery_finished)

        self.tiles: List[CameraTile] = []
        # cam_id -> CameraView currently needing live frames pushed into it
        # (main_window feeds these each display cycle). Only whichever page
        # is visible gets populated, so a hidden detail view isn't wastefully
        # updated while the grid is showing, and vice versa.
        self.live_views: Dict[int, CameraView] = {}

        self._init_help_info()
        self._setup_ui()
        self._refresh_profile_list()
        self._refresh_camera_grid()
        self.apply_theme(self.palette)

    @property
    def active_profile_id(self) -> str:
        return self._active_profile().id

    def _icon_btn(self, widget: QPushButton, name: str, color_kind: str) -> QPushButton:
        """Registers a button for a Lucide icon that gets recolored on every
        apply_theme() call (color_kind: "white", "destructive", or "dim")."""
        widget.setIconSize(ICON_SIZE)
        self._icon_registry.append((widget, name, color_kind))
        return widget

    def apply_theme(self, palette: dict):
        self.palette = palette
        icon_colors = {"white": palette["on_accent"], "destructive": palette["danger"], "dim": palette["text2"]}
        for widget, name, color_kind in self._icon_registry:
            widget.setIcon(get_icon(name, icon_colors[color_kind]))
        self._apply_help_theme(palette)

    def showEvent(self, event):
        # A hidden widget doesn't get real layout geometry, so the grid's
        # viewport width used for tile sizing (in _layout_camera_grid) can
        # still be stale/near-zero from before this tab was ever shown -
        # producing undersized tiles that don't reach the tab's actual
        # edge. Also, isVisible() on grid_page/detail_page (used by
        # _refresh_live_views) only reflects reality once this panel itself
        # is on screen. Recompute both whenever this tab is switched to.
        super().showEvent(event)
        if hasattr(self, "grid_scroll"):
            self._layout_camera_grid()
        else:
            self._refresh_live_views()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "grid_scroll"):
            self._layout_camera_grid()

    def _label(self, text: str) -> QLabel:
        return ds.text(text, "small")

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
        self._refresh_profile_list()
        self._refresh_camera_grid()
        self._show_grid_page()

    # ---------------- UI construction ----------------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        self.grid_page = self._build_grid_page()
        self.detail_page = self._build_detail_page()

        outer.addWidget(self.grid_page)
        outer.addWidget(self.detail_page)
        self.detail_page.hide()

    def _build_grid_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = ds.PageHeader(
            "Cameras", "Add, discover and switch cameras on for each room. Place them on the floor plan in Room setup.")
        header.add(self._make_info_toggle())
        self.profile_selector = ds.Select(icon="house")
        self.profile_selector.setFixedWidth(190)
        self.profile_selector.currentIndexChanged.connect(self._on_profile_selected)
        header.add(self.profile_selector)
        save_cameras_btn = ds.Button("Save cameras", "primary", "save")
        save_cameras_btn.clicked.connect(self._on_save_cameras)
        header.add(save_cameras_btn)
        layout.addWidget(header)

        panel = ds.GlassPanel("Cameras in this room", "cctv", padding=12)
        self.grid_status_label = ds.text("", "status")
        panel.add_title_widget(self.grid_status_label)
        self._add_help(
            None,
            "Every saved room tracks its own cameras, so each room needs cameras with their "
            "own distinct IDs. Click \"Add camera\" to scan for one - you'll land in its "
            "settings to name it, set its type, and place it. A 180° camera only sees the half "
            "of the room it's pointed at; a 360° camera sees all of it.",
            layout=panel.body_layout,
        )
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.camera_grid = QGridLayout(self.grid_container)
        self.camera_grid.setContentsMargins(0, 0, 0, 0)
        self.camera_grid.setSpacing(GRID_SPACING)
        self.grid_scroll.setWidget(self.grid_container)
        panel.body_layout.addWidget(self.grid_scroll, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        back_btn = ds.Button("Cameras", "ghost", "arrow-left", size="sm")
        back_btn.clicked.connect(self._show_grid_page)
        layout.addWidget(back_btn, 0, Qt.AlignLeft)

        header = ds.PageHeader("Camera", "")
        header.layout().setContentsMargins(4, 0, 4, 0)
        self.detail_title = header.title_label
        self.remove_camera_btn = ds.Button("Remove camera", "danger", "trash-2")
        self.remove_camera_btn.clicked.connect(self._on_remove_camera)
        header.add(self.remove_camera_btn)
        save_camera_btn = ds.Button("Save camera", "primary", "save")
        save_camera_btn.clicked.connect(self._on_save_camera_detail)
        header.add(save_camera_btn)
        layout.addWidget(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._build_preview_section(), 1)
        row.addWidget(self._build_type_section())
        layout.addLayout(row, 1)
        return page

    def _build_type_section(self) -> QFrame:
        section = ds.GlassPanel("Settings", "sliders-horizontal")
        section.setFixedWidth(360)
        layout = section.body_layout

        layout.addWidget(self._label("Label"))
        self.camera_rename_input = ds.TextInput("Camera name")
        layout.addWidget(self.camera_rename_input)

        layout.addWidget(self._label("Type"))
        self.camera_type_edit_input = ds.Select()
        self.camera_type_edit_input.addItems(CAMERA_TYPES)
        layout.addWidget(self.camera_type_edit_input)

        layout.addWidget(self._label("Facing (180° cameras only)"))
        self.camera_facing_stepper = ds.NumberInput(0.0, 359.9, 15.0, 1, suffix="°")
        self.camera_facing_input = self.camera_facing_stepper.spin
        layout.addWidget(self.camera_facing_stepper)
        layout.addWidget(ds.text(
            "0° faces right (+x), 90° faces down (+y), matching the floor plan. Detections a 180° "
            "camera couldn't have seen are mirrored back onto its visible side.", "caption", wrap=True))
        layout.addWidget(ds.separator())
        self.camera_enabled_check = ds.Switch("Enabled")
        layout.addWidget(self.camera_enabled_check)
        layout.addWidget(ds.text("Detection sensitivity for every camera is in Settings → Camera.",
                                 "caption", wrap=True))
        layout.addStretch(1)
        self.camera_status_label = ds.text("", "status", wrap=True)
        layout.addWidget(self.camera_status_label)
        return section

    def _build_preview_section(self) -> QFrame:
        section = ds.GlassPanel("Live preview", "eye")
        self.detail_view = CameraView(0)
        self.detail_view.setMinimumSize(360, 240)
        section.body_layout.addWidget(self.detail_view, 1)
        return section

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
        self._refresh_camera_grid()
        self._show_grid_page()
        self.grid_status_label.setText(f"Editing \"{self._active_profile().name}\".")

    # ---------------- Camera grid ----------------

    def _refresh_camera_grid(self):
        while self.camera_grid.count():
            item = self.camera_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self.tiles = []

        for i, cam in enumerate(self.cameras):
            tile = CameraTile(i, cam, self.palette)
            tile.clicked.connect(self._open_camera_detail)
            tile.enabled_toggled.connect(self._on_tile_enabled_toggled)
            self.tiles.append(tile)

        self.add_tile = AddCameraTile(self.palette)
        self.add_tile.clicked.connect(self._on_add_camera_tile_clicked)

        self._layout_camera_grid()

    def _layout_camera_grid(self):
        """Places every tile (+ the Add tile) into a fixed GRID_COLUMNS-wide
        grid and sizes them, keeping each live preview's aspect ratio fixed.
        Tile size is a baseline "exactly GRID_COLUMNS fit the viewport"
        width scaled by TILE_SCALE - since the row length always stays
        GRID_COLUMNS regardless of TILE_SCALE, a row can end up wider than
        the viewport once scaled up, which is why the grid scrolls
        horizontally as needed rather than shrinking tiles to force-fit.
        Called on every grid rebuild and on resize - existing tile widgets
        are just repositioned/resized, not recreated, so live frames don't
        flicker."""
        if not hasattr(self, "grid_scroll"):
            return
        viewport_width = self.grid_scroll.viewport().width()
        if viewport_width <= 0:
            return

        base_tile_width = (viewport_width - GRID_SPACING * (GRID_COLUMNS - 1)) / GRID_COLUMNS
        tile_total_width = base_tile_width * TILE_SCALE
        view_width = max(MIN_TILE_VIEW_WIDTH, tile_total_width - 2 * TILE_MARGIN)
        view_height = view_width / CAMERA_TILE_ASPECT

        while self.camera_grid.count():
            self.camera_grid.takeAt(0)

        all_items = self.tiles + [self.add_tile]
        for i, widget in enumerate(all_items):
            row, col = divmod(i, GRID_COLUMNS)
            self.camera_grid.addWidget(widget, row, col, alignment=Qt.AlignLeft | Qt.AlignTop)

        for tile in self.tiles:
            tile.set_view_size(int(view_width), int(view_height))

        # Tile chrome: 10px sides, 10 top + 12 bottom, 10 gap, ~36 info row.
        tile_w, tile_h = int(view_width) + 20, int(view_height) + 68
        for tile in self.tiles:
            tile.setFixedSize(tile_w, tile_h)
        self.add_tile.set_size(tile_w, tile_h)

        # A trailing stretch column/row soaks up any leftover scroll-area
        # width/height instead of it being distributed as extra gaps
        # between the (now fixed-size) tiles.
        last_row = len(all_items) // GRID_COLUMNS
        self.camera_grid.setColumnStretch(GRID_COLUMNS, 1)
        self.camera_grid.setRowStretch(last_row + 1, 1)

        self._refresh_live_views()

    def _refresh_live_views(self):
        if self.detail_page.isVisible() and self._selected_camera_index is not None:
            cam = self.cameras[self._selected_camera_index]
            self.live_views = {cam["id"]: self.detail_view}
        elif self.grid_page.isVisible():
            self.live_views = {cam["id"]: tile.view for cam, tile in zip(self.cameras, self.tiles)}
        else:
            self.live_views = {}

    def _on_tile_enabled_toggled(self, index: int, enabled: bool):
        self.cameras[index]["enabled"] = enabled
        self.grid_status_label.setText("Don't forget to Save cameras.")

    def _add_camera(self, cam_id: int, label: str = "", cam_type: str = "Standard") -> Optional[int]:
        if any(c["id"] == cam_id for c in self.cameras):
            self.grid_status_label.setText(f"Camera ID {cam_id} is already in the list.")
            return None
        label = label.strip() or f"Camera {cam_id}"
        profile = self._active_profile()
        self.cameras.append({
            "id": cam_id,
            "label": label,
            "enabled": True,
            "x": profile.width_m / 2.0,
            "y": profile.height_m / 2.0,
            "is_360": cam_type == "360°",
            "is_180": cam_type == "180°",
            "facing_deg": 0.0,
        })
        index = len(self.cameras) - 1
        self._refresh_camera_grid()
        self.grid_status_label.setText(f"Added \"{label}\". Set it up below, then Save.")
        return index

    def _add_camera_and_configure(self, cam_id: int):
        index = self._add_camera(cam_id)
        if index is not None:
            self._open_camera_detail(index)

    def _on_add_camera_tile_clicked(self):
        if self._camera_discovery.is_scanning():
            return
        self.grid_status_label.setText("Scanning for cameras...")
        exclude_ids = {c["id"] for c in self.cameras}
        self._camera_discovery.start_scan(
            max_index=10, exclude_ids=exclude_ids,
            progress_callback=self._camera_discovery_progress.emit,
            done_callback=self._camera_discovery_finished.emit,
        )

    def _on_camera_discovery_progress(self, message: str):
        self.grid_status_label.setText(message)

    def _on_camera_discovery_finished(self, found: list):
        menu = QMenu(self)
        for info in found:
            action = menu.addAction(f"Camera {info['id']} ({info['width']}x{info['height']})")
            action.triggered.connect(lambda checked, cid=info["id"]: self._add_camera_and_configure(cid))
        if found:
            menu.addSeparator()
        manual_action = menu.addAction("Add camera by ID...")
        manual_action.triggered.connect(self._on_manual_add_camera)

        self.grid_status_label.setText(
            f"Found {len(found)} camera(s) - pick one to add." if found
            else "No additional cameras found. Already-added or in-use IDs are skipped."
        )
        menu.exec_(self.add_tile.mapToGlobal(self.add_tile.rect().center()))

    def _on_manual_add_camera(self):
        cam_id, ok = QInputDialog.getInt(self, "Add Camera", "Camera device ID:", 0, 0, 9)
        if ok:
            self._add_camera_and_configure(cam_id)

    def _on_save_cameras(self):
        profile = self._active_profile()
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)
        self.grid_status_label.setText("")
        ds.toast(self, f"Saved cameras for \"{profile.name}\".")
        self.settings_updated.emit()

    # ---------------- Camera detail page ----------------

    def _open_camera_detail(self, index: int):
        self._selected_camera_index = index
        cam = self.cameras[index]

        self.detail_title.setText(f"{cam['label']}  ·  ID {cam['id']}")
        self.detail_view.camera_id = cam["id"]
        self.detail_view.label = cam["label"]
        self.detail_view.set_no_signal()

        self.camera_type_edit_input.blockSignals(True)
        if cam.get("is_360"):
            self.camera_type_edit_input.setCurrentText("360°")
        elif cam.get("is_180"):
            self.camera_type_edit_input.setCurrentText("180°")
        else:
            self.camera_type_edit_input.setCurrentText("Standard")
        self.camera_type_edit_input.blockSignals(False)

        self.camera_facing_input.blockSignals(True)
        self.camera_facing_input.setValue(cam.get("facing_deg", 0.0))
        self.camera_facing_input.blockSignals(False)

        self.camera_rename_input.setText(cam["label"])
        self.camera_enabled_check.setChecked(bool(cam.get("enabled")))
        self.camera_status_label.setText("")

        self.grid_page.hide()
        self.detail_page.show()
        self._refresh_live_views()

    def _show_grid_page(self):
        self._selected_camera_index = None
        self.detail_page.hide()
        self.grid_page.show()
        self._refresh_live_views()

    def _on_save_camera_detail(self):
        if self._selected_camera_index is None:
            return
        cam = self.cameras[self._selected_camera_index]

        new_label = self.camera_rename_input.text().strip()
        if new_label:
            cam["label"] = new_label

        cam_type = self.camera_type_edit_input.currentText()
        cam["is_360"] = cam_type == "360°"
        cam["is_180"] = cam_type == "180°"
        cam["facing_deg"] = self.camera_facing_input.value()
        cam["enabled"] = self.camera_enabled_check.isChecked()

        profile = self._active_profile()
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)

        self.detail_title.setText(f"{cam['label']}  ·  ID {cam['id']}")
        self.camera_status_label.setText(f"Saved \"{cam['label']}\".")
        self.settings_updated.emit()

    def _on_remove_camera(self):
        if self._selected_camera_index is None:
            return
        removed = self.cameras.pop(self._selected_camera_index)
        self._selected_camera_index = None

        profile = self._active_profile()
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)

        self._refresh_camera_grid()
        self._show_grid_page()
        self.grid_status_label.setText(f"Removed \"{removed['label']}\".")
        self.settings_updated.emit()
