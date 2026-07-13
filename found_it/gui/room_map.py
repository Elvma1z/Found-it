from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush
from typing import List, Tuple, Optional

from found_it.config import CAMERA_LABELS, CENTER_CAMERA_ID


class RoomMap(QWidget):
    PIN_COLORS = {
        0: QColor(255, 100, 100),
        1: QColor(100, 100, 255),
        2: QColor(100, 255, 180),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.items: List[dict] = []
        self.zones: List[dict] = []
        self.room_width = 4.0
        self.room_height = 4.0
        self.center_camera_enabled = False
        self.selected_item_id: Optional[int] = None
        self._padding = 40

    def set_room_size(self, width: float, height: float):
        self.room_width = width
        self.room_height = height
        self.update()

    def set_zones(self, zones: List[dict]):
        self.zones = zones
        self.update()

    def set_center_camera(self, enabled: bool):
        self.center_camera_enabled = enabled
        self.update()

    def update_items(self, items: List[dict]):
        self.items = items
        self.update()

    def select_item(self, item_id: Optional[int]):
        self.selected_item_id = item_id
        self.update()

    def _room_to_pixel(self, room_x: float, room_y: float) -> Tuple[int, int]:
        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        px = self._padding + int((room_x / self.room_width) * draw_w)
        py = self._padding + int((room_y / self.room_height) * draw_h)
        return px, py

    def _pixel_to_room(self, px: int, py: int) -> Tuple[float, float]:
        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        room_x = ((px - self._padding) / draw_w) * self.room_width
        room_y = ((py - self._padding) / draw_h) * self.room_height
        return room_x, room_y

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        draw_w = self.width() - 2 * self._padding
        draw_h = self.height() - 2 * self._padding
        room_rect = QRect(self._padding, self._padding, draw_w, draw_h)

        painter.setPen(QPen(QColor(60, 60, 80), 2))
        painter.setBrush(QBrush(QColor(20, 20, 35)))
        painter.drawRoundedRect(room_rect, 6, 6)

        painter.setPen(QPen(QColor(80, 80, 100), 1, Qt.DashLine))
        for i in range(1, 3):
            x = self._padding + int(draw_w * i / 3)
            painter.drawLine(x, self._padding, x, self._padding + draw_h)
            y = self._padding + int(draw_h * i / 3)
            painter.drawLine(self._padding, y, self._padding + draw_w, y)

        painter.setPen(QPen(QColor(120, 120, 160), 1))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        for i in range(3):
            x = self._padding + int(draw_w * (i + 0.5) / 3)
            painter.drawText(x - 10, self._padding + draw_h + 15, f"{(i+1)/3:.1f}")

        for zone in self.zones:
            zx1, zy1 = self._room_to_pixel(zone["x1"], zone["y1"])
            zx2, zy2 = self._room_to_pixel(zone["x2"], zone["y2"])
            painter.setPen(QPen(QColor(108, 99, 255), 1, Qt.DashLine))
            painter.setBrush(QBrush(QColor(108, 99, 255, 30)))
            painter.drawRect(zx1, zy1, zx2 - zx1, zy2 - zy1)
            painter.setPen(QPen(QColor(180, 175, 255), 1))
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            painter.drawText(zx1 + 4, zy1 + 12, zone.get("name", "Zone"))

        cam0_x, cam0_y = self._room_to_pixel(0.1, 0.1)
        cam1_x, cam1_y = self._room_to_pixel(self.room_width - 0.1, self.room_height - 0.1)

        painter.setPen(QPen(QColor(255, 100, 100), 2))
        painter.setBrush(QBrush(QColor(255, 100, 100, 80)))
        painter.drawEllipse(cam0_x - 8, cam0_y - 8, 16, 16)
        painter.drawText(cam0_x + 12, cam0_y + 5, "Cam 0")

        painter.setPen(QPen(QColor(100, 100, 255), 2))
        painter.setBrush(QBrush(QColor(100, 100, 255, 80)))
        painter.drawEllipse(cam1_x - 8, cam1_y - 8, 16, 16)
        painter.drawText(cam1_x - 40, cam1_y + 5, "Cam 1")

        if self.center_camera_enabled:
            center_px, center_py = self._room_to_pixel(
                self.room_width / 2.0, self.room_height / 2.0
            )
            painter.setPen(QPen(QColor(100, 255, 180), 2))
            painter.setBrush(QBrush(QColor(100, 255, 180, 80)))
            painter.drawEllipse(center_px - 10, center_py - 10, 20, 20)
            painter.drawText(center_px + 14, center_py + 5, "360")

            painter.setPen(QPen(QColor(100, 255, 180, 40), 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            radius = min(draw_w, draw_h) // 2 - 10
            painter.drawEllipse(center_px - radius, center_py - radius,
                                radius * 2, radius * 2)

        for item in self.items:
            room_x = item.get("room_x", 0)
            room_y = item.get("room_y", 0)
            px, py = self._room_to_pixel(room_x, room_y)

            cam_id = item.get("camera_id", 0)
            is_selected = item.get("id") == self.selected_item_id

            color = self.PIN_COLORS.get(cam_id, QColor(200, 200, 200))
            if is_selected:
                color = QColor(255, 255, 0)

            pin_size = 12 if is_selected else 8
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(px - pin_size // 2, py - pin_size // 2,
                                pin_size, pin_size)

            label = item.get("label", "?")
            cam_label = CAMERA_LABELS.get(cam_id, f"cam{cam_id}")
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            painter.setPen(QPen(QColor(200, 200, 200), 1))
            text_rect = QRect(px + 8, py - 8, 120, 16)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             f"{label} [{cam_label}]")

        painter.end()
