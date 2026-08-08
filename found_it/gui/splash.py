from PyQt5.QtWidgets import QSplashScreen, QApplication
from PyQt5.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PyQt5.QtCore import Qt, QRectF

WIDTH, HEIGHT = 480, 320


def _splash_colors(palette: dict) -> dict:
    """Derive the splash's look from the user's saved theme palette, instead
    of a color scheme fixed to whatever the app's original theme happened to
    be - so the very first thing shown on startup already matches."""
    accent = QColor(palette["accent"])
    return {
        "bg": QColor(palette["bg"]),
        "lens_glass": QColor(accent.red(), accent.green(), accent.blue(), 55),
        "rim": QColor(palette["accent_hover"]),
        "handle": QColor(palette["text"]),
        "highlight": QColor(255, 255, 255, 140),
        "title": QColor(palette["text"]),
        "subtitle": QColor(palette["text_dim"]),
        "message": QColor(palette["text_dim"]),
    }


def _draw_magnifier(painter: QPainter, center_x: float, center_y: float, radius: float, colors: dict):
    """An original, from-scratch magnifying glass icon (circle lens + angled
    handle + a glossy highlight arc) - no traced artwork, no watermark."""
    painter.save()
    painter.translate(center_x, center_y)
    painter.rotate(45)
    handle_length = radius * 1.3
    handle_width = radius * 0.3
    handle_rect = QRectF(radius * 0.75, -handle_width / 2, handle_length, handle_width)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(colors["handle"]))
    painter.drawRoundedRect(handle_rect, handle_width / 2, handle_width / 2)
    painter.restore()

    lens_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(colors["lens_glass"]))
    painter.drawEllipse(lens_rect)

    rim_pen = QPen(colors["rim"], radius * 0.16)
    painter.setPen(rim_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(lens_rect)

    highlight_pen = QPen(colors["highlight"], radius * 0.1, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(highlight_pen)
    highlight_rect = QRectF(
        center_x - radius * 0.55, center_y - radius * 0.78,
        radius * 0.9, radius * 0.9
    )
    painter.drawArc(highlight_rect, 55 * 16, 70 * 16)


def build_splash_pixmap(palette: dict) -> QPixmap:
    colors = _splash_colors(palette)

    pixmap = QPixmap(WIDTH, HEIGHT)
    pixmap.fill(colors["bg"])

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    _draw_magnifier(painter, WIDTH / 2, HEIGHT * 0.36, radius=58, colors=colors)

    painter.setPen(colors["title"])
    painter.setFont(QFont("Segoe UI", 26, QFont.Bold))
    painter.drawText(QRectF(0, HEIGHT * 0.60, WIDTH, 44), Qt.AlignCenter, "Found It")

    painter.setPen(colors["subtitle"])
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(QRectF(0, HEIGHT * 0.60 + 40, WIDTH, 24), Qt.AlignCenter, "Never lose track of it again")

    painter.end()
    return pixmap


def create_splash_screen(palette: dict) -> QSplashScreen:
    splash = QSplashScreen(build_splash_pixmap(palette))
    splash._theme_colors = _splash_colors(palette)

    screen = QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        splash.move(
            geo.center().x() - splash.width() // 2,
            geo.center().y() - splash.height() // 2,
        )

    return splash


def splash_show_message(splash: QSplashScreen, text: str):
    message_color = getattr(splash, "_theme_colors", {}).get("message", QColor("#aaaaaa"))
    splash.showMessage(text, Qt.AlignBottom | Qt.AlignHCenter, message_color)
