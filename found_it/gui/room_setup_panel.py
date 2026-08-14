import uuid
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QDoubleSpinBox, QSpinBox, QComboBox,
    QInputDialog, QMessageBox, QMenu, QScrollArea,
    QMainWindow, QDockWidget
)
from PyQt5.QtCore import Qt, pyqtSignal, QByteArray
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush
from typing import List, Optional, Tuple

from found_it.utils.room_profiles import load_room_profiles, save_room_profiles
from found_it.storage.database import Database
from found_it.storage.models import RoomConfig
from found_it.detection.item_mapper import ItemMapper
from found_it.utils.themes import get_palette, widget_qss, repolish
from found_it.utils.app_settings import load_app_settings, save_app_settings
from found_it.camera.capture import CameraDiscovery

# Real-world footprints (width_m, depth_m) for COCO labels worth auto-placing
# as a zone when detected. Camera detections can't measure true size, so
# these are reasonable defaults the user can still resize/move by hand.
FURNITURE_SIZES_M = {
    "bed": (1.6, 2.0),
    "couch": (1.8, 0.9),
    "chair": (0.5, 0.5),
    "dining table": (1.2, 0.8),
    "tv": (1.1, 0.15),
    "refrigerator": (0.7, 0.7),
    "sink": (0.6, 0.5),
    "toilet": (0.4, 0.6),
    "oven": (0.6, 0.6),
    "microwave": (0.5, 0.4),
    "potted plant": (0.4, 0.4),
}

CAMERA_COLORS = {
    0: QColor(255, 100, 100),
    1: QColor(100, 100, 255),
    2: QColor(100, 255, 180),
}
CAMERA_FALLBACK_COLORS = [
    QColor(255, 180, 60), QColor(200, 100, 255), QColor(255, 100, 200),
    QColor(120, 220, 255), QColor(180, 255, 100),
]


def _camera_color(cam_id: int) -> QColor:
    if cam_id in CAMERA_COLORS:
        return CAMERA_COLORS[cam_id]
    return CAMERA_FALLBACK_COLORS[cam_id % len(CAMERA_FALLBACK_COLORS)]


def _remap_drawers(drawers: List[dict], old_x1: float, old_y1: float, old_x2: float, old_y2: float,
                    new_x1: float, new_y1: float, new_x2: float, new_y2: float) -> List[dict]:
    """Re-fit drawer rectangles proportionally when their parent zone moves or resizes."""
    old_w = (old_x2 - old_x1) or 1.0
    old_h = (old_y2 - old_y1) or 1.0
    new_w = new_x2 - new_x1
    new_h = new_y2 - new_y1
    remapped = []
    for d in drawers:
        rel_x1 = (d["x1"] - old_x1) / old_w
        rel_y1 = (d["y1"] - old_y1) / old_h
        rel_x2 = (d["x2"] - old_x1) / old_w
        rel_y2 = (d["y2"] - old_y1) / old_h
        remapped.append({
            "name": d["name"],
            "x1": new_x1 + rel_x1 * new_w,
            "y1": new_y1 + rel_y1 * new_h,
            "x2": new_x1 + rel_x2 * new_w,
            "y2": new_y1 + rel_y2 * new_h,
        })
    return remapped


def _rotate_drawers_cw(drawers: List[dict], old_x1: float, old_y1: float, old_x2: float, old_y2: float,
                        new_x1: float, new_y1: float, new_x2: float, new_y2: float) -> List[dict]:
    """Rotate drawer rectangles 90 degrees clockwise along with their parent zone,
    instead of stretching them to fit the new (swapped) bounding box."""
    old_w = (old_x2 - old_x1) or 1.0
    old_h = (old_y2 - old_y1) or 1.0
    new_w = new_x2 - new_x1
    new_h = new_y2 - new_y1
    remapped = []
    for d in drawers:
        rx1 = (d["x1"] - old_x1) / old_w
        ry1 = (d["y1"] - old_y1) / old_h
        rx2 = (d["x2"] - old_x1) / old_w
        ry2 = (d["y2"] - old_y1) / old_h
        # 90 deg clockwise: (rx, ry) -> (1 - ry, rx)
        nrx1, nry1 = 1.0 - ry1, rx1
        nrx2, nry2 = 1.0 - ry2, rx2
        remapped.append({
            "name": d["name"],
            "x1": new_x1 + min(nrx1, nrx2) * new_w,
            "x2": new_x1 + max(nrx1, nrx2) * new_w,
            "y1": new_y1 + min(nry1, nry2) * new_h,
            "y2": new_y1 + max(nry1, nry2) * new_h,
        })
    return remapped


def _clamp_axis(a1: float, a2: float, room_size: float) -> Tuple[float, float]:
    """Slide a span [a1, a2] to stay within [0, room_size] without ever changing its size."""
    size = a2 - a1
    if a1 < 0:
        return 0.0, size
    if a2 > room_size:
        return room_size - size, room_size
    return a1, a2


class RoomCanvas(QWidget):
    """Interactive canvas for laying out a room: drag to draw a named zone
    or drag a camera marker to reposition it."""

    zone_drawn = pyqtSignal(float, float, float, float)
    zone_selected = pyqtSignal(int)
    zone_drag_finished = pyqtSignal()
    camera_moved = pyqtSignal(int, float, float)
    camera_drag_finished = pyqtSignal()
    camera_selected = pyqtSignal(int)
    camera_delete_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    rotate_requested = pyqtSignal()

    CAMERA_HIT_RADIUS_PX = 12
    CORNER_HANDLE_RADIUS_PX = 7
    MIN_ZONE_SIZE_M = 0.1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setFocusPolicy(Qt.StrongFocus)
        self.room_width = 4.0
        self.room_height = 4.0
        self.zones: List[dict] = []
        self.cameras: List[dict] = []
        self.draw_mode = False
        self.selected_index: Optional[int] = None
        self.selected_camera_index: Optional[int] = None
        self._drag_start: Optional[Tuple[float, float]] = None
        self._drag_current: Optional[Tuple[float, float]] = None
        self._dragging_camera_index: Optional[int] = None
        self._dragging_zone_index: Optional[int] = None
        self._zone_drag_start_mouse: Optional[Tuple[float, float]] = None
        self._zone_drag_start_bounds: Optional[Tuple[float, float, float, float]] = None
        self._zone_drag_start_drawers: Optional[List[dict]] = None
        self._resizing_zone_index: Optional[int] = None
        self._resize_start_bounds: Optional[Tuple[float, float, float, float]] = None
        self._resize_start_drawers: Optional[List[dict]] = None
        self._padding = 30
        self.palette = get_palette("Indigo")

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.update()

    def _corner_handle_px(self, zone: dict) -> Tuple[int, int]:
        return self._m_to_px(zone["x1"], zone["y1"])

    def set_room_size(self, width: float, height: float):
        self.room_width = max(width, 0.1)
        self.room_height = max(height, 0.1)
        self.update()

    def set_zones(self, zones: List[dict]):
        self.zones = zones
        self.selected_index = None
        self.update()

    def set_cameras(self, cameras: List[dict]):
        self.cameras = cameras
        self.selected_camera_index = None
        self.update()

    def set_draw_mode(self, enabled: bool):
        self.draw_mode = enabled
        self._drag_start = None
        self._drag_current = None
        self.update()

    def _draw_rect(self):
        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        return draw_w, draw_h

    def _scale_and_offset(self) -> Tuple[float, float, float, float, float]:
        """A single meters-to-pixels scale (not one per axis) so the room and
        everything in it renders in true proportion instead of stretching to
        fill the canvas - the room is letterboxed/centered within it instead."""
        draw_w, draw_h = self._draw_rect()
        if self.room_width <= 0 or self.room_height <= 0 or draw_w <= 0 or draw_h <= 0:
            return 1.0, float(self._padding), float(self._padding), float(max(draw_w, 0)), float(max(draw_h, 0))
        scale = min(draw_w / self.room_width, draw_h / self.room_height)
        room_px_w = self.room_width * scale
        room_px_h = self.room_height * scale
        ox = self._padding + (draw_w - room_px_w) / 2.0
        oy = self._padding + (draw_h - room_px_h) / 2.0
        return scale, ox, oy, room_px_w, room_px_h

    def _px_to_m(self, px: int, py: int) -> Tuple[float, float]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        x = (px - ox) / scale if scale else 0.0
        y = (py - oy) / scale if scale else 0.0
        x = max(0.0, min(self.room_width, x))
        y = max(0.0, min(self.room_height, y))
        return x, y

    def _m_to_px(self, x: float, y: float) -> Tuple[int, int]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        return int(ox + x * scale), int(oy + y * scale)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.draw_mode:
            self._drag_start = self._px_to_m(event.x(), event.y())
            self._drag_current = self._drag_start
            self.update()
            return

        if self.selected_index is not None and self.selected_index < len(self.zones):
            zone = self.zones[self.selected_index]
            hx, hy = self._corner_handle_px(zone)
            if (event.x() - hx) ** 2 + (event.y() - hy) ** 2 <= self.CORNER_HANDLE_RADIUS_PX ** 2:
                self._resizing_zone_index = self.selected_index
                self._resize_start_bounds = (zone["x1"], zone["y1"], zone["x2"], zone["y2"])
                self._resize_start_drawers = [dict(d) for d in zone.get("drawers", [])]
                self.setFocus()
                self.update()
                return

        for i, cam in enumerate(self.cameras):
            cx, cy = self._m_to_px(cam.get("x", 0), cam.get("y", 0))
            if (event.x() - cx) ** 2 + (event.y() - cy) ** 2 <= self.CAMERA_HIT_RADIUS_PX ** 2:
                self.selected_camera_index = i
                self.selected_index = None
                self.camera_selected.emit(i)
                self._dragging_camera_index = i
                self.setFocus()
                self.update()
                return

        mx, my = self._px_to_m(event.x(), event.y())
        for i, z in enumerate(self.zones):
            if z["x1"] <= mx <= z["x2"] and z["y1"] <= my <= z["y2"]:
                self.selected_index = i
                self.selected_camera_index = None
                self.zone_selected.emit(i)
                self._dragging_zone_index = i
                self._zone_drag_start_mouse = (mx, my)
                self._zone_drag_start_bounds = (z["x1"], z["y1"], z["x2"], z["y2"])
                self._zone_drag_start_drawers = [dict(d) for d in z.get("drawers", [])]
                self.setFocus()
                self.update()
                return
        self.selected_index = None
        self.selected_camera_index = None
        self.setFocus()
        self.update()

    def mouseMoveEvent(self, event):
        if self._resizing_zone_index is not None:
            mx, my = self._px_to_m(event.x(), event.y())
            ox1, oy1, ox2, oy2 = self._resize_start_bounds
            nx1 = max(0.0, min(mx, ox2 - self.MIN_ZONE_SIZE_M))
            ny1 = max(0.0, min(my, oy2 - self.MIN_ZONE_SIZE_M))

            zone = self.zones[self._resizing_zone_index]
            zone["x1"], zone["y1"], zone["x2"], zone["y2"] = nx1, ny1, ox2, oy2
            if self._resize_start_drawers:
                zone["drawers"] = _remap_drawers(
                    self._resize_start_drawers, ox1, oy1, ox2, oy2, nx1, ny1, ox2, oy2
                )
            self.update()
            return
        if self._dragging_camera_index is not None:
            mx, my = self._px_to_m(event.x(), event.y())
            cam = self.cameras[self._dragging_camera_index]
            cam["x"] = mx
            cam["y"] = my
            self.camera_moved.emit(self._dragging_camera_index, mx, my)
            self.update()
            return
        if self._dragging_zone_index is not None:
            mx, my = self._px_to_m(event.x(), event.y())
            start_mx, start_my = self._zone_drag_start_mouse
            ox1, oy1, ox2, oy2 = self._zone_drag_start_bounds
            dx = mx - start_mx
            dy = my - start_my

            nx1, nx2 = _clamp_axis(ox1 + dx, ox2 + dx, self.room_width)
            ny1, ny2 = _clamp_axis(oy1 + dy, oy2 + dy, self.room_height)

            zone = self.zones[self._dragging_zone_index]
            zone["x1"], zone["y1"], zone["x2"], zone["y2"] = nx1, ny1, nx2, ny2
            if self._zone_drag_start_drawers:
                zone["drawers"] = _remap_drawers(
                    self._zone_drag_start_drawers, ox1, oy1, ox2, oy2, nx1, ny1, nx2, ny2
                )
            self.update()
            return
        if self.draw_mode and self._drag_start is not None:
            self._drag_current = self._px_to_m(event.x(), event.y())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._resizing_zone_index is not None:
            self._resizing_zone_index = None
            self._resize_start_bounds = None
            self._resize_start_drawers = None
            self.zone_drag_finished.emit()
            return
        if self._dragging_camera_index is not None:
            self._dragging_camera_index = None
            self.camera_drag_finished.emit()
            return
        if self._dragging_zone_index is not None:
            self._dragging_zone_index = None
            self._zone_drag_start_mouse = None
            self._zone_drag_start_bounds = None
            self._zone_drag_start_drawers = None
            self.zone_drag_finished.emit()
            return
        if self.draw_mode and self._drag_start is not None:
            end = self._px_to_m(event.x(), event.y())
            x1, x2 = sorted((self._drag_start[0], end[0]))
            y1, y2 = sorted((self._drag_start[1], end[1]))
            self._drag_start = None
            self._drag_current = None
            self.update()
            if x2 - x1 >= 0.1 and y2 - y1 >= 0.1:
                self.zone_drawn.emit(x1, y1, x2, y2)

    def paintEvent(self, event):
        p = self.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        _, ox, oy, room_px_w, room_px_h = self._scale_and_offset()
        ox, oy, room_px_w, room_px_h = int(ox), int(oy), int(room_px_w), int(room_px_h)

        painter.setPen(QPen(QColor(p["border"]), 2))
        painter.setBrush(QBrush(QColor(p["bg"])))
        painter.drawRoundedRect(ox, oy, room_px_w, room_px_h, 6, 6)

        painter.setPen(QPen(QColor(p["border"]), 1, Qt.DashLine))
        for i in range(1, 4):
            x = ox + int(room_px_w * i / 4)
            painter.drawLine(x, oy, x, oy + room_px_h)
            y = oy + int(room_px_h * i / 4)
            painter.drawLine(ox, y, ox + room_px_w, y)

        accent = QColor(p["accent"])
        accent_hover = QColor(p["accent_hover"])
        for i, zone in enumerate(self.zones):
            x1, y1 = self._m_to_px(zone["x1"], zone["y1"])
            x2, y2 = self._m_to_px(zone["x2"], zone["y2"])
            selected = i == self.selected_index
            color = accent_hover if selected else accent
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)
            painter.setPen(QPen(QColor(p["text"]), 1))
            font = QFont("Segoe UI", 8, QFont.Bold)
            painter.setFont(font)
            painter.drawText(x1 + 4, y1 + 14, zone.get("name", "Zone"))

            for drawer in zone.get("drawers", []):
                dx1, dy1 = self._m_to_px(drawer["x1"], drawer["y1"])
                dx2, dy2 = self._m_to_px(drawer["x2"], drawer["y2"])
                painter.setPen(QPen(QColor(255, 210, 90), 1, Qt.DotLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(dx1, dy1, dx2 - dx1, dy2 - dy1)
                painter.setPen(QPen(QColor(220, 210, 180), 1))
                painter.setFont(QFont("Segoe UI", 6))
                painter.drawText(dx1 + 3, dy1 + 11, drawer.get("name", "Drawer"))

        if self.selected_index is not None and self.selected_index < len(self.zones):
            handle_zone = self.zones[self.selected_index]
            hx, hy = self._corner_handle_px(handle_zone)
            r = self.CORNER_HANDLE_RADIUS_PX
            painter.setPen(QPen(accent_hover, 2))
            painter.setBrush(QBrush(accent_hover))
            painter.drawRect(hx - r, hy - r, r * 2, r * 2)

        if self.draw_mode and self._drag_start and self._drag_current:
            x1, y1 = self._m_to_px(*self._drag_start)
            x2, y2 = self._m_to_px(*self._drag_current)
            painter.setPen(QPen(QColor(100, 255, 180), 2, Qt.DashLine))
            painter.setBrush(QBrush(QColor(100, 255, 180, 40)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

        for i, cam in enumerate(self.cameras):
            cx, cy = self._m_to_px(cam.get("x", 0), cam.get("y", 0))
            color = _camera_color(cam.get("id", 0))
            alpha = 255 if cam.get("enabled") else 90
            is_dragging = i == self._dragging_camera_index
            is_selected = i == self.selected_camera_index
            radius = 10 if is_dragging else 8

            if is_selected:
                ring_r = radius + 5
                painter.setPen(QPen(accent_hover, 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)

            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), min(alpha, 130))))
            painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            text_color = QColor(p["text"])
            text_color.setAlpha(alpha)
            painter.setPen(QPen(text_color, 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(cx + 12, cy + 4, cam.get("label", f"Camera {cam.get('id', 0)}"))

        painter.end()

    def keyPressEvent(self, event):
        if self.selected_camera_index is not None and self.selected_camera_index < len(self.cameras):
            if event.key() == Qt.Key_Delete and event.modifiers() == Qt.NoModifier:
                self.camera_delete_requested.emit()
                return
            super().keyPressEvent(event)
            return

        if self.selected_index is None or self.selected_index >= len(self.zones):
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key_Delete and event.modifiers() == Qt.NoModifier:
            self.delete_requested.emit()
            return

        if event.key() == Qt.Key_R and event.modifiers() == Qt.ControlModifier:
            self.rotate_requested.emit()
            return

        super().keyPressEvent(event)


class RoomSetupPanel(QWidget):
    """Lets the user size their room, lay out named zones/furniture, and rename detected objects."""

    room_updated = pyqtSignal()

    # Emitted from the background scan thread - queued automatically onto
    # this widget's own (GUI) thread since the connected slots below live
    # here, so it's safe to touch widgets (including popping up a QMenu)
    # from the handlers even though the scan itself runs elsewhere.
    _camera_discovery_progress = pyqtSignal(str)
    _camera_discovery_finished = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles: List[RoomConfig] = load_room_profiles()
        self._active_profile_index = 0
        self.zones: List[dict] = [dict(z) for z in self.profiles[0].zones]
        self.cameras: List[dict] = [dict(c) for c in self.profiles[0].cameras]
        self.palette = get_palette("Indigo")
        self._camera_discovery = CameraDiscovery()
        self._camera_discovery_progress.connect(self._on_camera_discovery_progress)
        self._camera_discovery_finished.connect(self._on_camera_discovery_finished)
        self._setup_ui()
        self._refresh_profile_list()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_camera_list()
        self._refresh_object_list()
        self.apply_theme(self.palette)
        self._restore_layout()

    def apply_theme(self, palette: dict):
        self.palette = palette
        p = palette
        # Room Setup's lists (cameras/zones/drawers/objects) get taller rows
        # than the shared default - selecting the right one among many needs
        # a slightly bigger click/read target here. Qt rounds QSS padding to
        # whole pixels per side, so 6.5px (vs. the shared 6px) is the
        # smallest step that actually renders taller instead of rounding away.
        self.setStyleSheet(widget_qss(palette) + """
            QListWidget::item { padding: 6.5px 6px; }
        """)
        repolish(self)
        self.canvas.apply_theme(palette)

        self.dock_host.setStyleSheet(f"""
            QMainWindow {{ background-color: {p['bg']}; }}
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

    def _restore_layout(self):
        state_b64 = load_app_settings().room_setup_layout
        if not state_b64:
            return
        try:
            state = QByteArray.fromBase64(state_b64.encode())
            self.dock_host.restoreState(state)
        except Exception:
            pass

    def save_layout(self):
        """Persist the current dock panel arrangement (size/position/floating
        state) so the Room Setup panel reopens where the user left it -
        called on app close, same as Room Tracker's own layout."""
        state = self.dock_host.saveState()
        settings = load_app_settings()
        settings.room_setup_layout = bytes(state.toBase64()).decode()
        save_app_settings(settings)

    def _active_profile(self) -> RoomConfig:
        return self.profiles[self._active_profile_index]

    def reload_profiles(self):
        """Re-read room profiles from disk - for changes made outside this
        panel (e.g. importing room data in Settings) so it doesn't keep
        editing a stale in-memory copy and clobber the import on next Save."""
        self.profiles = load_room_profiles()
        if self._active_profile_index >= len(self.profiles):
            self._active_profile_index = 0
        self.zones = [dict(z) for z in self._active_profile().zones]
        self.cameras = [dict(c) for c in self._active_profile().cameras]
        self._refresh_profile_list()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self._refresh_camera_list()
        self._refresh_object_list()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(10)

        title = QLabel("Room Setup")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setProperty("cls", "title")
        outer.addWidget(title)

        desc = QLabel("Set a room's size, sketch out zones like the bed or desk, and rename detected objects. "
                       "Use \"New Room\" to add another room profile, or \"Rename\" to rename this one.")
        desc.setProperty("cls", "muted")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        self.dock_host = QMainWindow()
        self.dock_host.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
        )
        view_menu = self.dock_host.menuBar().addMenu("Panels")

        # --- Central: dimensions + canvas ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 4, 4, 4)
        left_layout.setSpacing(10)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        profile_row.addWidget(self._label("Editing Room"))
        self.profile_selector = QComboBox()
        self.profile_selector.currentIndexChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_selector, 1)

        self.new_room_btn = QPushButton("New Room")
        self.new_room_btn.setProperty("cls", "secondary")
        self.new_room_btn.clicked.connect(self._on_new_room)
        profile_row.addWidget(self.new_room_btn)

        self.rename_room_btn = QPushButton("Rename")
        self.rename_room_btn.setProperty("cls", "secondary")
        self.rename_room_btn.clicked.connect(self._on_rename_room)
        profile_row.addWidget(self.rename_room_btn)

        self.delete_room_btn = QPushButton("Delete")
        self.delete_room_btn.setProperty("cls", "secondary")
        self.delete_room_btn.clicked.connect(self._on_delete_room)
        profile_row.addWidget(self.delete_room_btn)
        left_layout.addLayout(profile_row)

        profile_hint = QLabel(
            "Every saved room tracks its own cameras in the background at the same time, "
            "even while you're viewing a different one - so each room needs cameras with "
            "their own distinct IDs. Switch which one you're viewing from the \"Main Room\" "
            "button in Room Tracker."
        )
        profile_hint.setProperty("cls", "hint")
        profile_hint.setWordWrap(True)
        left_layout.addWidget(profile_hint)

        dims_row = QHBoxLayout()
        dims_row.setSpacing(8)
        dims_row.addWidget(self._label("Width (m)"))
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(1.0, 30.0)
        self.width_input.setSingleStep(0.1)
        self.width_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.width_input)

        dims_row.addWidget(self._label("Height (m)"))
        self.height_input = QDoubleSpinBox()
        self.height_input.setRange(1.0, 30.0)
        self.height_input.setSingleStep(0.1)
        self.height_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.height_input)
        dims_row.addStretch()
        left_layout.addLayout(dims_row)

        self.canvas = RoomCanvas()
        self.canvas.zone_drawn.connect(self._on_zone_drawn)
        self.canvas.zone_selected.connect(self._on_zone_selected_in_canvas)
        self.canvas.zone_drag_finished.connect(self._on_zone_drag_finished)
        self.canvas.camera_moved.connect(self._on_camera_moved)
        self.canvas.camera_drag_finished.connect(self._on_camera_drag_finished)
        self.canvas.camera_selected.connect(self._on_camera_selected_in_canvas)
        self.canvas.camera_delete_requested.connect(self._on_remove_camera)
        self.canvas.delete_requested.connect(self._on_delete_zone)
        self.canvas.rotate_requested.connect(self._on_rotate_zone)
        left_layout.addWidget(self.canvas)

        self.status_label = QLabel("")
        self.status_label.setProperty("cls", "status")
        left_layout.addWidget(self.status_label)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setWidget(left)
        self.dock_host.setCentralWidget(left_scroll)

        # --- Cameras panel ---
        cameras_widget = QWidget()
        right_layout = QVBoxLayout(cameras_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(10)

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
        right_layout.addLayout(camera_add_row)

        camera_hint = QLabel("Drag a camera's marker on the room to place it where it actually sits. "
                              "Click a marker to select it, then press Delete (or use Remove below) to "
                              "take it out. Detected objects are positioned relative to that camera.")
        camera_hint.setProperty("cls", "hint")
        camera_hint.setWordWrap(True)
        right_layout.addWidget(camera_hint)

        discover_row = QHBoxLayout()
        discover_row.setSpacing(8)
        self.discover_cameras_btn = QPushButton("Discover Cameras")
        self.discover_cameras_btn.setProperty("cls", "secondary")
        self.discover_cameras_btn.clicked.connect(self._on_discover_cameras)
        discover_row.addWidget(self.discover_cameras_btn)
        right_layout.addLayout(discover_row)

        discover_hint = QLabel("Scans this PC for cameras that aren't in the list yet, so you don't have "
                                "to guess an ID. Already-added or currently in-use cameras are skipped.")
        discover_hint.setProperty("cls", "hint")
        discover_hint.setWordWrap(True)
        right_layout.addWidget(discover_hint)

        self.camera_list = QListWidget()
        self.camera_list.setMinimumHeight(80)
        self.camera_list.itemClicked.connect(self._on_camera_list_clicked)
        self.camera_list.itemChanged.connect(self._on_camera_item_changed)
        right_layout.addWidget(self.camera_list)

        camera_edit_row = QHBoxLayout()
        camera_edit_row.setSpacing(8)
        self.camera_rename_input = QLineEdit()
        self.camera_rename_input.setPlaceholderText("Rename selected camera")
        camera_edit_row.addWidget(self.camera_rename_input)

        self.rename_camera_btn = QPushButton("Rename")
        self.rename_camera_btn.setProperty("cls", "primary")
        self.rename_camera_btn.clicked.connect(self._on_rename_camera)
        camera_edit_row.addWidget(self.rename_camera_btn)
        right_layout.addLayout(camera_edit_row)

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
        right_layout.addLayout(camera_action_row)
        right_layout.addStretch()

        self.cameras_dock = QDockWidget("Cameras", self.dock_host)
        self.cameras_dock.setObjectName("cameras_dock")
        self.cameras_dock.setWidget(cameras_widget)
        self.cameras_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self.dock_host.addDockWidget(Qt.RightDockWidgetArea, self.cameras_dock)
        view_menu.addAction(self.cameras_dock.toggleViewAction())

        # --- Zones / Furniture panel ---
        zones_widget = QWidget()
        right_layout = QVBoxLayout(zones_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(10)

        zones_hint = QLabel("Drag a zone on the room to move it, or drag its top-left corner handle to resize it. "
                             "With a zone selected: Delete removes it, Ctrl+R rotates it 90°.")
        zones_hint.setProperty("cls", "hint")
        zones_hint.setWordWrap(True)
        right_layout.addWidget(zones_hint)

        scan_row = QHBoxLayout()
        scan_row.setSpacing(8)
        self.scan_room_btn = QPushButton("Scan Room with Cameras")
        self.scan_room_btn.setProperty("cls", "secondary")
        self.scan_room_btn.clicked.connect(self._on_scan_room)
        scan_row.addWidget(self.scan_room_btn)
        right_layout.addLayout(scan_row)

        scan_hint = QLabel("Auto-creates zones for furniture the cameras currently recognize (bed, couch, chair, TV, etc.) at their mapped position. Sizes are estimates since a camera can't measure true dimensions - reposition/resize by hand afterward. Add cameras and enable them first.")
        scan_hint.setProperty("cls", "hint")
        scan_hint.setWordWrap(True)
        right_layout.addWidget(scan_hint)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.zone_name_input = QLineEdit()
        self.zone_name_input.setPlaceholderText("e.g. Bed, Desk, Closet")
        add_row.addWidget(self.zone_name_input)

        self.draw_zone_btn = QPushButton("Draw Zone")
        self.draw_zone_btn.setCheckable(True)
        self.draw_zone_btn.setProperty("cls", "secondary")
        self.draw_zone_btn.clicked.connect(self._on_draw_zone_clicked)
        add_row.addWidget(self.draw_zone_btn)
        right_layout.addLayout(add_row)

        self.zone_list = QListWidget()
        self.zone_list.setMinimumHeight(80)
        self.zone_list.itemClicked.connect(self._on_zone_list_clicked)
        right_layout.addWidget(self.zone_list)

        rename_row = QHBoxLayout()
        rename_row.setSpacing(8)
        self.zone_rename_input = QLineEdit()
        self.zone_rename_input.setPlaceholderText("Rename selected zone")
        rename_row.addWidget(self.zone_rename_input)

        self.rename_zone_btn = QPushButton("Rename")
        self.rename_zone_btn.setProperty("cls", "primary")
        self.rename_zone_btn.clicked.connect(self._on_rename_zone)
        rename_row.addWidget(self.rename_zone_btn)

        self.rotate_zone_btn = QPushButton("Rotate 90°")
        self.rotate_zone_btn.setProperty("cls", "secondary")
        self.rotate_zone_btn.clicked.connect(self._on_rotate_zone)
        rename_row.addWidget(self.rotate_zone_btn)

        self.delete_zone_btn = QPushButton("Delete")
        self.delete_zone_btn.setProperty("cls", "secondary")
        self.delete_zone_btn.clicked.connect(self._on_delete_zone)
        rename_row.addWidget(self.delete_zone_btn)
        right_layout.addLayout(rename_row)
        right_layout.addStretch()

        self.zones_dock = QDockWidget("Zones / Furniture", self.dock_host)
        self.zones_dock.setObjectName("zones_dock")
        self.zones_dock.setWidget(zones_widget)
        self.zones_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self.dock_host.addDockWidget(Qt.RightDockWidgetArea, self.zones_dock)
        view_menu.addAction(self.zones_dock.toggleViewAction())

        # --- Drawers panel ---
        drawers_widget = QWidget()
        right_layout = QVBoxLayout(drawers_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(10)

        drawers_hint = QLabel("Has drawers? Select a zone above (e.g. Dresser) and split it into named compartments so the app can be specific about which one an object was put in.")
        drawers_hint.setProperty("cls", "hint")
        drawers_hint.setWordWrap(True)
        right_layout.addWidget(drawers_hint)

        drawer_config_row = QHBoxLayout()
        drawer_config_row.setSpacing(8)
        self.drawer_count_input = QSpinBox()
        self.drawer_count_input.setRange(0, 8)
        self.drawer_count_input.setPrefix("Drawers ")
        drawer_config_row.addWidget(self.drawer_count_input)

        self.drawer_orientation_input = QComboBox()
        self.drawer_orientation_input.addItems(["Stacked (top-bottom)", "Side by side (left-right)"])
        drawer_config_row.addWidget(self.drawer_orientation_input)

        self.set_drawers_btn = QPushButton("Set Drawers")
        self.set_drawers_btn.setProperty("cls", "secondary")
        self.set_drawers_btn.clicked.connect(self._on_set_drawers)
        drawer_config_row.addWidget(self.set_drawers_btn)
        right_layout.addLayout(drawer_config_row)

        self.drawer_list = QListWidget()
        self.drawer_list.setMinimumHeight(50)
        self.drawer_list.setMaximumHeight(90)
        self.drawer_list.itemClicked.connect(self._on_drawer_list_clicked)
        right_layout.addWidget(self.drawer_list)

        drawer_rename_row = QHBoxLayout()
        drawer_rename_row.setSpacing(8)
        self.drawer_rename_input = QLineEdit()
        self.drawer_rename_input.setPlaceholderText("Rename selected drawer (e.g. Top Drawer)")
        drawer_rename_row.addWidget(self.drawer_rename_input)

        self.rename_drawer_btn = QPushButton("Rename")
        self.rename_drawer_btn.setProperty("cls", "primary")
        self.rename_drawer_btn.clicked.connect(self._on_rename_drawer)
        drawer_rename_row.addWidget(self.rename_drawer_btn)
        right_layout.addLayout(drawer_rename_row)
        right_layout.addStretch()

        self.drawers_dock = QDockWidget("Drawers", self.dock_host)
        self.drawers_dock.setObjectName("drawers_dock")
        self.drawers_dock.setWidget(drawers_widget)
        self.drawers_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self.dock_host.addDockWidget(Qt.RightDockWidgetArea, self.drawers_dock)
        view_menu.addAction(self.drawers_dock.toggleViewAction())

        # --- Detected Objects panel ---
        objects_widget = QWidget()
        right_layout = QVBoxLayout(objects_widget)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(10)

        self.object_list = QListWidget()
        self.object_list.setMinimumHeight(80)
        self.object_list.itemClicked.connect(self._on_object_list_clicked)
        right_layout.addWidget(self.object_list)

        object_row = QHBoxLayout()
        object_row.setSpacing(8)
        self.object_rename_input = QLineEdit()
        self.object_rename_input.setPlaceholderText("Rename selected object")
        object_row.addWidget(self.object_rename_input)

        self.rename_object_btn = QPushButton("Rename")
        self.rename_object_btn.setProperty("cls", "primary")
        self.rename_object_btn.clicked.connect(self._on_rename_object)
        object_row.addWidget(self.rename_object_btn)

        self.refresh_objects_btn = QPushButton("Refresh")
        self.refresh_objects_btn.setProperty("cls", "secondary")
        self.refresh_objects_btn.clicked.connect(self._refresh_object_list)
        object_row.addWidget(self.refresh_objects_btn)
        right_layout.addLayout(object_row)
        right_layout.addStretch()

        self.objects_dock = QDockWidget("Detected Objects", self.dock_host)
        self.objects_dock.setObjectName("objects_dock")
        self.objects_dock.setWidget(objects_widget)
        self.objects_dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        self.dock_host.addDockWidget(Qt.RightDockWidgetArea, self.objects_dock)
        view_menu.addAction(self.objects_dock.toggleViewAction())

        # Cameras/Zones/Drawers/Detected Objects are independent dock
        # panels - drag by their title bar to move or tab them together,
        # drag an edge to resize, or float/close them (reopen via the
        # "Panels" menu). Exposed as _room_docks so Panel Customization can
        # still pull each one out to the sidebar individually.
        self._room_docks: List[QDockWidget] = [
            self.cameras_dock, self.zones_dock, self.drawers_dock, self.objects_dock,
        ]

        # "Save Room" stays outside the dock area, always reachable no
        # matter how the panels get rearranged.
        outer.addWidget(self.dock_host, 1)

        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_btn = QPushButton("Save Room")
        self.save_btn.setProperty("cls", "primary")
        self.save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self.save_btn)
        outer.addLayout(save_row)

        self._selected_zone_index: Optional[int] = None
        self._selected_drawer_index: Optional[int] = None
        self._selected_camera_index: Optional[int] = None
        self._selected_object_id: Optional[int] = None
        self._updating_camera_list = False

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("cls", "muted")
        return lbl

    def _load_from_config(self):
        profile = self._active_profile()
        self.width_input.blockSignals(True)
        self.height_input.blockSignals(True)
        self.width_input.setValue(profile.width_m)
        self.height_input.setValue(profile.height_m)
        self.width_input.blockSignals(False)
        self.height_input.blockSignals(False)
        self.canvas.set_room_size(profile.width_m, profile.height_m)
        self.canvas.set_zones(self.zones)
        self.canvas.set_cameras(self.cameras)

    def _on_size_changed(self):
        self.canvas.set_room_size(self.width_input.value(), self.height_input.value())

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
        profile = self._active_profile()
        self.zones = [dict(z) for z in profile.zones]
        self.cameras = [dict(c) for c in profile.cameras]
        self._selected_zone_index = None
        self._selected_drawer_index = None
        self._selected_camera_index = None
        self.zone_rename_input.clear()
        self.camera_rename_input.clear()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self._refresh_camera_list()
        self._refresh_object_list()
        self.status_label.setText(f"Editing \"{profile.name}\".")

    def _on_new_room(self):
        name, ok = QInputDialog.getText(self, "New Room", "Room name:")
        if not ok or not name.strip():
            return
        name = name.strip()

        new_profile = RoomConfig(
            id=uuid.uuid4().hex[:8],
            name=name,
            cameras=[],
            zones=[],
        )
        self.profiles.append(new_profile)
        save_room_profiles(self.profiles)
        self._active_profile_index = len(self.profiles) - 1
        self._refresh_profile_list()
        self._on_profile_selected(self._active_profile_index)
        self.status_label.setText(
            f"Created \"{name}\". Set its size, add its own cameras, then Save Room."
        )
        self.room_updated.emit()

    def _on_rename_room(self):
        profile = self._active_profile()
        new_name, ok = QInputDialog.getText(self, "Rename Room", "Room name:", text=profile.name)
        if not ok or not new_name.strip():
            return
        profile.name = new_name.strip()
        save_room_profiles(self.profiles)
        self._refresh_profile_list()
        self.status_label.setText(f"Renamed to \"{profile.name}\".")
        self.room_updated.emit()

    def _on_delete_room(self):
        if len(self.profiles) <= 1:
            self.status_label.setText("Can't delete the only room.")
            return
        profile = self._active_profile()
        confirm = QMessageBox.question(
            self, "Delete Room",
            f"Delete \"{profile.name}\" and stop tracking its cameras? "
            "Its item history is kept, just no longer shown as an active room.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        del self.profiles[self._active_profile_index]
        self._active_profile_index = 0
        save_room_profiles(self.profiles)
        self._refresh_profile_list()
        self._on_profile_selected(0)
        self.status_label.setText(f"Deleted \"{profile.name}\".")
        self.room_updated.emit()

    def _on_draw_zone_clicked(self, checked: bool):
        if checked and not self.zone_name_input.text().strip():
            self.status_label.setText("Enter a zone name first (e.g. Bed).")
            self.draw_zone_btn.setChecked(False)
            return
        self.canvas.set_draw_mode(checked)
        if checked:
            self.status_label.setText(f"Drag on the room to place \"{self.zone_name_input.text().strip()}\".")
        else:
            self.status_label.setText("")

    def _on_zone_drawn(self, x1: float, y1: float, x2: float, y2: float):
        name = self.zone_name_input.text().strip() or f"Zone {len(self.zones) + 1}"
        self.zones.append({"name": name, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self.zone_name_input.clear()
        self.draw_zone_btn.setChecked(False)
        self.canvas.set_draw_mode(False)
        self.status_label.setText(f"Added zone \"{name}\". Don't forget to Save Room.")

    def _on_scan_room(self):
        db = Database()
        active_items = db.get_active_items(room_id=self._active_profile().id)
        db.close()

        temp_config = RoomConfig(
            width_m=self.width_input.value(),
            height_m=self.height_input.value(),
            cameras=self.cameras,
            zones=self.zones,
        )
        mapper = ItemMapper(temp_config)
        room_w, room_h = temp_config.width_m, temp_config.height_m

        added, updated = 0, 0
        for det in active_items:
            label = (det.get("label") or "").strip().lower()
            size = FURNITURE_SIZES_M.get(label)
            if size is None:
                continue

            room_x, room_y = mapper.pixel_to_room(det["zone_x"], det["zone_y"], det["camera_id"])
            half_w, half_h = size[0] / 2.0, size[1] / 2.0
            x1, x2 = _clamp_axis(room_x - half_w, room_x + half_w, room_w)
            y1, y2 = _clamp_axis(room_y - half_h, room_y + half_h, room_h)

            zone_name = "TV" if label == "tv" else label.title()
            existing = next((z for z in self.zones if z["name"].lower() == zone_name.lower()), None)
            if existing:
                existing["x1"], existing["y1"], existing["x2"], existing["y2"] = x1, y1, x2, y2
                updated += 1
            else:
                self.zones.append({"name": zone_name, "x1": x1, "y1": y1, "x2": x2, "y2": y2})
                added += 1

        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()

        if added or updated:
            self.status_label.setText(
                f"Scanned room: added {added}, updated {updated} zone(s) from what the cameras "
                "can currently see. Don't forget to Save Room."
            )
        else:
            self.status_label.setText(
                "No recognizable furniture currently in camera view. Make sure cameras are "
                "added, enabled, and pointed at the room, then try again."
            )

    def _refresh_zone_list(self):
        self.zone_list.clear()
        for i, zone in enumerate(self.zones):
            drawer_count = len(zone.get("drawers", []))
            tag = f", {drawer_count} drawers" if drawer_count else ""
            text = (f"{zone['name']}{tag}  "
                    f"({zone['x1']:.1f},{zone['y1']:.1f}) -> ({zone['x2']:.1f},{zone['y2']:.1f})")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, i)
            self.zone_list.addItem(item)

    def _on_zone_list_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        self._selected_zone_index = index
        self.canvas.selected_index = index
        self.canvas.update()
        self.zone_rename_input.setText(self.zones[index]["name"])
        self._refresh_drawer_list()

    def _on_zone_selected_in_canvas(self, index: int):
        self._selected_zone_index = index
        self.zone_list.setCurrentRow(index)
        self.zone_rename_input.setText(self.zones[index]["name"])
        self._refresh_drawer_list()

    def _on_zone_drag_finished(self):
        self._refresh_zone_list()
        if self._selected_zone_index is not None:
            self.zone_list.setCurrentRow(self._selected_zone_index)
        self.status_label.setText("Updated zone. Don't forget to Save Room.")

    def _on_rename_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to rename first.")
            return
        new_name = self.zone_rename_input.text().strip()
        if not new_name:
            return
        self.zones[self._selected_zone_index]["name"] = new_name
        self.canvas.set_zones(self.zones)
        self.canvas.selected_index = self._selected_zone_index
        self._refresh_zone_list()
        self.zone_list.setCurrentRow(self._selected_zone_index)
        self.status_label.setText(f"Renamed zone to \"{new_name}\". Don't forget to Save Room.")

    def _on_rotate_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to rotate first.")
            return

        zone = self.zones[self._selected_zone_index]
        x1, y1, x2, y2 = zone["x1"], zone["y1"], zone["x2"], zone["y2"]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        half_w, half_h = (x2 - x1) / 2.0, (y2 - y1) / 2.0

        room_w, room_h = self.width_input.value(), self.height_input.value()
        nx1, nx2 = _clamp_axis(cx - half_h, cx + half_h, room_w)
        ny1, ny2 = _clamp_axis(cy - half_w, cy + half_w, room_h)

        zone["drawers"] = _rotate_drawers_cw(zone.get("drawers", []), x1, y1, x2, y2, nx1, ny1, nx2, ny2)
        zone["x1"], zone["y1"], zone["x2"], zone["y2"] = nx1, ny1, nx2, ny2

        self.canvas.set_zones(self.zones)
        self.canvas.selected_index = self._selected_zone_index
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self.zone_list.setCurrentRow(self._selected_zone_index)
        self.status_label.setText(f"Rotated \"{zone['name']}\" 90°. Don't forget to Save Room.")

    def _on_delete_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to delete first.")
            return
        removed = self.zones.pop(self._selected_zone_index)
        self._selected_zone_index = None
        self.zone_rename_input.clear()
        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self.status_label.setText(f"Deleted zone \"{removed['name']}\". Don't forget to Save Room.")

    def _refresh_drawer_list(self):
        self.drawer_list.clear()
        self._selected_drawer_index = None
        self.drawer_rename_input.clear()

        if self._selected_zone_index is None:
            self.drawer_count_input.blockSignals(True)
            self.drawer_count_input.setValue(0)
            self.drawer_count_input.blockSignals(False)
            return

        drawers = self.zones[self._selected_zone_index].get("drawers", [])
        self.drawer_count_input.blockSignals(True)
        self.drawer_count_input.setValue(len(drawers))
        self.drawer_count_input.blockSignals(False)
        for i, drawer in enumerate(drawers):
            item = QListWidgetItem(drawer["name"])
            item.setData(Qt.UserRole, i)
            self.drawer_list.addItem(item)

    def _on_set_drawers(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone first (e.g. Dresser), then set its drawers.")
            return

        zone = self.zones[self._selected_zone_index]
        count = self.drawer_count_input.value()

        if count == 0:
            zone["drawers"] = []
            self.canvas.set_zones(self.zones)
            self._refresh_drawer_list()
            self._refresh_zone_list()
            self.zone_list.setCurrentRow(self._selected_zone_index)
            self.status_label.setText(f"Cleared drawers on \"{zone['name']}\". Don't forget to Save Room.")
            return

        stacked = self.drawer_orientation_input.currentIndex() == 0
        x1, y1, x2, y2 = zone["x1"], zone["y1"], zone["x2"], zone["y2"]
        drawers = []
        if stacked:
            step = (y2 - y1) / count
            for i in range(count):
                drawers.append({
                    "name": f"Drawer {i + 1}",
                    "x1": x1, "x2": x2,
                    "y1": y1 + i * step, "y2": y1 + (i + 1) * step,
                })
        else:
            step = (x2 - x1) / count
            for i in range(count):
                drawers.append({
                    "name": f"Drawer {i + 1}",
                    "x1": x1 + i * step, "x2": x1 + (i + 1) * step,
                    "y1": y1, "y2": y2,
                })

        zone["drawers"] = drawers
        self.canvas.set_zones(self.zones)
        self._refresh_drawer_list()
        self._refresh_zone_list()
        self.zone_list.setCurrentRow(self._selected_zone_index)
        self.status_label.setText(
            f"Set {count} drawers on \"{zone['name']}\". Rename them below, then Save Room."
        )

    def _on_drawer_list_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        self._selected_drawer_index = index
        zone = self.zones[self._selected_zone_index]
        self.drawer_rename_input.setText(zone["drawers"][index]["name"])

    def _on_rename_drawer(self):
        if self._selected_zone_index is None or self._selected_drawer_index is None:
            self.status_label.setText("Select a drawer to rename first.")
            return
        new_name = self.drawer_rename_input.text().strip()
        if not new_name:
            return
        drawer_index = self._selected_drawer_index
        zone = self.zones[self._selected_zone_index]
        zone["drawers"][drawer_index]["name"] = new_name
        self.canvas.set_zones(self.zones)
        self._refresh_drawer_list()
        self.drawer_list.setCurrentRow(drawer_index)
        self._selected_drawer_index = drawer_index
        self.status_label.setText(f"Renamed drawer to \"{new_name}\". Don't forget to Save Room.")

    def _on_save(self):
        profile = self._active_profile()
        profile.width_m = self.width_input.value()
        profile.height_m = self.height_input.value()
        profile.zones = self.zones
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)
        self.status_label.setText(f"Saved \"{profile.name}\".")
        self.room_updated.emit()

    def _refresh_camera_list(self):
        self._updating_camera_list = True
        self.camera_list.clear()
        for i, cam in enumerate(self.cameras):
            tag = ", 360°" if cam.get("is_360") else ""
            text = (f"{cam['label']}  (id {cam['id']}{tag}) "
                    f"@ ({cam['x']:.1f}, {cam['y']:.1f})")
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if cam.get("enabled") else Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.camera_list.addItem(item)
        self._updating_camera_list = False

    def _add_camera(self, cam_id: int, label: str = ""):
        if any(c["id"] == cam_id for c in self.cameras):
            self.status_label.setText(f"Camera ID {cam_id} is already in the list.")
            return
        label = label.strip() or f"Camera {cam_id}"
        self.cameras.append({
            "id": cam_id,
            "label": label,
            "enabled": True,
            "x": self.width_input.value() / 2.0,
            "y": self.height_input.value() / 2.0,
            "is_360": False,
        })
        self.canvas.set_cameras(self.cameras)
        self._refresh_camera_list()
        self.status_label.setText(f"Added \"{label}\". Drag it into place, then Save Room.")

    def _on_add_camera(self):
        self._add_camera(self.camera_id_input.value(), self.camera_label_input.text())
        self.camera_label_input.clear()

    def _on_discover_cameras(self):
        if self._camera_discovery.is_scanning():
            return
        self.discover_cameras_btn.setEnabled(False)
        self.status_label.setText("Scanning for cameras...")
        exclude_ids = {c["id"] for c in self.cameras}
        self._camera_discovery.start_scan(
            max_index=10, exclude_ids=exclude_ids,
            progress_callback=self._camera_discovery_progress.emit,
            done_callback=self._camera_discovery_finished.emit,
        )

    def _on_camera_discovery_progress(self, message: str):
        self.status_label.setText(message)

    def _on_camera_discovery_finished(self, found: list):
        self.discover_cameras_btn.setEnabled(True)
        if not found:
            self.status_label.setText(
                "No additional cameras found. Already-added or in-use IDs are skipped."
            )
            return

        menu = QMenu(self)
        for info in found:
            action = menu.addAction(f"Camera {info['id']} ({info['width']}x{info['height']})")
            action.triggered.connect(lambda checked, cid=info["id"]: self._add_camera(cid))
        self.status_label.setText(f"Found {len(found)} camera(s) - pick one to add.")
        menu.exec_(self.discover_cameras_btn.mapToGlobal(self.discover_cameras_btn.rect().bottomLeft()))

    def _on_camera_list_clicked(self, item: QListWidgetItem):
        index = item.data(Qt.UserRole)
        self._selected_camera_index = index
        self.canvas.selected_camera_index = index
        self.canvas.selected_index = None
        self.canvas.update()
        self.camera_rename_input.setText(self.cameras[index]["label"])

    def _on_camera_selected_in_canvas(self, index: int):
        self._selected_camera_index = index
        self.camera_list.setCurrentRow(index)
        self.camera_rename_input.setText(self.cameras[index]["label"])

    def _on_camera_item_changed(self, item: QListWidgetItem):
        if self._updating_camera_list:
            return
        index = item.data(Qt.UserRole)
        if index is None:
            return
        self.cameras[index]["enabled"] = item.checkState() == Qt.Checked
        self.canvas.set_cameras(self.cameras)
        self.status_label.setText("Don't forget to Save Room.")

    def _on_rename_camera(self):
        if self._selected_camera_index is None:
            self.status_label.setText("Select a camera to rename first.")
            return
        new_label = self.camera_rename_input.text().strip()
        if not new_label:
            return
        self.cameras[self._selected_camera_index]["label"] = new_label
        self.canvas.set_cameras(self.cameras)
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(self._selected_camera_index)
        self.status_label.setText(f"Renamed camera to \"{new_label}\". Don't forget to Save Room.")

    def _on_toggle_360(self):
        if self._selected_camera_index is None:
            self.status_label.setText("Select a camera first.")
            return
        cam = self.cameras[self._selected_camera_index]
        cam["is_360"] = not cam.get("is_360", False)
        self.canvas.set_cameras(self.cameras)
        self._refresh_camera_list()
        self.camera_list.setCurrentRow(self._selected_camera_index)
        state = "a 360°" if cam["is_360"] else "a standard"
        self.status_label.setText(f"\"{cam['label']}\" is now {state} camera. Don't forget to Save Room.")

    def _on_remove_camera(self):
        if self._selected_camera_index is None:
            self.status_label.setText("Select a camera to remove first.")
            return
        removed = self.cameras.pop(self._selected_camera_index)
        self._selected_camera_index = None
        self.camera_rename_input.clear()
        self.canvas.set_cameras(self.cameras)
        self._refresh_camera_list()
        self.status_label.setText(f"Removed \"{removed['label']}\". Don't forget to Save Room.")

    def _on_camera_moved(self, index: int, x: float, y: float):
        self.status_label.setText(f"{self.cameras[index]['label']} at ({x:.2f}m, {y:.2f}m)")

    def _on_camera_drag_finished(self):
        self._refresh_camera_list()
        if self._selected_camera_index is not None:
            self.camera_list.setCurrentRow(self._selected_camera_index)
        self.status_label.setText(self.status_label.text() + " - don't forget to Save Room.")

    def _refresh_object_list(self):
        db = Database()
        items = db.get_recent_items(100, room_id=self._active_profile().id)
        db.close()

        self.object_list.clear()
        for item in items:
            label = item.get("label", "unknown")
            cam = item.get("camera_id", 0)
            zone_name = item.get("zone_name")
            last_seen = (item.get("last_seen") or "")[:16]
            text = f"{label}  (cam {cam})"
            if zone_name:
                text += f"  {zone_name}"
            if last_seen:
                text += f"  - {last_seen}"
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.UserRole, item)
            self.object_list.addItem(list_item)

    def _on_object_list_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        self._selected_object_id = data.get("id")
        self.object_rename_input.setText(data.get("label", ""))

    def _on_rename_object(self):
        if self._selected_object_id is None:
            self.status_label.setText("Select an object to rename first.")
            return
        new_label = self.object_rename_input.text().strip()
        if not new_label:
            return
        db = Database()
        db.rename_item(self._selected_object_id, new_label)
        db.close()
        self._refresh_object_list()
        self.status_label.setText(f"Renamed object to \"{new_label}\".")
