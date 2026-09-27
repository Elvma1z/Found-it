"""components/room/RoomMap - the top-down room plan.

The paint helpers are shared with Room Setup's editable canvas, so both maps
draw the room, zones, drawers, cameras and pins identically."""

import math
from typing import List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from found_it.gui import ds
from found_it.gui.icons import get_pixmap
from found_it.utils.themes import DRAWER_LINE, PIN_SELECTED, pin_color

M_TO_FT = 3.28084


def _facing_wedge_path(cx: float, cy: float, radius: float, facing_deg: float, steps: int = 24) -> QPainterPath:
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


# ---------------------------------------------------------------- shared paint helpers

def paint_room(painter: QPainter, p: dict, rect: QRectF, scale: float, room_w: float, room_h: float,
               caption: bool = True):
    """Rounded room outline on surface-2, half-metre grid hairlines (every
    metre a little stronger) and the size caption underneath."""
    painter.setPen(QPen(QColor(p["border_strong"]), 1.5))
    painter.setBrush(QColor(p["surface2"]))
    painter.drawRoundedRect(rect, 10, 10)

    clip = QPainterPath()
    clip.addRoundedRect(rect, 10, 10)
    painter.save()
    painter.setClipPath(clip)
    step = 0.5
    if scale * step >= 6:
        n = 1
        while n * step < room_w:
            x = rect.left() + n * step * scale
            painter.setPen(QPen(QColor(p["border"]), 1 if n % 2 == 0 else 0.5))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            n += 1
        n = 1
        while n * step < room_h:
            y = rect.top() + n * step * scale
            painter.setPen(QPen(QColor(p["border"]), 1 if n % 2 == 0 else 0.5))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            n += 1
    painter.restore()

    if caption:
        painter.setPen(QColor(p["text3"]))
        painter.setFont(ds.font(11))
        painter.drawText(QPointF(rect.left(), rect.bottom() + 20),
                         f"{room_w * M_TO_FT:.1f} ft × {room_h * M_TO_FT:.1f} ft")


def paint_zone(painter: QPainter, p: dict, rect: QRectF, name: str, selected: bool = False):
    accent = QColor(p["accent"])
    fill = QColor(accent)
    fill.setAlphaF(0.16 if selected else 0.10)
    stroke = QColor(accent)
    stroke.setAlphaF(0.9 if selected else 0.55)
    painter.setPen(QPen(stroke, 1.5 if selected else 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 6, 6)
    painter.setPen(QColor(p["accent_text"]))
    painter.setFont(ds.font(11.5, 600))
    fm = painter.fontMetrics()
    painter.drawText(QPointF(rect.left() + 8, rect.top() + 17),
                     fm.elidedText(name or "Zone", Qt.ElideRight, int(max(rect.width() - 14, 10))))


def paint_drawer(painter: QPainter, rect: QRectF, name: str, first: bool):
    line = QColor(DRAWER_LINE)
    line.setAlphaF(0.6)
    pen = QPen(line, 1, Qt.CustomDashLine)
    pen.setDashPattern([3, 3])
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    inner = rect.adjusted(3, 22 if first else 3, -3, -3)
    if inner.height() < 6:
        inner = rect.adjusted(3, 3, -3, -3)
    painter.drawRoundedRect(inner, 4, 4)
    painter.setPen(QColor(DRAWER_LINE))
    painter.setFont(ds.font(10))
    fm = painter.fontMetrics()
    if inner.height() >= 14:
        painter.drawText(QPointF(rect.left() + 9, rect.bottom() - 8),
                         fm.elidedText(name or "Drawer", Qt.ElideRight, int(max(rect.width() - 18, 10))))


def paint_camera(painter: QPainter, p: dict, cx: float, cy: float, cam: dict, room_rect: QRectF,
                 label_right: bool = True, dim: bool = False, selected: bool = False, radius: float = 11):
    color = QColor(pin_color(cam.get("id", 0)))
    if dim:
        color.setAlphaF(0.4)
    r = min(room_rect.width(), room_rect.height()) / 2 - 10
    if cam.get("is_360"):
        ring = QColor(color)
        ring.setAlphaF(0.25)
        pen = QPen(ring, 1, Qt.CustomDashLine)
        pen.setDashPattern([2, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)
    elif cam.get("is_180"):
        edge = QColor(color)
        edge.setAlphaF(0.3)
        fill = QColor(color)
        fill.setAlphaF(0.08)
        painter.setPen(QPen(edge, 1, Qt.DotLine))
        painter.setBrush(fill)
        painter.drawPath(_facing_wedge_path(cx, cy, r, cam.get("facing_deg", 0.0)))
    if selected:
        ring = QColor(p["accent"])
        pen = QPen(ring, 1.5, Qt.CustomDashLine)
        pen.setDashPattern([3, 3])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius + 5, radius + 5)
    painter.setPen(QPen(color, 1.5))
    painter.setBrush(QColor(p["solid"]))
    painter.drawEllipse(QPointF(cx, cy), radius, radius)
    painter.drawPixmap(QPointF(cx - 6, cy - 6), get_pixmap("camera", color.name(), 12))
    label = cam.get("label") or f"Camera {cam.get('id', 0)}"
    painter.setFont(ds.font(11))
    painter.setPen(QColor(p["text2"]))
    fm = painter.fontMetrics()
    if label_right:
        painter.drawText(QPointF(cx + radius + 5, cy + 4), label)
    else:
        painter.drawText(QPointF(cx - radius - 5 - fm.horizontalAdvance(label), cy + 4), label)


def paint_pin(painter: QPainter, p: dict, px: float, py: float, label: str, cam_id: int,
              selected: bool = False, pulse: float = 0.0):
    col = QColor(PIN_SELECTED if selected else pin_color(cam_id))
    if selected:
        ring = QColor(col)
        ring.setAlphaF(0.7 * (1 - pulse))
        painter.setPen(QPen(ring, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(px, py), 6 + 10 * pulse, 6 + 10 * pulse)
    halo = QColor(col)
    halo.setAlphaF(0.25)
    painter.setPen(Qt.NoPen)
    painter.setBrush(halo)
    r = 9 if selected else 7
    painter.drawEllipse(QPointF(px, py), r, r)
    painter.setPen(QPen(QColor(p["bg"]), 1.5))
    painter.setBrush(col)
    r = 5 if selected else 4
    painter.drawEllipse(QPointF(px, py), r, r)

    painter.setFont(ds.font(11.5, 600 if selected else 400))
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(label) + 14
    pill = QRectF(px + 11, py - 10, w, 20)
    if selected:
        painter.setPen(QPen(QColor(p["border_strong"]), 1))
        painter.setBrush(QColor(p["solid"]))
        painter.drawRoundedRect(pill, 5, 5)
    painter.setPen(QColor(p["text"] if selected else p["text2"]))
    painter.drawText(pill.adjusted(7, 0, 0, 0), Qt.AlignVCenter, label)


class RoomMap(QWidget):
    """Room Tracker's live map. Click a pin to select that item."""

    item_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 260)
        self.items: List[dict] = []
        self.zones: List[dict] = []
        self.cameras: List[dict] = []
        self.room_width = 4.0
        self.room_height = 4.0
        self._padding = 36
        self._selected_id = None
        self._pulse = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        ds.theme_bus().changed.connect(lambda _p: self.update())

    def apply_theme(self, palette: dict):
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

    def set_selected_item(self, item_id):
        self._selected_id = item_id
        if item_id is None:
            self._pulse_timer.stop()
        elif not self._pulse_timer.isActive():
            self._pulse_timer.start(40)
        self.update()

    def _tick(self):
        self._pulse = (self._pulse + 40 / 1600) % 1.0
        self.update()

    def _color_for_camera(self, cam_id: int) -> QColor:
        return QColor(pin_color(cam_id))

    def _scale_and_offset(self) -> Tuple[float, float, float, float, float]:
        """A single metres-to-pixels scale (not one per axis) so the room is
        drawn in true proportion, letterboxed and centred in the widget."""
        pad = self._padding
        draw_w = self.width() - 2 * pad
        draw_h = self.height() - 2 * pad
        if self.room_width <= 0 or self.room_height <= 0 or draw_w <= 0 or draw_h <= 0:
            return 1.0, float(pad), float(pad), float(max(draw_w, 0)), float(max(draw_h, 0))
        scale = min(draw_w / self.room_width, draw_h / self.room_height)
        room_px_w = self.room_width * scale
        room_px_h = self.room_height * scale
        ox = pad + (draw_w - room_px_w) / 2.0
        oy = pad + (draw_h - room_px_h) / 2.0
        return scale, ox, oy, room_px_w, room_px_h

    def _room_to_pixel(self, room_x: float, room_y: float) -> Tuple[float, float]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        return ox + room_x * scale, oy + room_y * scale

    def _pixel_to_room(self, px: float, py: float) -> Tuple[float, float]:
        scale, ox, oy, _, _ = self._scale_and_offset()
        return ((px - ox) / scale if scale else 0.0), ((py - oy) / scale if scale else 0.0)

    def _item_at(self, pos) -> Optional[dict]:
        for item in reversed(self.items):
            px, py = self._room_to_pixel(item.get("room_x", 0), item.get("room_y", 0))
            if (pos.x() - px) ** 2 + (pos.y() - py) ** 2 <= 12 ** 2:
                return item
        return None

    def mouseMoveEvent(self, event):
        self.setCursor(Qt.PointingHandCursor if self._item_at(event.pos()) else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        item = self._item_at(event.pos())
        if item is not None:
            self.item_clicked.emit(item)

    def paintEvent(self, event):
        p = ds.pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale, ox, oy, rw, rh = self._scale_and_offset()
        room_rect = QRectF(ox, oy, rw, rh)
        paint_room(painter, p, room_rect, scale, self.room_width, self.room_height)

        for zone in self.zones:
            x1, y1 = self._room_to_pixel(zone["x1"], zone["y1"])
            x2, y2 = self._room_to_pixel(zone["x2"], zone["y2"])
            paint_zone(painter, p, QRectF(x1, y1, x2 - x1, y2 - y1), zone.get("name", "Zone"))
            for j, drawer in enumerate(zone.get("drawers", [])):
                dx1, dy1 = self._room_to_pixel(drawer["x1"], drawer["y1"])
                dx2, dy2 = self._room_to_pixel(drawer["x2"], drawer["y2"])
                paint_drawer(painter, QRectF(dx1, dy1, dx2 - dx1, dy2 - dy1), drawer.get("name", "Drawer"), j == 0)

        for cam in self.cameras:
            if not cam.get("enabled"):
                continue
            cx, cy = self._room_to_pixel(cam.get("x", 0), cam.get("y", 0))
            paint_camera(painter, p, cx, cy, cam, room_rect,
                         label_right=cam.get("x", 0) <= self.room_width / 2)

        ordered = sorted(self.items, key=lambda it: it.get("id") == self._selected_id)
        for item in ordered:
            px, py = self._room_to_pixel(item.get("room_x", 0), item.get("room_y", 0))
            paint_pin(painter, p, px, py, item.get("label", "?"), item.get("camera_id", 0),
                      selected=item.get("id") == self._selected_id and self._selected_id is not None,
                      pulse=self._pulse)
        painter.end()
