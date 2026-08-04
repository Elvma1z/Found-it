from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QFrame, QDoubleSpinBox, QSpinBox, QComboBox, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush
from typing import List, Optional, Tuple

from found_it.utils.room_config import load_room_config, save_room_config
from found_it.storage.database import Database
from found_it.storage.models import RoomConfig
from found_it.detection.item_mapper import ItemMapper

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

INPUT_STYLE = """
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
        background-color: #2a2a3e;
        color: #e0e0e0;
        border: 1px solid #444;
        border-radius: 4px;
        padding: 6px;
        font-size: 12px;
    }
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #6c63ff; }
"""

BUTTON_STYLE = """
    QPushButton {
        background-color: #6c63ff;
        color: white; border: none;
        border-radius: 4px; padding: 6px 14px;
        font-weight: bold; font-size: 12px;
    }
    QPushButton:hover { background-color: #5a52d5; }
    QPushButton:disabled { background-color: #3a3a4e; color: #777; }
"""

SECONDARY_BUTTON_STYLE = """
    QPushButton {
        background-color: #2a2a3e;
        color: #ccc; border: 1px solid #444;
        border-radius: 4px; padding: 6px 14px;
        font-size: 12px;
    }
    QPushButton:hover { background-color: #35354e; }
    QPushButton:checked { background-color: #6c63ff; color: white; }
"""

LIST_STYLE = """
    QListWidget {
        background-color: #1a1a2e;
        color: #e0e0e0;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 4px;
    }
    QListWidget::item { padding: 6px; border-bottom: 1px solid #2a2a3e; }
    QListWidget::item:selected { background-color: #3a3a5e; }
    QListWidget::item:hover { background-color: #2a2a4e; }
"""

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
                self._dragging_camera_index = i
                self.update()
                return

        mx, my = self._px_to_m(event.x(), event.y())
        for i, z in enumerate(self.zones):
            if z["x1"] <= mx <= z["x2"] and z["y1"] <= my <= z["y2"]:
                self.selected_index = i
                self.zone_selected.emit(i)
                self._dragging_zone_index = i
                self._zone_drag_start_mouse = (mx, my)
                self._zone_drag_start_bounds = (z["x1"], z["y1"], z["x2"], z["y2"])
                self._zone_drag_start_drawers = [dict(d) for d in z.get("drawers", [])]
                self.setFocus()
                self.update()
                return
        self.selected_index = None
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        _, ox, oy, room_px_w, room_px_h = self._scale_and_offset()
        ox, oy, room_px_w, room_px_h = int(ox), int(oy), int(room_px_w), int(room_px_h)

        painter.setPen(QPen(QColor(60, 60, 80), 2))
        painter.setBrush(QBrush(QColor(20, 20, 35)))
        painter.drawRoundedRect(ox, oy, room_px_w, room_px_h, 6, 6)

        painter.setPen(QPen(QColor(80, 80, 100), 1, Qt.DashLine))
        for i in range(1, 4):
            x = ox + int(room_px_w * i / 4)
            painter.drawLine(x, oy, x, oy + room_px_h)
            y = oy + int(room_px_h * i / 4)
            painter.drawLine(ox, y, ox + room_px_w, y)

        for i, zone in enumerate(self.zones):
            x1, y1 = self._m_to_px(zone["x1"], zone["y1"])
            x2, y2 = self._m_to_px(zone["x2"], zone["y2"])
            selected = i == self.selected_index
            color = QColor(255, 210, 90) if selected else QColor(108, 99, 255)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)
            painter.setPen(QPen(QColor(230, 230, 230), 1))
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
            painter.setPen(QPen(QColor(255, 210, 90), 2))
            painter.setBrush(QBrush(QColor(255, 210, 90)))
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
            radius = 10 if is_dragging else 8
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), alpha), 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), min(alpha, 130))))
            painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)
            painter.setPen(QPen(QColor(230, 230, 230, alpha), 1))
            painter.setFont(QFont("Segoe UI", 8, QFont.Bold))
            painter.drawText(cx + 12, cy + 4, cam.get("label", f"Camera {cam.get('id', 0)}"))

        painter.end()

    def keyPressEvent(self, event):
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.room_config = load_room_config()
        self.zones: List[dict] = [dict(z) for z in self.room_config.zones]
        self.cameras: List[dict] = [dict(c) for c in self.room_config.cameras]
        self._setup_ui()
        self._load_from_config()
        self._refresh_zone_list()
        self._refresh_camera_list()
        self._refresh_object_list()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        title = QLabel("Room Setup")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setStyleSheet("color: #e0e0e0;")
        outer.addWidget(title)

        desc = QLabel("Set your bedroom's size, sketch out zones like the bed or desk, and rename detected objects.")
        desc.setStyleSheet("color: #888; font-size: 11px;")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        splitter = QSplitter(Qt.Horizontal)

        # --- Left: dimensions + canvas ---
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 4, 4, 4)

        dims_row = QHBoxLayout()
        dims_row.addWidget(self._label("Width (m)"))
        self.width_input = QDoubleSpinBox()
        self.width_input.setRange(1.0, 30.0)
        self.width_input.setSingleStep(0.1)
        self.width_input.setStyleSheet(INPUT_STYLE)
        self.width_input.valueChanged.connect(self._on_size_changed)
        dims_row.addWidget(self.width_input)

        dims_row.addWidget(self._label("Height (m)"))
        self.height_input = QDoubleSpinBox()
        self.height_input.setRange(1.0, 30.0)
        self.height_input.setSingleStep(0.1)
        self.height_input.setStyleSheet(INPUT_STYLE)
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
        self.canvas.delete_requested.connect(self._on_delete_zone)
        self.canvas.rotate_requested.connect(self._on_rotate_zone)
        left_layout.addWidget(self.canvas)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #6c63ff; font-size: 11px;")
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left)

        # --- Right: zone list + object rename ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 0, 4)

        right_layout.addWidget(self._label("Cameras"))

        camera_add_row = QHBoxLayout()
        self.camera_id_input = QSpinBox()
        self.camera_id_input.setRange(0, 9)
        self.camera_id_input.setPrefix("ID ")
        self.camera_id_input.setStyleSheet(INPUT_STYLE)
        camera_add_row.addWidget(self.camera_id_input)

        self.camera_label_input = QLineEdit()
        self.camera_label_input.setPlaceholderText("e.g. Desk Cam")
        self.camera_label_input.setStyleSheet(INPUT_STYLE)
        camera_add_row.addWidget(self.camera_label_input)

        self.add_camera_btn = QPushButton("Add Camera")
        self.add_camera_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.add_camera_btn.clicked.connect(self._on_add_camera)
        camera_add_row.addWidget(self.add_camera_btn)
        right_layout.addLayout(camera_add_row)

        camera_hint = QLabel("Drag a camera's marker on the room to place it where it actually sits. Detected objects are positioned relative to that camera.")
        camera_hint.setStyleSheet("color: #666; font-size: 10px;")
        camera_hint.setWordWrap(True)
        right_layout.addWidget(camera_hint)

        self.camera_list = QListWidget()
        self.camera_list.setStyleSheet(LIST_STYLE)
        self.camera_list.itemClicked.connect(self._on_camera_list_clicked)
        self.camera_list.itemChanged.connect(self._on_camera_item_changed)
        right_layout.addWidget(self.camera_list)

        camera_edit_row = QHBoxLayout()
        self.camera_rename_input = QLineEdit()
        self.camera_rename_input.setPlaceholderText("Rename selected camera")
        self.camera_rename_input.setStyleSheet(INPUT_STYLE)
        camera_edit_row.addWidget(self.camera_rename_input)

        self.rename_camera_btn = QPushButton("Rename")
        self.rename_camera_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_camera_btn.clicked.connect(self._on_rename_camera)
        camera_edit_row.addWidget(self.rename_camera_btn)
        right_layout.addLayout(camera_edit_row)

        camera_action_row = QHBoxLayout()
        self.toggle_360_btn = QPushButton("Toggle 360°")
        self.toggle_360_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.toggle_360_btn.clicked.connect(self._on_toggle_360)
        camera_action_row.addWidget(self.toggle_360_btn)

        self.remove_camera_btn = QPushButton("Remove")
        self.remove_camera_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.remove_camera_btn.clicked.connect(self._on_remove_camera)
        camera_action_row.addWidget(self.remove_camera_btn)
        right_layout.addLayout(camera_action_row)

        camera_separator = QFrame()
        camera_separator.setFrameShape(QFrame.HLine)
        camera_separator.setStyleSheet("color: #333;")
        right_layout.addWidget(camera_separator)

        right_layout.addWidget(self._label("Zones / Furniture"))

        zones_hint = QLabel("Drag a zone on the room to move it, or drag its top-left corner handle to resize it. "
                             "With a zone selected: Delete removes it, Ctrl+R rotates it 90°.")
        zones_hint.setStyleSheet("color: #666; font-size: 10px;")
        zones_hint.setWordWrap(True)
        right_layout.addWidget(zones_hint)

        scan_row = QHBoxLayout()
        self.scan_room_btn = QPushButton("Scan Room with Cameras")
        self.scan_room_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.scan_room_btn.clicked.connect(self._on_scan_room)
        scan_row.addWidget(self.scan_room_btn)
        right_layout.addLayout(scan_row)

        scan_hint = QLabel("Auto-creates zones for furniture the cameras currently recognize (bed, couch, chair, TV, etc.) at their mapped position. Sizes are estimates since a camera can't measure true dimensions - reposition/resize by hand afterward. Add cameras and enable them first.")
        scan_hint.setStyleSheet("color: #666; font-size: 10px;")
        scan_hint.setWordWrap(True)
        right_layout.addWidget(scan_hint)

        add_row = QHBoxLayout()
        self.zone_name_input = QLineEdit()
        self.zone_name_input.setPlaceholderText("e.g. Bed, Desk, Closet")
        self.zone_name_input.setStyleSheet(INPUT_STYLE)
        add_row.addWidget(self.zone_name_input)

        self.draw_zone_btn = QPushButton("Draw Zone")
        self.draw_zone_btn.setCheckable(True)
        self.draw_zone_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.draw_zone_btn.clicked.connect(self._on_draw_zone_clicked)
        add_row.addWidget(self.draw_zone_btn)
        right_layout.addLayout(add_row)

        self.zone_list = QListWidget()
        self.zone_list.setStyleSheet(LIST_STYLE)
        self.zone_list.itemClicked.connect(self._on_zone_list_clicked)
        right_layout.addWidget(self.zone_list)

        rename_row = QHBoxLayout()
        self.zone_rename_input = QLineEdit()
        self.zone_rename_input.setPlaceholderText("Rename selected zone")
        self.zone_rename_input.setStyleSheet(INPUT_STYLE)
        rename_row.addWidget(self.zone_rename_input)

        self.rename_zone_btn = QPushButton("Rename")
        self.rename_zone_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_zone_btn.clicked.connect(self._on_rename_zone)
        rename_row.addWidget(self.rename_zone_btn)

        self.rotate_zone_btn = QPushButton("Rotate 90°")
        self.rotate_zone_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.rotate_zone_btn.clicked.connect(self._on_rotate_zone)
        rename_row.addWidget(self.rotate_zone_btn)

        self.delete_zone_btn = QPushButton("Delete")
        self.delete_zone_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.delete_zone_btn.clicked.connect(self._on_delete_zone)
        rename_row.addWidget(self.delete_zone_btn)
        right_layout.addLayout(rename_row)

        drawers_hint = QLabel("Has drawers? Select a zone above (e.g. Dresser) and split it into named compartments so the app can be specific about which one an object was put in.")
        drawers_hint.setStyleSheet("color: #666; font-size: 10px;")
        drawers_hint.setWordWrap(True)
        right_layout.addWidget(drawers_hint)

        drawer_config_row = QHBoxLayout()
        self.drawer_count_input = QSpinBox()
        self.drawer_count_input.setRange(0, 8)
        self.drawer_count_input.setPrefix("Drawers ")
        self.drawer_count_input.setStyleSheet(INPUT_STYLE)
        drawer_config_row.addWidget(self.drawer_count_input)

        self.drawer_orientation_input = QComboBox()
        self.drawer_orientation_input.addItems(["Stacked (top-bottom)", "Side by side (left-right)"])
        self.drawer_orientation_input.setStyleSheet(INPUT_STYLE)
        drawer_config_row.addWidget(self.drawer_orientation_input)

        self.set_drawers_btn = QPushButton("Set Drawers")
        self.set_drawers_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.set_drawers_btn.clicked.connect(self._on_set_drawers)
        drawer_config_row.addWidget(self.set_drawers_btn)
        right_layout.addLayout(drawer_config_row)

        self.drawer_list = QListWidget()
        self.drawer_list.setStyleSheet(LIST_STYLE)
        self.drawer_list.setMaximumHeight(90)
        self.drawer_list.itemClicked.connect(self._on_drawer_list_clicked)
        right_layout.addWidget(self.drawer_list)

        drawer_rename_row = QHBoxLayout()
        self.drawer_rename_input = QLineEdit()
        self.drawer_rename_input.setPlaceholderText("Rename selected drawer (e.g. Top Drawer)")
        self.drawer_rename_input.setStyleSheet(INPUT_STYLE)
        drawer_rename_row.addWidget(self.drawer_rename_input)

        self.rename_drawer_btn = QPushButton("Rename")
        self.rename_drawer_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_drawer_btn.clicked.connect(self._on_rename_drawer)
        drawer_rename_row.addWidget(self.rename_drawer_btn)
        right_layout.addLayout(drawer_rename_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #333;")
        right_layout.addWidget(separator)

        right_layout.addWidget(self._label("Detected Objects"))

        self.object_list = QListWidget()
        self.object_list.setStyleSheet(LIST_STYLE)
        self.object_list.itemClicked.connect(self._on_object_list_clicked)
        right_layout.addWidget(self.object_list)

        object_row = QHBoxLayout()
        self.object_rename_input = QLineEdit()
        self.object_rename_input.setPlaceholderText("Rename selected object")
        self.object_rename_input.setStyleSheet(INPUT_STYLE)
        object_row.addWidget(self.object_rename_input)

        self.rename_object_btn = QPushButton("Rename")
        self.rename_object_btn.setStyleSheet(BUTTON_STYLE)
        self.rename_object_btn.clicked.connect(self._on_rename_object)
        object_row.addWidget(self.rename_object_btn)

        self.refresh_objects_btn = QPushButton("Refresh")
        self.refresh_objects_btn.setStyleSheet(SECONDARY_BUTTON_STYLE)
        self.refresh_objects_btn.clicked.connect(self._refresh_object_list)
        object_row.addWidget(self.refresh_objects_btn)
        right_layout.addLayout(object_row)

        self.save_btn = QPushButton("Save Room")
        self.save_btn.setStyleSheet(BUTTON_STYLE)
        self.save_btn.clicked.connect(self._on_save)
        right_layout.addWidget(self.save_btn)

        splitter.addWidget(right)
        splitter.setSizes([550, 400])
        outer.addWidget(splitter)

        self._selected_zone_index: Optional[int] = None
        self._selected_drawer_index: Optional[int] = None
        self._selected_camera_index: Optional[int] = None
        self._selected_object_id: Optional[int] = None
        self._updating_camera_list = False

    def _label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        return lbl

    def _load_from_config(self):
        self.width_input.blockSignals(True)
        self.height_input.blockSignals(True)
        self.width_input.setValue(self.room_config.width_m)
        self.height_input.setValue(self.room_config.height_m)
        self.width_input.blockSignals(False)
        self.height_input.blockSignals(False)
        self.canvas.set_room_size(self.room_config.width_m, self.room_config.height_m)
        self.canvas.set_zones(self.zones)
        self.canvas.set_cameras(self.cameras)

    def _on_size_changed(self):
        self.canvas.set_room_size(self.width_input.value(), self.height_input.value())

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
        active_items = db.get_active_items()
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
        self.room_config.width_m = self.width_input.value()
        self.room_config.height_m = self.height_input.value()
        self.room_config.zones = self.zones
        self.room_config.cameras = self.cameras
        save_room_config(self.room_config)
        self.status_label.setText("Room saved.")
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

    def _on_add_camera(self):
        cam_id = self.camera_id_input.value()
        if any(c["id"] == cam_id for c in self.cameras):
            self.status_label.setText(f"Camera ID {cam_id} is already in the list.")
            return
        label = self.camera_label_input.text().strip() or f"Camera {cam_id}"
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
        self.camera_label_input.clear()
        self.status_label.setText(f"Added \"{label}\". Drag it into place, then Save Room.")

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
        self.status_label.setText(self.status_label.text() + " - don't forget to Save Room.")

    def _refresh_object_list(self):
        db = Database()
        items = db.get_recent_items(100)
        db.close()

        self.object_list.clear()
        for item in items:
            label = item.get("label", "unknown")
            cam = item.get("camera_id", 0)
            zone_name = item.get("zone_name")
            last_seen = (item.get("last_seen") or "")[:16]
            text = f"{label}  (cam {cam})"
            if zone_name:
                text += f"  in {zone_name}"
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
