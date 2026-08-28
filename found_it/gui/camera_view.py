from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont
import numpy as np
from typing import Optional, Tuple

from found_it.utils.themes import get_palette

HIGHLIGHT_DURATION_MS = 6000


class CameraView(QLabel):
    def __init__(self, camera_id: int, parent=None, palette: Optional[dict] = None):
        super().__init__(parent)
        self.camera_id = camera_id
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignCenter)
        self.apply_theme(palette or get_palette("Indigo"))
        self.setText(f"Camera {camera_id}\nNo signal")
        self._frame_size: Optional[Tuple[int, int]] = None
        self._highlight_bbox: Optional[Tuple[int, int, int, int]] = None
        self._highlight_label: Optional[str] = None
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self.clear_highlight)

    def set_highlight(self, bbox: Tuple[int, int, int, int], label: Optional[str] = None,
                       persistent: bool = False):
        """Draw an emphasis box around a previously-detected item's last
        known bounding box, so the user can see where it was found instead
        of having to hunt for it in the raw feed.

        By default it clears itself after a few seconds since the object
        may have moved on since detection. When `persistent` is True (an
        actively tracked item - main_window keeps calling this every
        detection cycle with its latest position), the auto-clear timer is
        held off instead, so the box stays up at wherever it was last
        drawn - including staying put once the item's no longer being
        redetected - rather than vanishing on a fixed timer."""
        self._highlight_bbox = bbox
        self._highlight_label = label
        if persistent:
            self._highlight_timer.stop()
        else:
            self._highlight_timer.start(HIGHLIGHT_DURATION_MS)
        self.update()

    def clear_highlight(self):
        self._highlight_bbox = None
        self._highlight_label = None
        self.update()

    def apply_theme(self, palette: dict):
        self.palette = palette
        p = palette
        self.setStyleSheet(
            f"background-color: {p['bg']}; border: 2px solid {p['border']}; border-radius: 4px; color: {p['text_dim']};"
        )

    def update_frame(self, frame: Optional[np.ndarray]):
        if frame is None:
            return

        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        self._frame_size = (w, h)

        q_image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        scaled = pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def set_no_signal(self):
        self.setText(f"Camera {self.camera_id}\nNo signal")
        self.clear()
        self._frame_size = None
        self.clear_highlight()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._highlight_bbox is None or self._frame_size is None or self.pixmap() is None:
            return

        frame_w, frame_h = self._frame_size
        pixmap_w, pixmap_h = self.pixmap().width(), self.pixmap().height()
        if frame_w <= 0 or frame_h <= 0 or pixmap_w <= 0 or pixmap_h <= 0:
            return

        # The pixmap is scaled to fit with its aspect ratio kept, then
        # centered by the label's own alignment - so the bbox (in original
        # frame pixel coords) needs the same scale plus that centering offset.
        scale = pixmap_w / frame_w
        ox = (self.width() - pixmap_w) / 2.0
        oy = (self.height() - pixmap_h) / 2.0

        x1, y1, x2, y2 = self._highlight_bbox
        rx1 = ox + x1 * scale
        ry1 = oy + y1 * scale
        rx2 = ox + x2 * scale
        ry2 = oy + y2 * scale

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(255, 220, 0), 3)
        painter.setPen(pen)
        painter.drawRect(int(rx1), int(ry1), int(rx2 - rx1), int(ry2 - ry1))

        if self._highlight_label:
            painter.setFont(QFont("Segoe UI", 9, QFont.Bold))
            text_y = ry1 - 6 if ry1 - 20 > 0 else ry2 + 16
            painter.drawText(int(rx1), int(text_y), self._highlight_label)
        painter.end()
