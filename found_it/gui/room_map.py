import math
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath
from typing import List, Tuple, Optional

from found_it.utils.themes import get_palette


def _facing_wedge_path(cx: int, cy: int, radius: int, facing_deg: float, steps: int = 24) -> QPainterPath:
    """A 180 deg pie slice centered on facing_deg (0deg = +x, 90deg = +y,
    matching the room's coordinate system), for drawing a camera's actual
    field of view instead of implying it can see the whole room."""
    path = QPainterPath()
    path.moveTo(cx, cy)
    facing_rad = math.radians(facing_deg)
    for i in range(steps + 1):
        ang = facing_rad - math.pi / 2 + math.pi * i / steps
        path.lineTo(cx + radius * math.cos(ang), cy + radius * math.sin(ang))
    path.closeSubpath()
    return path


class RoomMap(QWidget):
    PIN_COLORS = {
        0: QColor(255, 100, 100),
        1: QColor(100, 100, 255),
        2: QColor(100, 255, 180),
    }
    FALLBACK_COLORS = [
        QColor(255, 180, 60), QColor(200, 100, 255), QColor(255, 100, 200),
        QColor(120, 220, 255), QColor(180, 255, 100),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.items: List[dict] = []
        self.zones: List[dict] = []
        self.cameras: List[dict] = []
        self.room_width = 4.0
        self.room_height = 4.0
        self._padding = 40
        self.palette = get_palette("Indigo")

    def apply_theme(self, palette: dict):
        self.palette = palette
        self.update()

    def set_room_size(self, width: float, height: float):
        self.room_width = width
        self.room_height = height
        self.update()

    def set_zones(self, zones: List[dict]):
        self.zones = zones
        self.update()

    def set_cameras(self, cameras: List[dict]):
        self.cameras = cameras
        self.update()

    def update_items(self, items: List[dict]):
        self.items = items
        self.update()

    def _color_for_camera(self, cam_id: int) -> QColor:
        if cam_id in self.PIN_COLORS:
            return self.PIN_COLORS[cam_id]
        return self.FALLBACK_COLORS[cam_id % len(self.FALLBACK_COLORS)]

    def _scale_and_offset(self) -> Tuple[float, float, float, float, float]:
        """A single meters-to-pixels scale (not one per axis) so the room and
        everything in it renders in true proportion instead of stretching to
        fill the widget - the room is letterboxed/centered within it instead."""
        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        if self.room_width <= 0 or self.room_height <= 0 or draw_w <= 0 or draw_h <= 0:
            return 1.0, float(self._padding), float(self._padding), float(max(draw_w, 0)), float(max(draw_h, 0))
        scale = min(draw_w / self.room_width, draw_h / self.room_height)
        room_px_w = self.room_width * scale
        room_px_h = self.room_height * scale
        ox = self._padding + (draw_w - room_px_w) / 2.0
        oy = self._padding + (draw_h - room_px_h) / 2.0
        return scale, ox, oy, room_px_w, room_px_h

    def _room_to_pixel(self, room_x: float, room_y: float) -> Tuple[int, int]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        return int(ox + room_x * scale), int(oy + room_y * scale)

    def _pixel_to_room(self, px: int, py: int) -> Tuple[float, float]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        room_x = (px - ox) / scale if scale else 0.0
        room_y = (py - oy) / scale if scale else 0.0
        return room_x, room_y

    def paintEvent(self, event):
        p = self.palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        _, ox, oy, room_px_w, room_px_h = self._scale_and_offset()
        ox, oy, room_px_w, room_px_h = int(ox), int(oy), int(room_px_w), int(room_px_h)
        room_rect = QRect(ox, oy, room_px_w, room_px_h)

        painter.setPen(QPen(QColor(p["border"]), 2))
        painter.setBrush(QBrush(QColor(p["bg"])))
        painter.drawRoundedRect(room_rect, 6, 6)

        painter.setPen(QPen(QColor(p["border"]), 1, Qt.DashLine))
        for i in range(1, 3):
            x = ox + int(room_px_w * i / 3)
            painter.drawLine(x, oy, x, oy + room_px_h)
            y = oy + int(room_px_h * i / 3)
            painter.drawLine(ox, y, ox + room_px_w, y)

        painter.setPen(QPen(QColor(p["text_faint"]), 1))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        for i in range(3):
            x = ox + int(room_px_w * (i + 0.5) / 3)
            painter.drawText(x - 10, oy + room_px_h + 15, f"{(i+1)/3:.1f}")

        accent = QColor(p["accent"])
        accent_hover = QColor(p["accent_hover"])
        for zone in self.zones:
            zx1, zy1 = self._room_to_pixel(zone["x1"], zone["y1"])
            zx2, zy2 = self._room_to_pixel(zone["x2"], zone["y2"])
            painter.setPen(QPen(accent, 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(accent.red(), accent.green(), accent.blue(), 30)))
            painter.drawRect(zx1, zy1, zx2 - zx1, zy2 - zy1)
            painter.setPen(QPen(accent_hover, 1))
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            painter.drawText(zx1 + 4, zy1 + 12, zone.get("name", "Zone"))

            for drawer in zone.get("drawers", []):
                dx1, dy1 = self._room_to_pixel(drawer["x1"], drawer["y1"])
                dx2, dy2 = self._room_to_pixel(drawer["x2"], drawer["y2"])
                painter.setPen(QPen(QColor(255, 210, 90), 1, Qt.DotLine))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(dx1, dy1, dx2 - dx1, dy2 - dy1)
                painter.setPen(QPen(QColor(230, 215, 170), 1))
                painter.setFont(QFont("Segoe UI", 6))
                painter.drawText(dx1 + 3, dy1 + 10, drawer.get("name", "Drawer"))

        for cam in self.cameras:
            if not cam.get("enabled"):
                continue
            cam_id = cam.get("id", 0)
            cam_px, cam_py = self._room_to_pixel(cam.get("x", 0), cam.get("y", 0))
            color = self._color_for_camera(cam_id)
            label = cam.get("label", f"Camera {cam_id}")

            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 80)))
            painter.drawEllipse(cam_px - 8, cam_py - 8, 16, 16)
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(cam_px + 12, cam_py + 5, label)

            if cam.get("is_360"):
                painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 40), 1, Qt.DotLine))
                painter.setBrush(Qt.NoBrush)
                radius = min(room_px_w, room_px_h) // 2 - 10
                painter.drawEllipse(cam_px - radius, cam_py - radius, radius * 2, radius * 2)
            elif cam.get("is_180"):
                # Only a half-circle wedge, not a full ring like 360° - this
                # camera genuinely can't see the other half of the room, and
                # the map should look like that's true.
                radius = min(room_px_w, room_px_h) // 2 - 10
                painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 60), 1, Qt.DotLine))
                painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 20)))
                painter.drawPath(_facing_wedge_path(cam_px, cam_py, radius, cam.get("facing_deg", 0.0)))

        for item in self.items:
            room_x = item.get("room_x", 0)
            room_y = item.get("room_y", 0)
            px, py = self._room_to_pixel(room_x, room_y)

            cam_id = item.get("camera_id", 0)
            color = self._color_for_camera(cam_id)

            pin_size = 8
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(px - pin_size // 2, py - pin_size // 2,
                                pin_size, pin_size)

            label = item.get("label", "?")
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            painter.setPen(QPen(QColor(p["text_dim"]), 1))
            text_rect = QRect(px + 8, py - 8, 120, 16)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             f"{label} [cam{cam_id}]")

        painter.end()
