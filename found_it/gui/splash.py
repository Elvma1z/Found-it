from PyQt5.QtWidgets import QSplashScreen, QApplication
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PyQt5.QtCore import Qt, QRectF

BASE_COLOR = QColor("#6c63ff")
BG_COLOR = BASE_COLOR.darker(320)
LENS_GLASS_COLOR = QColor(140, 150, 255, 55)
RIM_COLOR = QColor(224, 221, 255)
HANDLE_COLOR = QColor(28, 25, 58)
HIGHLIGHT_COLOR = QColor(255, 255, 255, 140)
TITLE_COLOR = QColor(255, 255, 255)
SUBTITLE_COLOR = QColor(196, 192, 255)
MESSAGE_COLOR = QColor(170, 165, 230)

WIDTH, HEIGHT = 480, 320


def _draw_magnifier(painter: QPainter, center_x: float, center_y: float, radius: float):
    """An original, from-scratch magnifying glass icon (circle lens + angled
    handle + a glossy highlight arc) - no traced artwork, no watermark."""
    painter.save()
    painter.translate(center_x, center_y)
    painter.rotate(45)
    handle_length = radius * 1.3
    handle_width = radius * 0.3
    handle_rect = QRectF(radius * 0.75, -handle_width / 2, handle_length, handle_width)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(HANDLE_COLOR))
    painter.drawRoundedRect(handle_rect, handle_width / 2, handle_width / 2)
    painter.restore()

    lens_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(LENS_GLASS_COLOR))
    painter.drawEllipse(lens_rect)

    rim_pen = QPen(RIM_COLOR, radius * 0.16)
    painter.setPen(rim_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(lens_rect)

    highlight_pen = QPen(HIGHLIGHT_COLOR, radius * 0.1, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(highlight_pen)
    highlight_rect = QRectF(
        center_x - radius * 0.55, center_y - radius * 0.78,
        radius * 0.9, radius * 0.9
    )
    painter.drawArc(highlight_rect, 55 * 16, 70 * 16)


def build_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(WIDTH, HEIGHT)
    pixmap.fill(BG_COLOR)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    _draw_magnifier(painter, WIDTH / 2, HEIGHT * 0.36, radius=58)

    painter.setPen(TITLE_COLOR)
    painter.setFont(QFont("Segoe UI", 26, QFont.Bold))
    painter.drawText(QRectF(0, HEIGHT * 0.60, WIDTH, 44), Qt.AlignCenter, "Found It")

    painter.setPen(SUBTITLE_COLOR)
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(QRectF(0, HEIGHT * 0.60 + 40, WIDTH, 24), Qt.AlignCenter, "Never lose track of it again")

    painter.end()
    return pixmap


def create_splash_screen() -> QSplashScreen:
    splash = QSplashScreen(build_splash_pixmap())

    screen = QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        splash.move(
            geo.center().x() - splash.width() // 2,
            geo.center().y() - splash.height() // 2,
        )

    return splash


def splash_show_message(splash: QSplashScreen, text: str):
    splash.showMessage(text, Qt.AlignBottom | Qt.AlignHCenter, MESSAGE_COLOR)
