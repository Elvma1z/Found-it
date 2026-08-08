from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap
import numpy as np
from typing import Optional

from found_it.utils.themes import get_palette


class CameraView(QLabel):
    def __init__(self, camera_id: int, parent=None, palette: Optional[dict] = None):
        super().__init__(parent)
        self.camera_id = camera_id
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignCenter)
        self.apply_theme(palette or get_palette("Indigo"))
        self.setText(f"Camera {camera_id}\nNo signal")

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

        q_image = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)

        scaled = pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def set_no_signal(self):
        self.setText(f"Camera {self.camera_id}\nNo signal")
        self.clear()
