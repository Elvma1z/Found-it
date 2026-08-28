import math
import uuid
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QDoubleSpinBox, QSpinBox, QComboBox,
    QInputDialog, QMessageBox, QMenu, QScrollArea,
    QMainWindow, QDockWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QByteArray, QPointF, QRectF
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QPolygonF
from typing import List, Optional, Tuple

from found_it.gui.room_map import _facing_wedge_path
from found_it.gui.icons import get_icon, ICON_SIZE

from found_it.utils.room_profiles import load_room_profiles, save_room_profiles
from found_it.storage.database import Database
from found_it.storage.models import RoomConfig
from found_it.detection.item_mapper import ItemMapper
from found_it.utils.themes import get_palette, widget_qss, repolish
from found_it.utils.app_settings import load_app_settings, save_app_settings

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

FURNITURE_TYPES = [
    "Other", "Bed", "Dresser", "Closet", "Nightstand", "Desk", "Shelf",
    "Cabinet", "Couch", "Chair", "Table", "TV", "Refrigerator",
]

# A piece of furniture with no height is just a flat rectangle, and guessing
# one would draw the user a room that isn't theirs - so height starts unset
# (0.0) and the 3D view refuses to open until every piece has a real one.
DEFAULT_WALL_HEIGHT_M = 2.5
CAMERA_MOUNT_HEIGHT_M = 2.0


# Room Setup is shown in imperial, but every stored measurement stays in
# metres - the detector, the item mapper and the Room Tracker map all work in
# them, and so do already-saved room profiles. Feet and inches exist purely at
# the display/input boundary, converted by the helpers below.
M_PER_FT = 0.3048
M_PER_IN = 0.0254


def m_to_ft(metres: float) -> float:
    return metres / M_PER_FT


def ft_to_m(feet: float) -> float:
    return feet * M_PER_FT


def m_to_in(metres: float) -> float:
    return metres / M_PER_IN


def in_to_m(inches: float) -> float:
    return inches * M_PER_IN


def format_ft_in(metres: float) -> str:
    """Render a length as feet and inches - 0.85m -> 2' 9\".

    Heights read naturally this way where decimal feet ("2.79 ft") do not,
    so it is used for every height the user reads back.
    """
    total_in = int(round(metres / M_PER_IN))
    feet, inches = divmod(total_in, 12)
    if feet and inches:
        return f"{feet}' {inches}\""
    if feet:
        return f"{feet}'"
    return f"{inches}\""


def zone_height(zone: dict) -> float:
    """A zone's height off the floor in metres, or 0.0 when it hasn't been
    set yet. Note this is not the room's own height_m, which is its depth
    (the y axis of the floor plan) - these live on different objects."""
    try:
        return float(zone.get("height_m") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def zones_missing_height(zones: List[dict]) -> List[str]:
    """Names of the furniture still without a height, in list order."""
    return [z.get("name", "Unnamed") for z in zones if zone_height(z) <= 0.0]


def _iso_point(x: float, y: float, z: float, yaw: float, elev: float) -> Tuple[float, float, float]:
    """Project a room-space point (metres, z = up) for the 3D view.

    Returns (u, v, depth): u/v are unscaled screen offsets, and depth grows
    towards the viewer so it doubles as the painter's-algorithm sort key.
    """
    rx = x * math.cos(yaw) - y * math.sin(yaw)
    ry = x * math.sin(yaw) + y * math.cos(yaw)
    return rx, ry * math.sin(elev) - z * math.cos(elev), ry


def _faces_viewer(nx: float, ny: float, yaw: float) -> bool:
    """Whether an outward face normal (nx, ny) points towards the viewer -
    used to draw only the sides of a box that can actually be seen."""
    return nx * math.sin(yaw) + ny * math.cos(yaw) > 0


def _shade(color: QColor, factor: float, alpha: int = 255) -> QColor:
    """Darken a face colour so a box's top and sides read as lit from
    different angles instead of as one flat silhouette."""
    shaded = QColor(int(color.red() * factor), int(color.green() * factor),
                    int(color.blue() * factor))
    shaded.setAlpha(alpha)
    return shaded


CAMERA_COLORS = {
    0: QColor(255, 100, 100),
    1: QColor(100, 100, 255),
    2: QColor(100, 255, 180),
}
CAMERA_FALLBACK_COLORS = [
    QColor(255, 180, 60), QColor(200, 100, 255), QColor(255, 100, 200),
    QColor(120, 220, 255), QColor(180, 255, 100),
]


def _guess_furniture_type(name: str) -> str:
    """Best-effort default for a new zone's Type field, matched against the
    known FURNITURE_TYPES by name (e.g. "Dresser" -> "Dresser") so the
    settings panel doesn't just show "Other" for every obviously-named item."""
    lowered = name.strip().lower()
    for t in FURNITURE_TYPES:
        if t.lower() == lowered:
            return t
    return "Other"


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
    MIN_ELEV_DEG = 8.0
    MAX_ELEV_DEG = 85.0

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
        # 3D view: off by default, and view-only while on (see set_view_3d).
        self.view_3d = False
        self.yaw_deg = 30.0
        self.elev_deg = 35.0
        self._orbit_last: Optional[Tuple[int, int]] = None

    def set_view_3d(self, enabled: bool):
        """Switch between the flat floor plan and the extruded 3D room.

        Turning it on cancels any in-progress zone drawing: once the room is
        tilted a click no longer maps to a single point on the floor, so
        laying out furniture stays a 2D job.
        """
        self.view_3d = enabled
        self._orbit_last = None
        if enabled:
            self.draw_mode = False
            self._drag_start = None
            self._drag_current = None
        self.update()

    def _wall_height(self) -> float:
        """Room height for the 3D shell - tall enough to clear the tallest
        piece of furniture in it, so nothing pokes through the walls."""
        tallest = max((zone_height(z) for z in self.zones), default=0.0)
        return max(DEFAULT_WALL_HEIGHT_M, tallest + 0.3)

    def _iso_transform(self) -> Tuple[float, float, float, float, float]:
        """Scale/offset that fits the whole room box on screen at the current
        orbit angles, plus those angles in radians."""
        yaw = math.radians(self.yaw_deg)
        elev = math.radians(self.elev_deg)
        wall = self._wall_height()
        us, vs = [], []
        for x in (0.0, self.room_width):
            for y in (0.0, self.room_height):
                for z in (0.0, wall):
                    u, v, _ = _iso_point(x, y, z, yaw, elev)
                    us.append(u)
                    vs.append(v)
        span_u = (max(us) - min(us)) or 1.0
        span_v = (max(vs) - min(vs)) or 1.0
        draw_w, draw_h = self._draw_rect()
        draw_w, draw_h = max(draw_w, 1), max(draw_h, 1)
        scale = min(draw_w / span_u, draw_h / span_v)
        ox = self._padding + (draw_w - span_u * scale) / 2.0 - min(us) * scale
        oy = self._padding + (draw_h - span_v * scale) / 2.0 - min(vs) * scale
        return scale, ox, oy, yaw, elev

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
        if self.view_3d:
            self._orbit_last = (event.x(), event.y())
            self.setFocus()
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
        if self.view_3d:
            if self._orbit_last is None:
                return
            last_x, last_y = self._orbit_last
            self.yaw_deg = (self.yaw_deg + (event.x() - last_x) * 0.5) % 360.0
            self.elev_deg = max(self.MIN_ELEV_DEG, min(
                self.MAX_ELEV_DEG, self.elev_deg - (event.y() - last_y) * 0.35))
            self._orbit_last = (event.x(), event.y())
            self.update()
            return
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
        if self.view_3d:
            self._orbit_last = None
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.view_3d:
            self._paint_3d(painter)
        else:
            self._paint_2d(painter)
        painter.end()

    def _paint_2d(self, painter):
        p = self.palette
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

            if cam.get("is_180"):
                # Shows what this camera can (and can't) actually see, so
                # its coverage gap is obvious while placing it - not just
                # discovered later on the Room Tracker map.
                wedge_r = min(room_px_w, room_px_h) // 2 - 10
                painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 70), 1, Qt.DotLine))
                painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 25)))
                painter.drawPath(_facing_wedge_path(cx, cy, wedge_r, cam.get("facing_deg", 0.0)))

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

    def _paint_3d(self, painter):
        """The same room drawn as a box, with every piece of furniture stood
        up to the height the user gave it. Faces are depth-sorted back to
        front (painter's algorithm) so nearer furniture covers what is behind
        it - that overlap is what makes the layout read as a room instead of
        a plan."""
        p = self.palette
        scale, ox, oy, yaw, elev = self._iso_transform()
        wall = self._wall_height()
        room_w, room_h = self.room_width, self.room_height

        def pt(x: float, y: float, z: float = 0.0) -> QPointF:
            u, v, _ = _iso_point(x, y, z, yaw, elev)
            return QPointF(ox + u * scale, oy + v * scale)

        def poly(*corners) -> QPolygonF:
            return QPolygonF([pt(*c) for c in corners])

        def depth_of(x: float, y: float) -> float:
            return x * math.sin(yaw) + y * math.cos(yaw)

        border = QColor(p["border"])
        accent = QColor(p["accent"])
        accent_hover = QColor(p["accent_hover"])

        # Only the walls facing away from the viewer, so the room reads as a
        # box being looked into rather than a sealed crate.
        for nx, ny, corners in (
            (-1, 0, ((0, 0, 0), (0, room_h, 0), (0, room_h, wall), (0, 0, wall))),
            (1, 0, ((room_w, 0, 0), (room_w, room_h, 0), (room_w, room_h, wall), (room_w, 0, wall))),
            (0, -1, ((0, 0, 0), (room_w, 0, 0), (room_w, 0, wall), (0, 0, wall))),
            (0, 1, ((0, room_h, 0), (room_w, room_h, 0), (room_w, room_h, wall), (0, room_h, wall))),
        ):
            if _faces_viewer(nx, ny, yaw):
                continue
            painter.setPen(QPen(border, 1))
            painter.setBrush(QBrush(_shade(QColor(p["panel"]), 1.0, 110)))
            painter.drawPolygon(poly(*corners))

        painter.setPen(QPen(border, 2))
        painter.setBrush(QBrush(QColor(p["bg"])))
        painter.drawPolygon(poly((0, 0, 0), (room_w, 0, 0), (room_w, room_h, 0), (0, room_h, 0)))

        painter.setPen(QPen(border, 1, Qt.DashLine))
        for i in range(1, 4):
            painter.drawLine(pt(room_w * i / 4, 0), pt(room_w * i / 4, room_h))
            painter.drawLine(pt(0, room_h * i / 4), pt(room_w, room_h * i / 4))

        # Camera coverage lies flat on the floor, so it goes down before any
        # furniture is stood up on top of it.
        for cam in self.cameras:
            if not cam.get("is_180"):
                continue
            color = _camera_color(cam.get("id", 0))
            cam_x, cam_y = cam.get("x", 0.0), cam.get("y", 0.0)
            radius_m = min(room_w, room_h) / 2.0
            facing = math.radians(cam.get("facing_deg", 0.0))
            corners = [(cam_x, cam_y, 0.0)]
            for i in range(25):
                ang = facing - math.pi / 2 + math.pi * i / 24
                corners.append((cam_x + radius_m * math.cos(ang),
                                cam_y + radius_m * math.sin(ang), 0.0))
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 70), 1, Qt.DotLine))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 22)))
            painter.drawPolygon(poly(*corners))

        def draw_zone(index: int):
            zone = self.zones[index]
            x1, y1, x2, y2 = zone["x1"], zone["y1"], zone["x2"], zone["y2"]
            zh = zone_height(zone)
            selected = index == self.selected_index
            base = accent_hover if selected else accent

            for nx, ny, corners in (
                (-1, 0, ((x1, y1, 0), (x1, y2, 0), (x1, y2, zh), (x1, y1, zh))),
                (1, 0, ((x2, y1, 0), (x2, y2, 0), (x2, y2, zh), (x2, y1, zh))),
                (0, -1, ((x1, y1, 0), (x2, y1, 0), (x2, y1, zh), (x1, y1, zh))),
                (0, 1, ((x1, y2, 0), (x2, y2, 0), (x2, y2, zh), (x1, y2, zh))),
            ):
                if not _faces_viewer(nx, ny, yaw):
                    continue
                painter.setPen(QPen(_shade(base, 0.45), 1))
                painter.setBrush(QBrush(_shade(base, 0.72 if nx else 0.52, 235)))
                painter.drawPolygon(poly(*corners))

            painter.setPen(QPen(base.lighter(130) if selected else base, 2 if selected else 1))
            painter.setBrush(QBrush(_shade(base, 1.0, 215)))
            painter.drawPolygon(poly((x1, y1, zh), (x2, y1, zh), (x2, y2, zh), (x1, y2, zh)))

            for drawer in zone.get("drawers", []):
                painter.setPen(QPen(QColor(255, 210, 90, 200), 1, Qt.DotLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawPolygon(poly(
                    (drawer["x1"], drawer["y1"], zh), (drawer["x2"], drawer["y1"], zh),
                    (drawer["x2"], drawer["y2"], zh), (drawer["x1"], drawer["y2"], zh),
                ))

            center = pt((x1 + x2) / 2.0, (y1 + y2) / 2.0, zh)
            painter.setPen(QPen(QColor(p["text"]), 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(
                QRectF(center.x() - 75, center.y() - 9, 150, 18), Qt.AlignCenter,
                f"{zone.get('name', 'Zone')} - {format_ft_in(zh)}",
            )

        def draw_camera(index: int):
            cam = self.cameras[index]
            cam_x, cam_y = cam.get("x", 0.0), cam.get("y", 0.0)
            color = _camera_color(cam.get("id", 0))
            alpha = 255 if cam.get("enabled") else 90
            mount = min(CAMERA_MOUNT_HEIGHT_M, wall)
            base_pt, top_pt = pt(cam_x, cam_y, 0.0), pt(cam_x, cam_y, mount)

            # A stem down to the floor - without it a marker floating at
            # mount height gives no clue where in the room it actually sits.
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(),
                                       min(alpha, 140)), 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(base_pt, top_pt)

            if index == self.selected_camera_index:
                painter.setPen(QPen(accent_hover, 2, Qt.DashLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(top_pt, 13.0, 13.0)

            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), min(alpha, 130))))
            painter.drawEllipse(top_pt, 8.0, 8.0)

            text_color = QColor(p["text"])
            text_color.setAlpha(alpha)
            painter.setPen(QPen(text_color, 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(int(top_pt.x()) + 12, int(top_pt.y()) + 4,
                             cam.get("label", f"Camera {cam.get('id', 0)}"))

        drawables = [
            (depth_of((z["x1"] + z["x2"]) / 2.0, (z["y1"] + z["y2"]) / 2.0), draw_zone, i)
            for i, z in enumerate(self.zones)
        ] + [
            (depth_of(c.get("x", 0.0), c.get("y", 0.0)), draw_camera, i)
            for i, c in enumerate(self.cameras)
        ]
        drawables.sort(key=lambda entry: entry[0])
        for _, draw, index in drawables:
            draw(index)

        painter.setPen(QPen(QColor(p["text_faint"]), 1))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(8, self.height() - 8,
                         "3D view - drag to orbit. Switch back to 2D to move or resize anything.")

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


# Room Setup's panels are pinned the same way Room Tracker's are: no Movable,
# no Floatable. Collapsing (the arrow in each title bar) and hiding via the
# View menu still work - neither moves a panel out of its slot. Rearranging
# happens in Settings > Customization.
LOCKED_DOCK_FEATURES = QDockWidget.DockWidgetClosable


class _CollapsibleDockTitle(QWidget):
    """Custom title bar for a sidebar dock: click the arrow to collapse the
    dock down to just this header, freeing up vertical space for its
    siblings instead of every dock fighting over a fixed-size split (which
    is what made their button rows overlap). The rest of the bar is inert -
    docks are locked in place (LOCKED_DOCK_FEATURES) outside Customization."""

    def __init__(self, title: str, dock: QDockWidget, dock_host: QMainWindow, parent=None):
        super().__init__(parent)
        self.dock = dock
        self.dock_host = dock_host
        self._expanded = True
        self._palette = {}
        self._last_expanded_height: Optional[int] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setIconSize(ICON_SIZE)
        self.toggle_btn.setFlat(True)
        self.toggle_btn.setFixedWidth(18)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_btn)

        self.title_label = QLabel(title)
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_label.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.title_label)
        layout.addStretch()

    def mousePressEvent(self, event):
        # Clicking the title text (not just the arrow) also toggles - only
        # the empty stretch area is left free for the native drag handle.
        if event.button() == Qt.LeftButton and self.title_label.geometry().contains(event.pos()):
            self.toggle()
            return
        super().mousePressEvent(event)

    def toggle(self):
        # Constraining the dock's max height (not hiding its content widget)
        # is deliberate - QMainWindow's dock layout recomputes the whole
        # sidebar column's width off of each dock's *visible* size hint, so
        # hiding a dock's content instead of just capping its height was
        # collapsing the entire sidebar's width along with it.
        self._expanded = not self._expanded
        self.toggle_btn.setIcon(get_icon(
            "chevron-down" if self._expanded else "chevron-right",
            self._palette.get("text", "#e0e0e0"),
        ))
        header_h = self.sizeHint().height()

        if self._expanded:
            self.dock.setMaximumHeight(16777215)
            # Removing the max height cap doesn't by itself make the dock
            # grow back - the splitter just leaves it at its collapsed size
            # until something asks for more, which is why reopening a
            # section wasn't pushing the ones below it back down. Explicitly
            # resizing it back to (roughly) what it was before forces that
            # redistribution.
            target = self._last_expanded_height or max(header_h * 6, 200)
            self.dock_host.resizeDocks([self.dock], [target], Qt.Vertical)
        else:
            if self.dock.height() > header_h:
                self._last_expanded_height = self.dock.height()
            self.dock.setMaximumHeight(header_h)
            self.dock_host.resizeDocks([self.dock], [header_h], Qt.Vertical)

    def apply_theme(self, p: dict):
        self._palette = p
        self.setStyleSheet(
            f"background: {p['header']}; "
            f"border-top: 1px solid {p['border']}; border-bottom: 1px solid {p['border']};"
        )
        self.title_label.setStyleSheet(f"color: {p['text']}; background: transparent;")
        self.toggle_btn.setStyleSheet("""
            QPushButton { border: none; background: transparent; }
        """)
        self.toggle_btn.setIcon(get_icon("chevron-down" if self._expanded else "chevron-right", p["text"]))


class _HeightRequiredSplash(QWidget):
    """Error splash covering the whole Room Setup tab when 3D is switched on
    while some furniture still has no height.

    Deliberately not a QMessageBox: it names every piece that is missing one,
    so the fix is a list to work through rather than a dialog that has to be
    dismissed before the user can go hunting for which piece was the problem.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(30, 30, 30, 30)
        outer.addStretch()

        row = QHBoxLayout()
        row.addStretch()

        self.card = QFrame()
        self.card.setObjectName("splash_card")
        self.card.setMinimumWidth(380)
        self.card.setMaximumWidth(560)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(22, 20, 22, 18)
        card_layout.setSpacing(10)

        self.title_label = QLabel("Can't switch to 3D yet")
        self.title_label.setFont(QFont("Segoe UI", 15, QFont.Bold))
        card_layout.addWidget(self.title_label)

        self.body_label = QLabel()
        self.body_label.setWordWrap(True)
        card_layout.addWidget(self.body_label)

        self.list_label = QLabel()
        self.list_label.setWordWrap(True)
        card_layout.addWidget(self.list_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.dismiss_btn = QPushButton("Got it")
        self.dismiss_btn.setProperty("cls", "primary")
        self.dismiss_btn.clicked.connect(self.hide)
        button_row.addWidget(self.dismiss_btn)
        card_layout.addLayout(button_row)

        row.addWidget(self.card)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))
        painter.end()

    def mousePressEvent(self, event):
        # Clicking the dimmed backdrop dismisses. Labels and frames ignore
        # mouse presses, so a click on the card itself would otherwise
        # propagate up to here and close the splash mid-read.
        if not self.card.geometry().contains(event.pos()):
            self.hide()

    def apply_theme(self, p: dict):
        self.setStyleSheet(widget_qss(p) + f"""
            QFrame#splash_card {{
                background: {p['panel']};
                border: 1px solid {p['border']};
                border-radius: 8px;
            }}
        """)
        self.title_label.setStyleSheet("color: #ff8080; background: transparent;")
        self.body_label.setStyleSheet(f"color: {p['text']}; background: transparent;")
        self.list_label.setStyleSheet(f"color: {p['text_dim']}; background: transparent;")
        repolish(self)

    def show_error(self, missing_names: List[str]):
        count = len(missing_names)
        is_one = count == 1
        self.body_label.setText(
            f"{count} {'piece' if is_one else 'pieces'} of furniture "
            f"{'has' if is_one else 'have'} no height set. The 3D room is built by standing "
            "each piece up to its real height, so it can't be drawn until every one of them "
            "has one. Pick each piece below in Zones / Furniture, set its Height (in), then "
            "turn 3D back on."
        )
        shown = missing_names[:8]
        text = "\n".join(f"    - {name}" for name in shown)
        if count > len(shown):
            text += f"\n    - ...and {count - len(shown)} more"
        self.list_label.setText(text)
        parent = self.parent()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()


class RoomSetupPanel(QWidget):
    """Lets the user size their room, lay out named zones/furniture, and rename detected objects."""

    room_updated = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles: List[RoomConfig] = load_room_profiles()
        self._active_profile_index = 0
        self.zones: List[dict] = [dict(z) for z in self.profiles[0].zones]
        self.cameras: List[dict] = [dict(c) for c in self.profiles[0].cameras]
        self.palette = get_palette("Indigo")
        self._setup_ui()
        self._refresh_profile_list()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_object_list()
        self.apply_theme(self.palette)
        self._update_view_mode_hint()
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
        self._height_splash.apply_theme(palette)

        self.dock_host.setStyleSheet(f"""
            QMainWindow {{ background-color: {p['bg']}; }}
            QMainWindow::separator {{ background: {p['bg']}; width: 6px; height: 6px; }}
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

        self.zones_title.apply_theme(p)
        self.drawers_title.apply_theme(p)
        self.objects_title.apply_theme(p)

    # Bump this whenever the dock set changes (widgets added/removed, or a
    # dock gets a custom title bar) - restoreState() rejects a saved layout
    # whose version doesn't match instead of half-applying geometry that was
    # computed for a different set of docks, which is what squeezed the
    # sidebar down to a sliver after the Cameras dock was removed but the
    # old saved layout (still describing 4 docks) got restored anyway.
    _DOCK_LAYOUT_VERSION = 2

    def _restore_layout(self):
        state_b64 = load_app_settings().room_setup_layout
        if not state_b64:
            return
        try:
            state = QByteArray.fromBase64(state_b64.encode())
            self.dock_host.restoreState(state, self._DOCK_LAYOUT_VERSION)
        except Exception:
            pass
        # A layout saved back when panels could be torn off would otherwise
        # restore a floating dock that there is no longer any way to drag
        # back into place.
        for dock in self._room_docks:
            dock.setFloating(False)

    def save_layout(self):
        """Persist the current dock panel arrangement (size/position/floating
        state) so the Room Setup panel reopens where the user left it -
        called on app close, same as Room Tracker's own layout."""
        state = self.dock_host.saveState(self._DOCK_LAYOUT_VERSION)
        settings = load_app_settings()
        settings.room_setup_layout = bytes(state.toBase64()).decode()
        save_app_settings(settings)

    def _active_profile(self) -> RoomConfig:
        return self.profiles[self._active_profile_index]

    def reload_profiles(self):
        """Re-read room profiles from disk - for changes made outside this
        panel (e.g. importing room data in Settings, or camera add/rename/
        remove from the Cameras tab) so it doesn't keep editing a stale
        in-memory copy and clobber those changes on next Save."""
        self.profiles = load_room_profiles()
        if self._active_profile_index >= len(self.profiles):
            self._active_profile_index = 0
        self.zones = [dict(z) for z in self._active_profile().zones]
        self.cameras = [dict(c) for c in self._active_profile().cameras]
        self._refresh_profile_list()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self._refresh_object_list()
        self._sync_3d_mode()

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
        self.profile_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.profile_selector.setMinimumContentsLength(8)
        self.profile_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.profile_selector.currentIndexChanged.connect(self._on_profile_selected)
        profile_row.addWidget(self.profile_selector, 1)

        self.new_room_btn = QPushButton("New Room")
        self.new_room_btn.setProperty("cls", "secondary")
        self.new_room_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.new_room_btn.clicked.connect(self._on_new_room)
        profile_row.addWidget(self.new_room_btn)

        self.rename_room_btn = QPushButton("Rename")
        self.rename_room_btn.setProperty("cls", "secondary")
        self.rename_room_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.rename_room_btn.clicked.connect(self._on_rename_room)
        profile_row.addWidget(self.rename_room_btn)

        self.delete_room_btn = QPushButton("Delete")
        self.delete_room_btn.setProperty("cls", "secondary")
        self.delete_room_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
        dims_row.addWidget(self._label("Width (ft)"))
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(m_to_ft(1.0), m_to_ft(30.0))
        self.width_input.setDecimals(1)
        self.width_input.setSingleStep(0.5)
        self.width_input.setSuffix(" ft")
        self.width_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.width_input)

        # "Depth", not "Height" - this is the room's second floor-plan axis,
        # and there is now a separate Height field for how tall a piece of
        # furniture stands.
        dims_row.addWidget(self._label("Depth (ft)"))
        self.height_input = QDoubleSpinBox()
        self.height_input.setRange(m_to_ft(1.0), m_to_ft(30.0))
        self.height_input.setDecimals(1)
        self.height_input.setSingleStep(0.5)
        self.height_input.setSuffix(" ft")
        self.height_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.height_input)
        dims_row.addStretch()
        left_layout.addLayout(dims_row)

        view_row = QHBoxLayout()
        view_row.setSpacing(8)
        self.view_3d_btn = QPushButton("3D View")
        self.view_3d_btn.setCheckable(True)
        self.view_3d_btn.setProperty("cls", "secondary")
        self.view_3d_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.view_3d_btn.clicked.connect(self._on_toggle_3d)
        view_row.addWidget(self.view_3d_btn)
        view_row.addStretch()
        left_layout.addLayout(view_row)

        self.view_mode_hint = QLabel("")
        self.view_mode_hint.setProperty("cls", "hint")
        self.view_mode_hint.setWordWrap(True)
        left_layout.addWidget(self.view_mode_hint)

        camera_hint = QLabel(
            "Add, rename, or remove cameras from the Cameras tab. Once a camera's added, "
            "drag its marker below to place it where it actually sits in the room - click "
            "a marker to select it, then press Delete to take it out."
        )
        camera_hint.setProperty("cls", "hint")
        camera_hint.setWordWrap(True)
        left_layout.addWidget(camera_hint)

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

        settings_sep = QFrame()
        settings_sep.setFrameShape(QFrame.HLine)
        settings_sep.setProperty("cls", "sep")
        right_layout.addWidget(settings_sep)

        self.zone_settings_label = QLabel("Select a piece of furniture to edit its settings")
        self.zone_settings_label.setProperty("cls", "muted")
        self.zone_settings_label.setWordWrap(True)
        right_layout.addWidget(self.zone_settings_label)

        type_row = QHBoxLayout()
        type_row.setSpacing(8)
        type_row.addWidget(self._label("Type"))
        self.zone_type_input = QComboBox()
        self.zone_type_input.addItems(FURNITURE_TYPES)
        self.zone_type_input.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.zone_type_input.setMinimumContentsLength(6)
        self.zone_type_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.zone_type_input.setEnabled(False)
        self.zone_type_input.currentIndexChanged.connect(self._on_zone_type_changed)
        type_row.addWidget(self.zone_type_input, 1)
        right_layout.addLayout(type_row)

        height_row = QHBoxLayout()
        height_row.setSpacing(8)
        # Inches rather than feet: furniture is measured in them ("a 32 inch
        # dresser"), and decimal feet would make every value a fraction.
        height_row.addWidget(self._label("Height (in)"))
        self.zone_height_input = QDoubleSpinBox()
        self.zone_height_input.setRange(0.0, m_to_in(5.0))
        self.zone_height_input.setSingleStep(1.0)
        self.zone_height_input.setDecimals(1)
        self.zone_height_input.setSuffix(" in")
        # 0.00 is "no height yet" rather than a zero-height object, so it
        # reads as unset instead of as a deliberate answer.
        self.zone_height_input.setSpecialValueText("Not set")
        self.zone_height_input.setEnabled(False)
        self.zone_height_input.valueChanged.connect(self._on_zone_height_changed)
        height_row.addWidget(self.zone_height_input, 1)
        right_layout.addLayout(height_row)

        height_hint = QLabel(
            "How tall this piece stands off the floor - a bed is roughly 24 in, a dresser "
            "32 in, a desk 30 in, a wardrobe 78 in. The 3D view needs one on every piece "
            "before it will open."
        )
        height_hint.setProperty("cls", "hint")
        height_hint.setWordWrap(True)
        right_layout.addWidget(height_hint)

        self.zone_notes_input = QLineEdit()
        self.zone_notes_input.setPlaceholderText("Notes (e.g. \"Kids' clothes\", \"keep unlocked\")")
        self.zone_notes_input.setEnabled(False)
        self.zone_notes_input.editingFinished.connect(self._on_zone_notes_changed)
        right_layout.addWidget(self.zone_notes_input)

        right_layout.addStretch()

        zones_scroll = QScrollArea()
        zones_scroll.setWidgetResizable(True)
        zones_scroll.setFrameShape(QFrame.NoFrame)
        zones_scroll.setWidget(zones_widget)

        self.zones_dock = QDockWidget("Zones / Furniture", self.dock_host)
        self.zones_dock.setObjectName("zones_dock")
        self.zones_dock.setWidget(zones_scroll)
        self.zones_dock.setFeatures(LOCKED_DOCK_FEATURES)
        self.zones_title = _CollapsibleDockTitle("Zones / Furniture", self.zones_dock, self.dock_host)
        self.zones_dock.setTitleBarWidget(self.zones_title)
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
        self.drawer_count_input.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        drawer_config_row.addWidget(self.drawer_count_input)

        self.drawer_orientation_input = QComboBox()
        self.drawer_orientation_input.addItems(["Stacked (top-bottom)", "Side by side (left-right)"])
        self.drawer_orientation_input.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.drawer_orientation_input.setMinimumContentsLength(6)
        self.drawer_orientation_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        drawer_config_row.addWidget(self.drawer_orientation_input, 1)

        self.set_drawers_btn = QPushButton("Set Drawers")
        self.set_drawers_btn.setProperty("cls", "secondary")
        self.set_drawers_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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

        drawers_scroll = QScrollArea()
        drawers_scroll.setWidgetResizable(True)
        drawers_scroll.setFrameShape(QFrame.NoFrame)
        drawers_scroll.setWidget(drawers_widget)

        self.drawers_dock = QDockWidget("Drawers", self.dock_host)
        self.drawers_dock.setObjectName("drawers_dock")
        self.drawers_dock.setWidget(drawers_scroll)
        self.drawers_dock.setFeatures(LOCKED_DOCK_FEATURES)
        self.drawers_title = _CollapsibleDockTitle("Drawers", self.drawers_dock, self.dock_host)
        self.drawers_dock.setTitleBarWidget(self.drawers_title)
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

        objects_scroll = QScrollArea()
        objects_scroll.setWidgetResizable(True)
        objects_scroll.setFrameShape(QFrame.NoFrame)
        objects_scroll.setWidget(objects_widget)

        self.objects_dock = QDockWidget("Detected Objects", self.dock_host)
        self.objects_dock.setObjectName("objects_dock")
        self.objects_dock.setWidget(objects_scroll)
        self.objects_dock.setFeatures(LOCKED_DOCK_FEATURES)
        self.objects_title = _CollapsibleDockTitle("Detected Objects", self.objects_dock, self.dock_host)
        self.objects_dock.setTitleBarWidget(self.objects_title)
        self.dock_host.addDockWidget(Qt.RightDockWidgetArea, self.objects_dock)
        view_menu.addAction(self.objects_dock.toggleViewAction())

        # Zones/Drawers/Detected Objects are independent dock panels - collapse
        # them from their title bar, drag an edge to resize, or hide them
        # (reopen via the "Panels" menu). Where they sit is fixed here and
        # changed only in Settings > Customization, which is why they are
        # exposed as _room_docks - that screen pulls each one out to its
        # sidebar individually.
        self._room_docks: List[QDockWidget] = [
            self.zones_dock, self.drawers_dock, self.objects_dock,
        ]
        for dock in self._room_docks:
            dock.setMinimumWidth(260)
        self.dock_host.resizeDocks(self._room_docks, [320] * len(self._room_docks), Qt.Horizontal)

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

        # The metres the size fields were last loaded with - see _dim_to_m.
        self._loaded_width_m = 0.0
        self._loaded_height_m = 0.0

        self._selected_zone_index: Optional[int] = None
        self._selected_drawer_index: Optional[int] = None
        self._selected_camera_index: Optional[int] = None
        self._selected_object_id: Optional[int] = None

        # Covers the whole tab, so it is created against the panel itself
        # rather than the dock host or the canvas.
        self._height_splash = _HeightRequiredSplash(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Laying out the panel can resize it before _setup_ui has finished,
        # so the splash is not guaranteed to exist yet.
        splash = getattr(self, '_height_splash', None)
        if splash is not None and splash.isVisible():
            splash.setGeometry(self.rect())

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("cls", "muted")
        return lbl

    def _load_from_config(self):
        profile = self._active_profile()
        self._loaded_width_m = profile.width_m
        self._loaded_height_m = profile.height_m
        self.width_input.blockSignals(True)
        self.height_input.blockSignals(True)
        self.width_input.setValue(m_to_ft(profile.width_m))
        self.height_input.setValue(m_to_ft(profile.height_m))
        self.width_input.blockSignals(False)
        self.height_input.blockSignals(False)
        self.canvas.set_room_size(profile.width_m, profile.height_m)
        self.canvas.set_zones(self.zones)
        self.canvas.set_cameras(self.cameras)

    @staticmethod
    def _dim_to_m(shown_ft: float, loaded_m: float) -> float:
        """Feet from a size field back to metres.

        A field the user hasn't touched is answered from the metres it was
        loaded with rather than converted back: the display rounds to a tenth
        of a foot, so round-tripping an untouched room would nudge its size by
        a centimetre or so every time it was saved.
        """
        if round(shown_ft, 1) == round(m_to_ft(loaded_m), 1):
            return loaded_m
        return ft_to_m(shown_ft)

    def _room_width_m(self) -> float:
        return self._dim_to_m(self.width_input.value(), self._loaded_width_m)

    def _room_height_m(self) -> float:
        return self._dim_to_m(self.height_input.value(), self._loaded_height_m)

    def _on_size_changed(self):
        self.canvas.set_room_size(self._room_width_m(), self._room_height_m())

    def _on_toggle_3d(self, checked: bool):
        if not checked:
            self.canvas.set_view_3d(False)
            self.draw_zone_btn.setEnabled(True)
            self._update_view_mode_hint()
            self.status_label.setText("Back to the 2D floor plan.")
            return

        missing = zones_missing_height(self.zones)
        if missing:
            self.view_3d_btn.setChecked(False)
            self.canvas.set_view_3d(False)
            self.draw_zone_btn.setEnabled(True)
            self._update_view_mode_hint()
            self._height_splash.show_error(missing)
            return

        # Drawing a zone needs a click to mean one point on the floor, which
        # it no longer does once the room is tilted - so that control is
        # parked while 3D is on rather than silently misbehaving.
        self.draw_zone_btn.setChecked(False)
        self.draw_zone_btn.setEnabled(False)
        self.canvas.set_draw_mode(False)
        self.canvas.set_view_3d(True)
        self._update_view_mode_hint()
        self.status_label.setText("3D view on - drag the room to orbit it.")

    def _sync_3d_mode(self):
        """Drop back to 2D (with the splash) when the furniture on screen no
        longer all has a height - switching rooms, scanning, or clearing a
        height can bring in pieces that don't."""
        if self.canvas.view_3d:
            missing = zones_missing_height(self.zones)
            if missing:
                self.view_3d_btn.setChecked(False)
                self.canvas.set_view_3d(False)
                self.draw_zone_btn.setEnabled(True)
                self._height_splash.show_error(missing)
        self._update_view_mode_hint()

    def _update_view_mode_hint(self):
        if self.canvas.view_3d:
            self.view_mode_hint.setText(
                "3D view: every piece stands at the height you gave it. Drag the room to orbit "
                "it. Switch back to 2D to draw, move, or resize anything."
            )
            return
        missing = zones_missing_height(self.zones)
        if missing:
            count = len(missing)
            self.view_mode_hint.setText(
                f"2D floor plan. {count} {'piece' if count == 1 else 'pieces'} of furniture "
                f"still {'needs' if count == 1 else 'need'} a height before 3D can be turned on: "
                + ", ".join(missing[:5]) + ("..." if count > 5 else "")
            )
        else:
            self.view_mode_hint.setText(
                "2D floor plan. Turn on 3D to stand the furniture up at its real height."
            )

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
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_drawer_list()
        self._refresh_object_list()
        self._sync_3d_mode()
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
        self.zones.append({
            "name": name, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "type": _guess_furniture_type(name), "notes": "", "height_m": 0.0,
        })
        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self._update_view_mode_hint()
        self.zone_name_input.clear()
        self.draw_zone_btn.setChecked(False)
        self.canvas.set_draw_mode(False)
        self.status_label.setText(f"Added zone \"{name}\". Don't forget to Save Room.")

    def _on_scan_room(self):
        db = Database()
        active_items = db.get_active_items(room_id=self._active_profile().id)
        db.close()

        temp_config = RoomConfig(
            width_m=self._room_width_m(),
            height_m=self._room_height_m(),
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
                self.zones.append({
                    "name": zone_name, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "type": _guess_furniture_type(zone_name), "notes": "", "height_m": 0.0,
                })
                added += 1

        self.canvas.set_zones(self.zones)
        self._refresh_zone_list()
        self._sync_3d_mode()

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
            height = zone_height(zone)
            height_tag = f"{format_ft_in(height)} tall" if height > 0 else "no height"
            text = (f"{zone['name']}{tag}  "
                    f"({m_to_ft(zone['x1']):.1f}, {m_to_ft(zone['y1']):.1f}) -> "
                    f"({m_to_ft(zone['x2']):.1f}, {m_to_ft(zone['y2']):.1f}) ft  "
                    f"[{height_tag}]")
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
        self._refresh_zone_settings()

    def _on_zone_selected_in_canvas(self, index: int):
        self._selected_zone_index = index
        self.zone_list.setCurrentRow(index)
        self.zone_rename_input.setText(self.zones[index]["name"])
        self._refresh_drawer_list()
        self._refresh_zone_settings()

    def _refresh_zone_settings(self):
        """Populates the Type/Notes fields for whichever piece of furniture
        is currently selected - clicking a different zone (on the canvas or
        in the list above) re-scopes these to just that one object."""
        index = self._selected_zone_index
        if index is None:
            self.zone_settings_label.setText("Select a piece of furniture to edit its settings")
            self.zone_type_input.setEnabled(False)
            self.zone_notes_input.setEnabled(False)
            self.zone_notes_input.clear()
            self.zone_height_input.setEnabled(False)
            self.zone_height_input.blockSignals(True)
            self.zone_height_input.setValue(0.0)
            self.zone_height_input.blockSignals(False)
            self.zone_type_input.blockSignals(True)
            self.zone_type_input.setCurrentIndex(0)
            self.zone_type_input.blockSignals(False)
            return

        zone = self.zones[index]
        self.zone_settings_label.setText(f"Settings for \"{zone['name']}\"")
        self.zone_type_input.setEnabled(True)
        self.zone_notes_input.setEnabled(True)
        self.zone_height_input.setEnabled(True)

        self.zone_height_input.blockSignals(True)
        self.zone_height_input.setValue(m_to_in(zone_height(zone)))
        self.zone_height_input.blockSignals(False)

        self.zone_type_input.blockSignals(True)
        self.zone_type_input.setCurrentText(zone.get("type", "Other"))
        self.zone_type_input.blockSignals(False)

        self.zone_notes_input.blockSignals(True)
        self.zone_notes_input.setText(zone.get("notes", ""))
        self.zone_notes_input.blockSignals(False)

    def _on_zone_type_changed(self, _index: int):
        if self._selected_zone_index is None:
            return
        self.zones[self._selected_zone_index]["type"] = self.zone_type_input.currentText()
        self.status_label.setText("Updated furniture type. Don't forget to Save Room.")

    def _on_zone_height_changed(self, inches: float):
        if self._selected_zone_index is None:
            return
        zone = self.zones[self._selected_zone_index]
        zone["height_m"] = in_to_m(inches)
        # self.zones is the same list the canvas holds, so a repaint is all
        # that's needed - set_zones() would clear the current selection.
        self.canvas.update()
        self._refresh_zone_list()
        self.zone_list.setCurrentRow(self._selected_zone_index)
        if inches > 0:
            self.status_label.setText(
                f"\"{zone['name']}\" is {format_ft_in(zone['height_m'])} tall. "
                "Don't forget to Save Room."
            )
        else:
            self.status_label.setText(
                f"Cleared the height on \"{zone['name']}\" - 3D view needs one on every piece."
            )
        self._sync_3d_mode()

    def _on_zone_notes_changed(self):
        if self._selected_zone_index is None:
            return
        self.zones[self._selected_zone_index]["notes"] = self.zone_notes_input.text().strip()
        self.status_label.setText("Updated furniture notes. Don't forget to Save Room.")

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
        self._update_view_mode_hint()
        self.status_label.setText(f"Renamed zone to \"{new_name}\". Don't forget to Save Room.")

    def _on_rotate_zone(self):
        if self._selected_zone_index is None:
            self.status_label.setText("Select a zone to rotate first.")
            return

        zone = self.zones[self._selected_zone_index]
        x1, y1, x2, y2 = zone["x1"], zone["y1"], zone["x2"], zone["y2"]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        half_w, half_h = (x2 - x1) / 2.0, (y2 - y1) / 2.0

        room_w, room_h = self._room_width_m(), self._room_height_m()
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
        self._refresh_zone_settings()
        self._update_view_mode_hint()
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
        profile.width_m = self._room_width_m()
        profile.height_m = self._room_height_m()
        self._loaded_width_m = profile.width_m
        self._loaded_height_m = profile.height_m
        profile.zones = self.zones
        profile.cameras = self.cameras
        save_room_profiles(self.profiles)
        self.status_label.setText(f"Saved \"{profile.name}\".")
        self.room_updated.emit()

    def _on_camera_selected_in_canvas(self, index: int):
        self._selected_camera_index = index

    def _on_remove_camera(self):
        if self._selected_camera_index is None:
            self.status_label.setText("Select a camera to remove first.")
            return
        removed = self.cameras.pop(self._selected_camera_index)
        self._selected_camera_index = None
        self.canvas.set_cameras(self.cameras)
        self.status_label.setText(f"Removed \"{removed['label']}\". Don't forget to Save Room.")

    def _on_camera_moved(self, index: int, x: float, y: float):
        self.status_label.setText(
            f"{self.cameras[index]['label']} at ({m_to_ft(x):.1f} ft, {m_to_ft(y):.1f} ft)"
        )

    def _on_camera_drag_finished(self):
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
