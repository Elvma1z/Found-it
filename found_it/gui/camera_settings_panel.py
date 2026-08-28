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
from found_it.utils.themes import get_palette, widget_qss, repolish
from found_it.gui.camera_view import CameraView
from found_it.gui.icons import get_icon, ICON_SIZE

CAMERA_TYPES = ["Standard", "180°", "360°"]
GRID_COLUMNS = 3  # reference column count TILE_SCALE is measured against
GRID_SPACING = 6
TILE_MARGIN = 8
CAMERA_TILE_ASPECT = 280 / 120  # width:height of the live preview inside a tile
MIN_TILE_VIEW_WIDTH = 160
TILE_SCALE = 0.99  # how much bigger tiles are than "3 fit across the tab"


class CameraTile(QFrame):
    """One cell in the camera grid: a live thumbnail plus label/type/enabled
    state. Clicking anywhere on the tile except the checkbox opens that
    camera's dedicated settings screen."""

    clicked = pyqtSignal(int)
    enabled_toggled = pyqtSignal(int, bool)

    def __init__(self, index: int, cam: dict, palette: dict, parent=None):
        super().__init__(parent)
        self.index = index
        self.setCursor(Qt.PointingHandCursor)
        # Fixed rather than just a minimum - otherwise the grid stretches
        # tiles (and the video label inside) to fill leftover space when
        # there are only a few cameras, which upscales the live feed and
        # makes it look blown-up/blurry on tab load.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.view = CameraView(cam["id"], palette=palette)
        self.view.setFixedSize(280, 120)
        layout.addWidget(self.view)

        info_row = QHBoxLayout()
        self.name_label = QLabel()
        self.name_label.setWordWrap(True)
        info_row.addWidget(self.name_label, 1)

        self.enabled_check = QCheckBox("On")
        self.enabled_check.stateChanged.connect(
            lambda state: self.enabled_toggled.emit(self.index, state == Qt.Checked)
        )
        info_row.addWidget(self.enabled_check)
        layout.addLayout(info_row)

        self.set_camera(cam)
        self.apply_theme(palette)

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
        self.name_label.setText(f"{cam['label']}\nID {cam['id']} · {tag}")
        self.enabled_check.blockSignals(True)
        self.enabled_check.setChecked(bool(cam.get("enabled")))
        self.enabled_check.blockSignals(False)

    def apply_theme(self, palette: dict):
        p = palette
        self.setStyleSheet(f"""
            CameraTile {{
                background-color: {p['panel']}; border: 1px solid {p['border']}; border-radius: 6px;
            }}
            CameraTile:hover {{ border: 1px solid {p['accent']}; }}
            QLabel {{ color: {p['text_dim']}; font-size: 11px; border: none; background: transparent; }}
        """)
        self.view.apply_theme(p)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class AddCameraTile(QFrame):
    """Sits right after the last camera in the grid. Click it to scan for
    and pick a new camera - picking one adds it and immediately opens its
    settings screen so it gets set up on the spot rather than sitting
    half-configured in the grid."""

    clicked = pyqtSignal()

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(280, 178)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addStretch()

        self._plus_label = QLabel()
        self._plus_label.setFixedSize(56, 56)
        self._plus_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._plus_label, alignment=Qt.AlignHCenter)

        self._text_label = QLabel("Add Camera")
        self._text_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._text_label)
        layout.addStretch()

        self.apply_theme(palette)

    def set_size(self, width: int, height: int):
        self.setFixedSize(width, height)
        self.updateGeometry()

    def apply_theme(self, palette: dict):
        p = palette
        self.setStyleSheet(f"""
            AddCameraTile {{
                background-color: transparent; border: 2px dashed {p['border']}; border-radius: 6px;
            }}
            AddCameraTile:hover {{ border-color: {p['accent']}; }}
        """)
        self._plus_label.setStyleSheet(f"""
            background-color: {p['accent']};
            border: none; border-radius: 28px;
        """)
        self._plus_label.setPixmap(get_icon("plus", "#ffffff", size=24).pixmap(24, 24))
        self._text_label.setStyleSheet(f"color: {p['text_dim']}; font-size: 12px; border: none; background: transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
        self.palette = get_palette("Indigo")
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
        p = palette
        section_qss = f"""
            QFrame[cls="section"] {{
                background-color: {p['panel']}; border: 1px solid {p['border']}; border-radius: 8px;
            }}
        """
        self.setStyleSheet(widget_qss(palette) + section_qss)

        icon_colors = {"white": "#ffffff", "destructive": "#e57373", "dim": p["text_dim"]}
        for widget, name, color_kind in self._icon_registry:
            widget.setIcon(get_icon(name, icon_colors[color_kind]))

        for tile in self.tiles:
            tile.apply_theme(palette)
        if hasattr(self, "add_tile"):
            self.add_tile.apply_theme(palette)
        self.detail_view.apply_theme(palette)
        repolish(self)

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
        lbl = QLabel(text)
        lbl.setProperty("cls", "muted")
        return lbl

    def _page_title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 13, QFont.Bold))
        lbl.setProperty("cls", "title")
        return lbl

    def _section_frame(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("cls", "section")
        return frame

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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.grid_page = self._build_grid_page()
        self.detail_page = self._build_detail_page()

        outer.addWidget(self.grid_page)
        outer.addWidget(self.detail_page)
        self.detail_page.hide()

    def _build_grid_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Cameras")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        layout.addWidget(title)

        desc = QLabel(
            "Add, discover, or enable/disable cameras below. Click a camera's tile to open "
            "its dedicated settings screen. Once added, switch to the Room Setup tab and drag "
            "its marker into place on the room."
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

        grid_hint = QLabel(
            "Click \"Add Camera\" to scan for and pick a new camera - you'll land straight "
            "in its settings screen to name it, set its type, and place it. A 180° camera "
            "only sees the half of the room it's pointed at; a 360° camera sees the whole "
            "room from wherever it sits."
        )
        grid_hint.setProperty("cls", "hint")
        grid_hint.setWordWrap(True)
        layout.addWidget(grid_hint)

        self.grid_status_label = QLabel("")
        self.grid_status_label.setProperty("cls", "status")
        layout.addWidget(self.grid_status_label)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_container = QWidget()
        self.camera_grid = QGridLayout(self.grid_container)
        self.camera_grid.setSpacing(GRID_SPACING)
        self.grid_scroll.setWidget(self.grid_container)
        layout.addWidget(self.grid_scroll, 1)

        save_cameras_btn = self._icon_btn(QPushButton(" Save Cameras"), "save", "white")
        save_cameras_btn.setProperty("cls", "primary")
        save_cameras_btn.clicked.connect(self._on_save_cameras)
        layout.addWidget(save_cameras_btn)

        return page

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        back_btn = self._icon_btn(QPushButton(" Back to Cameras"), "arrow-left", "dim")
        back_btn.setProperty("cls", "muted")
        back_btn.clicked.connect(self._show_grid_page)
        header_row.addWidget(back_btn)

        self.detail_title = QLabel("Camera")
        self.detail_title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        self.detail_title.setProperty("cls", "title")
        header_row.addWidget(self.detail_title)
        header_row.addStretch()
        layout.addLayout(header_row)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(self._build_type_section(), 1)
        top_row.addWidget(self._build_preview_section(), 2)
        top_row.addWidget(self._build_detection_section(), 1)
        layout.addLayout(top_row, 4)

        layout.addWidget(self._build_other_settings_section(), 3)

        return page

    def _build_type_section(self) -> QFrame:
        section = self._section_frame()
        layout = QVBoxLayout(section)
        layout.setSpacing(8)
        layout.addWidget(self._page_title("Camera Type"))

        layout.addWidget(self._label("Type"))
        self.camera_type_edit_input = QComboBox()
        self.camera_type_edit_input.addItems(CAMERA_TYPES)
        layout.addWidget(self.camera_type_edit_input)

        layout.addWidget(self._label("Facing (° - 180° cams only)"))
        self.camera_facing_input = QDoubleSpinBox()
        self.camera_facing_input.setRange(0.0, 359.9)
        self.camera_facing_input.setSingleStep(15.0)
        self.camera_facing_input.setSuffix("°")
        layout.addWidget(self.camera_facing_input)

        facing_hint = QLabel(
            "0° faces right (+x), 90° faces down (+y), matching the room canvas. Detections "
            "a 180° camera couldn't have seen are mirrored back onto its visible side."
        )
        facing_hint.setProperty("cls", "hint")
        facing_hint.setWordWrap(True)
        layout.addWidget(facing_hint)
        layout.addStretch()
        return section

    def _build_preview_section(self) -> QFrame:
        section = self._section_frame()
        layout = QVBoxLayout(section)
        layout.addWidget(self._page_title("Live Preview"))
        self.detail_view = CameraView(0, palette=self.palette)
        self.detail_view.setMinimumSize(360, 240)
        layout.addWidget(self.detail_view, 1)
        return section

    def _build_detection_section(self) -> QFrame:
        section = self._section_frame()
        layout = QVBoxLayout(section)
        layout.setSpacing(8)
        layout.addWidget(self._page_title("Detection"))
        detection_desc = QLabel("Tunes detection across every camera in every room.")
        detection_desc.setProperty("cls", "muted")
        detection_desc.setWordWrap(True)
        layout.addWidget(detection_desc)

        layout.addWidget(self._label("Detection confidence"))
        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.05, 0.95)
        self.confidence_input.setSingleStep(0.05)
        self.confidence_input.setValue(self.app_settings.detection_confidence)
        layout.addWidget(self.confidence_input)
        conf_hint = QLabel("Higher = fewer false positives, but may miss partially hidden items.")
        conf_hint.setProperty("cls", "hint")
        conf_hint.setWordWrap(True)
        layout.addWidget(conf_hint)

        layout.addWidget(self._label("Detect every N frames"))
        self.frame_skip_input = QSpinBox()
        self.frame_skip_input.setRange(1, 15)
        self.frame_skip_input.setValue(self.app_settings.detection_frame_skip)
        layout.addWidget(self.frame_skip_input)
        skip_hint = QLabel("Higher = less CPU usage, slower to notice new items.")
        skip_hint.setProperty("cls", "hint")
        skip_hint.setWordWrap(True)
        layout.addWidget(skip_hint)

        self.dewarp_default_check = QCheckBox("Enable fisheye/360° dewarping by default")
        self.dewarp_default_check.setChecked(self.app_settings.dewarp_default)
        layout.addWidget(self.dewarp_default_check)

        self.detection_status_label = QLabel("")
        self.detection_status_label.setProperty("cls", "status")
        layout.addWidget(self.detection_status_label)

        save_detection_btn = self._icon_btn(QPushButton(" Save Detection Settings"), "save", "white")
        save_detection_btn.setProperty("cls", "primary")
        save_detection_btn.clicked.connect(self._on_save_detection_settings)
        layout.addWidget(save_detection_btn)
        layout.addStretch()
        return section

    def _build_other_settings_section(self) -> QFrame:
        section = self._section_frame()
        layout = QVBoxLayout(section)
        layout.setSpacing(8)
        layout.addWidget(self._page_title("Other Settings"))

        rename_row = QHBoxLayout()
        rename_row.setSpacing(8)
        rename_row.addWidget(self._label("Label"))
        self.camera_rename_input = QLineEdit()
        self.camera_rename_input.setPlaceholderText("Camera name")
        rename_row.addWidget(self.camera_rename_input, 1)
        layout.addLayout(rename_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.camera_enabled_check = QCheckBox("Enabled")
        action_row.addWidget(self.camera_enabled_check)
        action_row.addStretch()

        self.remove_camera_btn = self._icon_btn(QPushButton(" Remove Camera"), "trash-2", "destructive")
        self.remove_camera_btn.setProperty("cls", "destructive")
        self.remove_camera_btn.clicked.connect(self._on_remove_camera)
        action_row.addWidget(self.remove_camera_btn)
        layout.addLayout(action_row)

        self.camera_status_label = QLabel("")
        self.camera_status_label.setProperty("cls", "status")
        layout.addWidget(self.camera_status_label)

        save_camera_btn = self._icon_btn(QPushButton(" Save Camera"), "save", "white")
        save_camera_btn.setProperty("cls", "primary")
        save_camera_btn.clicked.connect(self._on_save_camera_detail)
        layout.addWidget(save_camera_btn)
        layout.addStretch()
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

        if self.tiles:
            # Match the Add tile to a real tile's actual total size (its
            # sizeHint, now that its view has just been resized) rather than
            # re-deriving the label/checkbox chrome height by hand.
            self.add_tile.set_size(self.tiles[0].sizeHint().width(), self.tiles[0].sizeHint().height())
        else:
            self.add_tile.set_size(int(tile_total_width), int(view_height) + 60)

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
        self.grid_status_label.setText("Don't forget to Save Cameras.")

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
        self.grid_status_label.setText(f"Saved cameras for \"{profile.name}\".")
        self.settings_updated.emit()

    # ---------------- Camera detail page ----------------

    def _open_camera_detail(self, index: int):
        self._selected_camera_index = index
        cam = self.cameras[index]

        self.detail_title.setText(f"{cam['label']} (ID {cam['id']})")
        self.detail_view.camera_id = cam["id"]
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

        self.detail_title.setText(f"{cam['label']} (ID {cam['id']})")
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

    # ---------------- Detection settings ----------------

    def _on_save_detection_settings(self):
        self.app_settings.detection_confidence = self.confidence_input.value()
        self.app_settings.detection_frame_skip = self.frame_skip_input.value()
        self.app_settings.dewarp_default = self.dewarp_default_check.isChecked()
        save_app_settings(self.app_settings)
        self.detection_status_label.setText("Saved. Applies immediately.")
        self.settings_updated.emit()
