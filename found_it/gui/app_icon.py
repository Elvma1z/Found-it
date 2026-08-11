from PyQt5.QtGui import QImage, QPainter, QColor, QPen, QBrush
from PyQt5.QtCore import Qt, QRectF

# Fixed brand colors, independent of the user's theme setting - this is the
# icon Windows shows for the taskbar, desktop shortcut and Explorer, so it
# needs to read clearly against any wallpaper rather than shift with the
# in-app theme the way the splash screen does.
_DISC = QColor("#6955e7")
_GLASS = QColor(255, 255, 255, 60)
_RIM = QColor("#ffffff")
_HANDLE = QColor("#ffffff")
_HIGHLIGHT = QColor(255, 255, 255, 160)


def _draw_magnifier(painter: QPainter, center_x: float, center_y: float, radius: float):
    """Same from-scratch magnifying glass (circle lens + angled handle + a
    glossy highlight arc) used on the splash screen, redrawn in fixed
    white-on-brand-disc colors so it stays legible at 16x16."""
    painter.save()
    painter.translate(center_x, center_y)
    painter.rotate(45)
    handle_length = radius * 1.3
    handle_width = radius * 0.32
    handle_rect = QRectF(radius * 0.75, -handle_width / 2, handle_length, handle_width)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(_HANDLE))
    painter.drawRoundedRect(handle_rect, handle_width / 2, handle_width / 2)
    painter.restore()

    lens_rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(_GLASS))
    painter.drawEllipse(lens_rect)

    rim_pen = QPen(_RIM, radius * 0.22)
    painter.setPen(rim_pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(lens_rect)

    highlight_pen = QPen(_HIGHLIGHT, radius * 0.12, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(highlight_pen)
    highlight_rect = QRectF(
        center_x - radius * 0.55, center_y - radius * 0.78,
        radius * 0.9, radius * 0.9
    )
    painter.drawArc(highlight_rect, 55 * 16, 70 * 16)


def build_icon_image(size: int) -> QImage:
    """Renders the app icon (brand-colored disc + magnifying glass) at the
    given square size, for packing into a multi-resolution .ico."""
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.04
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(_DISC))
    painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))

    _draw_magnifier(painter, size / 2, size / 2, radius=size * 0.24)

    painter.end()
    return image


def generate_ico(path: str, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Builds each resolution with Qt (so strokes stay crisp instead of being
    resampled down from one large render) and packs them into a single .ico
    with Pillow, which is what actually understands the ICO container."""
    from io import BytesIO
    from PIL import Image

    frames = []
    for size in sizes:
        image = build_icon_image(size)
        buf = image.bits().asstring(image.sizeInBytes())
        pil_image = Image.frombuffer(
            "RGBA", (image.width(), image.height()), buf, "raw", "BGRA", 0, 1
        ).copy()
        frames.append(pil_image)

    # Pillow's ICO writer caps allowed sizes at the size of the image `save()`
    # is called on, so the largest frame must be the one driving the call -
    # calling it on the smallest frame silently drops every larger size.
    frames.sort(key=lambda f: f.width)
    frames[-1].save(
        path,
        format="ICO",
        sizes=[(f.width, f.height) for f in frames],
        append_images=frames[:-1],
    )


if __name__ == "__main__":
    import os
    import sys

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "resources")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "app_icon.ico")
    generate_ico(out_path)
    print(f"Wrote {os.path.abspath(out_path)}")
