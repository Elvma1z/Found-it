"""components/brand/Splash - the 480x320 startup card (and in-app notices
in the same style): top accent glow, the procedural magnifier mark, the
display wordmark, and a thin progress bar with the current step."""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QApplication, QSplashScreen

WIDTH, HEIGHT = 480, 320
RADIUS = 16


def _font(px: int, weight=QFont.Normal, family: str = "Segoe UI") -> QFont:
    f = QFont(family)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _draw_card(painter: QPainter, p: dict):
    rect = QRectF(0.5, 0.5, WIDTH - 1, HEIGHT - 1)
    path = QPainterPath()
    path.addRoundedRect(rect, RADIUS, RADIUS)
    painter.setClipPath(path)
    painter.fillRect(rect, QColor(p["bg"]))
    # radial-gradient(420px 260px at 50% 0%, glow-1, transparent 70%)
    painter.save()
    painter.translate(WIDTH / 2, 0)
    painter.scale(1.0, 260 / 420)
    g = QRadialGradient(QPointF(0, 0), 420 * 0.7)
    g.setColorAt(0, QColor(p["glow1"]))
    g.setColorAt(1, QColor(0, 0, 0, 0))
    painter.fillRect(QRectF(-420, -420, 840, 840), QBrush(g))
    painter.restore()
    painter.setClipping(False)
    painter.setPen(QPen(QColor(p["border_strong"]), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


def draw_magnifier(painter: QPainter, cx: float, cy: float, r: float, p: dict):
    """components/brand/Magnifier - ported from the original splash.py mark."""
    painter.save()
    painter.translate(cx, cy)
    painter.rotate(45)
    hw, hl = r * 0.3, r * 1.3
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(p["text"]))
    painter.drawRoundedRect(QRectF(r * 0.75, -hw / 2, hl, hw), hw / 2, hw / 2)
    painter.restore()

    glass = QColor(p["accent"])
    glass.setAlphaF(0.20)
    painter.setPen(Qt.NoPen)
    painter.setBrush(glass)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    painter.setPen(QPen(QColor(p["accent"]), r * 0.16))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), r, r)
    arc_r = r * 0.45
    painter.setPen(QPen(QColor(255, 255, 255, 153), r * 0.1, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(QRectF(cx - r * 0.55, cy - r * 0.78, arc_r * 2, arc_r * 2), 55 * 16, 70 * 16)


def _draw_progress(painter: QPainter, p: dict, message: str):
    left, right, bottom = 120, WIDTH - 120, HEIGHT - 32
    painter.setFont(_font(12))
    painter.setPen(QColor(p["text2"]))
    painter.drawText(QRectF(left, bottom - 24, right - left, 18), Qt.AlignLeft | Qt.AlignVCenter, message)
    track = QRectF(left, bottom - 4, right - left, 4)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(p["surface3"]))
    painter.drawRoundedRect(track, 2, 2)
    painter.setBrush(QColor(p["accent"]))
    painter.drawRoundedRect(QRectF(left + track.width() * 0.3, track.top(), track.width() * 0.35, 4), 2, 2)


def build_splash_pixmap(palette: dict, message: str = "Starting up…") -> QPixmap:
    ratio = 2.0
    pixmap = QPixmap(int(WIDTH * ratio), int(HEIGHT * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    _draw_card(painter, palette)
    draw_magnifier(painter, WIDTH / 2, 104, 30, palette)
    painter.setPen(QColor(palette["text"]))
    painter.setFont(_font(32, QFont.Bold, "Segoe UI"))
    painter.drawText(QRectF(0, 150, WIDTH, 44), Qt.AlignCenter, "Found It")
    painter.setPen(QColor(palette["text2"]))
    painter.setFont(_font(14))
    painter.drawText(QRectF(0, 194, WIDTH, 22), Qt.AlignCenter, "Never lose track of it again")
    _draw_progress(painter, palette, message)
    painter.end()
    return pixmap


def _center(splash: QSplashScreen):
    screen = QApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        splash.move(geo.center().x() - splash.width() // 2, geo.center().y() - splash.height() // 2)


def create_splash_screen(palette: dict) -> QSplashScreen:
    splash = QSplashScreen(build_splash_pixmap(palette))
    splash.setAttribute(Qt.WA_TranslucentBackground, True)
    splash._palette = palette
    _center(splash)
    return splash


def splash_show_message(splash: QSplashScreen, text: str):
    palette = getattr(splash, "_palette", None)
    if palette is None:
        splash.showMessage(text, Qt.AlignBottom | Qt.AlignHCenter)
        return
    splash.setPixmap(build_splash_pixmap(palette, text))


def build_notice_pixmap(palette: dict, title: str, message: str) -> QPixmap:
    """In-app notices (e.g. a layout change about to take effect) in the
    splash's style, instead of a plain QMessageBox."""
    ratio = 2.0
    pixmap = QPixmap(int(WIDTH * ratio), int(HEIGHT * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    _draw_card(painter, palette)

    cx, cy = WIDTH / 2, 96
    soft = QColor(palette["accent"])
    soft.setAlphaF(0.16)
    painter.setPen(Qt.NoPen)
    painter.setBrush(soft)
    painter.drawEllipse(QPointF(cx, cy), 32, 32)
    painter.setPen(QPen(QColor(palette["accent_text"]), 4, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx, cy - 12), QPointF(cx, cy + 4))
    painter.drawPoint(QPointF(cx, cy + 14))

    painter.setPen(QColor(palette["text"]))
    painter.setFont(_font(24, QFont.DemiBold, "Segoe UI"))
    painter.drawText(QRectF(20, 146, WIDTH - 40, 34), Qt.AlignCenter, title)
    painter.setPen(QColor(palette["text2"]))
    painter.setFont(_font(14))
    painter.drawText(QRectF(48, 188, WIDTH - 96, HEIGHT - 210), Qt.AlignHCenter | Qt.TextWordWrap, message)
    painter.end()
    return pixmap


def create_notice_splash(palette: dict, title: str, message: str) -> QSplashScreen:
    splash = QSplashScreen(build_notice_pixmap(palette, title, message))
    splash.setAttribute(Qt.WA_TranslucentBackground, True)
    splash._palette = palette
    _center(splash)
    return splash
