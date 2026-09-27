from PyQt5.QtWidgets import QLabel, QSizePolicy, QWidget
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QElapsedTimer, QEvent, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QPainterPath, QBrush
import numpy as np
from typing import Optional, Tuple

from found_it.gui import ds
from found_it.gui.icons import get_pixmap

HIGHLIGHT_DURATION_MS = 6000


class CameraView(QLabel):
    """components/room/CameraView - a rounded feed tile with a striped
    "No signal" placeholder and a LIVE / OFFLINE chip in the corner.
    Double-clicking it emits `expand_requested` (see CameraSpotlight)."""

    expand_requested = pyqtSignal(int)

    def __init__(self, camera_id: int, parent=None, palette: Optional[dict] = None, label: str = ""):
        super().__init__(parent)
        self.camera_id = camera_id
        self.label = label or f"Camera {camera_id}"
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._frame: Optional[QPixmap] = None
        self._frame_size: Optional[Tuple[int, int]] = None
        self._last_frame = QElapsedTimer()
        self._highlight_bbox: Optional[Tuple[int, int, int, int]] = None
        self._highlight_label: Optional[str] = None
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self.clear_highlight)
        ds.theme_bus().changed.connect(lambda _p: self.update())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return int(w * 3 / 4)

    def set_highlight(self, bbox: Tuple[int, int, int, int], label: Optional[str] = None,
                      persistent: bool = False):
        """Draw an emphasis box around a previously-detected item's last
        known bounding box. By default it clears itself after a few seconds;
        `persistent` (an actively tracked item) holds the timer off."""
        self._highlight_bbox = bbox
        self._highlight_label = label
        if persistent:
            self._highlight_timer.stop()
        else:
            self._highlight_timer.start(HIGHLIGHT_DURATION_MS)
        self.update()

    def copy_highlight_from(self, other: "CameraView"):
        """Mirror another view's highlight box - the spotlight's enlarged
        copy of a feed shows whatever the docked tile is tracking."""
        if (other._highlight_bbox, other._highlight_label) != (self._highlight_bbox, self._highlight_label):
            self._highlight_bbox = other._highlight_bbox
            self._highlight_label = other._highlight_label
            self.update()

    def frame_aspect(self) -> float:
        if self._frame_size is not None and self._frame_size[1]:
            return self._frame_size[0] / self._frame_size[1]
        return 4 / 3

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.expand_requested.emit(self.camera_id)
        super().mouseDoubleClickEvent(event)

    def clear_highlight(self):
        self._highlight_bbox = None
        self._highlight_label = None
        self.update()

    def apply_theme(self, palette: dict):
        self.update()

    def update_frame(self, frame: Optional[np.ndarray]):
        if frame is None:
            return
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        h, w, ch = rgb.shape
        self._frame_size = (w, h)
        q_image = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        self._frame = QPixmap.fromImage(q_image).scaled(
            self.size() * self.devicePixelRatioF(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._frame.setDevicePixelRatio(self.devicePixelRatioF())
        self._last_frame.start()
        self.update()

    def pixmap(self):
        return self._frame

    def set_no_signal(self):
        self._frame = None
        self._frame_size = None
        self.clear_highlight()
        self.update()

    def is_live(self) -> bool:
        return self._frame is not None and self._last_frame.isValid() and self._last_frame.elapsed() < 3000

    def paintEvent(self, event):
        p = ds.pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(p["bg"]))

        frame_rect = None
        if self._frame is not None:
            fw = self._frame.width() / self._frame.devicePixelRatio()
            fh = self._frame.height() / self._frame.devicePixelRatio()
            frame_rect = QRectF((self.width() - fw) / 2, (self.height() - fh) / 2, fw, fh)
            painter.drawPixmap(frame_rect.topLeft(), self._frame)
        else:
            # repeating-linear-gradient(135deg, surface-2 0 10px, transparent 10px 20px)
            painter.save()
            painter.setPen(QPen(QColor(p["surface2"]), 7))
            d = int(self.width() + self.height())
            for off in range(-d, d, 20):
                painter.drawLine(QPointF(off, 0), QPointF(off + self.height(), self.height()))
            painter.restore()
            cy = self.height() / 2
            painter.drawPixmap(QPointF(self.width() / 2 - 11, cy - 22), get_pixmap("video-off", p["text3"], 22))
            painter.setPen(QColor(p["text3"]))
            painter.setFont(ds.font(12.5))
            painter.drawText(QRectF(0, cy + 6, self.width(), 20), Qt.AlignHCenter, "No signal")

        if self._highlight_bbox is not None and self._frame_size is not None and frame_rect is not None:
            frame_w, frame_h = self._frame_size
            scale = frame_rect.width() / frame_w
            x1, y1, x2, y2 = self._highlight_bbox
            box = QRectF(frame_rect.left() + x1 * scale, frame_rect.top() + y1 * scale,
                         (x2 - x1) * scale, (y2 - y1) * scale)
            sel = QColor(ds.pal().get("pin_selected", "#facc15"))
            painter.setPen(QPen(sel, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(box, 4, 4)
            if self._highlight_label:
                painter.setFont(ds.font(11.5, 600))
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(self._highlight_label) + 12
                ty = box.top() - 24 if box.top() - 24 > 0 else box.bottom() + 4
                chip = QRectF(box.left(), ty, tw, 20)
                painter.setPen(Qt.NoPen)
                painter.setBrush(sel)
                painter.drawRoundedRect(chip, 5, 5)
                painter.setPen(QColor("#1a1400"))
                painter.drawText(chip, Qt.AlignCenter, self._highlight_label)

        # LIVE / OFFLINE chip
        live = self.is_live()
        painter.setFont(ds.font(11.5, 600))
        chip_text = f"{'LIVE' if live else 'OFFLINE'} · {self.label}"
        tw = painter.fontMetrics().horizontalAdvance(chip_text)
        chip = QRectF(8, 8, tw + 28, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 128))
        painter.drawRoundedRect(chip, 6, 6)
        painter.setBrush(QColor("#ef4444" if live else "#9ca3af"))
        painter.drawEllipse(QRectF(chip.left() + 8, chip.center().y() - 3, 6, 6))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(chip.adjusted(20, 0, 0, 0), Qt.AlignVCenter, chip_text)

        painter.setClipping(False)
        painter.setPen(QPen(QColor(p["border"]), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 8, 8)
        painter.end()


class CameraSpotlight(QWidget):
    """A camera feed taking primary view: an overlay child of the main
    window's central widget that covers the whole UI in a darkened shade of
    the theme's background, with the enlarged feed centred and a Close
    button just under its bottom middle. Esc closes it too."""

    closed = pyqtSignal()

    MARGIN = 40
    GAP = 14

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.hide()
        self.setFocusPolicy(Qt.StrongFocus)
        self.source: Optional[CameraView] = None
        self.view: Optional[CameraView] = None
        self._aspect = 4 / 3
        parent.installEventFilter(self)

        self.close_btn = ds.Button("Close", "secondary", icon="x", parent=self)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.clicked.connect(self.close_spotlight)
        ds.theme_bus().changed.connect(lambda _p: self.update())

    @property
    def camera_id(self) -> Optional[int]:
        return self.source.camera_id if self.source is not None else None

    def open_for(self, source: CameraView):
        if self.view is not None:
            self.view.deleteLater()
        self.source = source
        self.view = CameraView(source.camera_id, self, label=source.label)
        self.view.copy_highlight_from(source)
        self.view.show()
        self._aspect = source.frame_aspect()
        self.setGeometry(self.parentWidget().rect())
        self._relayout()
        self.show()
        self.raise_()
        self.setFocus()

    def close_spotlight(self):
        if not self.isVisible():
            return
        self.hide()
        if self.view is not None:
            self.view.deleteLater()
        self.view = None
        self.source = None
        self.closed.emit()

    def update_frame(self, frame):
        if self.view is None:
            return
        self.view.update_frame(frame)
        if self.source is not None:
            self.view.copy_highlight_from(self.source)
        aspect = self.view.frame_aspect()
        if abs(aspect - self._aspect) > 1e-3:
            self._aspect = aspect
            self._relayout()

    def _relayout(self):
        if self.view is None:
            return
        btn_h = self.close_btn.sizeHint().height()
        avail_w = max(1, self.width() - 2 * self.MARGIN)
        avail_h = max(1, self.height() - 2 * self.MARGIN - self.GAP - btn_h)
        w = min(avail_w, avail_h * self._aspect)
        h = w / self._aspect
        x = (self.width() - w) / 2
        y = (self.height() - (h + self.GAP + btn_h)) / 2
        self.view.setGeometry(int(x), int(y), int(w), int(h))
        self.close_btn.adjustSize()
        bw = self.close_btn.width()
        self.close_btn.move(int(x + (w - bw) / 2), int(y + h + self.GAP))
        self.close_btn.raise_()

    def paintEvent(self, _e):
        painter = QPainter(self)
        bg = QColor(ds.pal()["bg"]).darker(175)
        bg.setAlphaF(0.96)
        painter.fillRect(self.rect(), bg)
        painter.end()

    def mousePressEvent(self, event):
        # Swallow clicks so nothing underneath reacts; only Close / Esc exit.
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_spotlight()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        self._relayout()
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(obj.rect())
        return super().eventFilter(obj, event)
