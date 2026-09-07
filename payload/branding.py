"""Keep the supplied artwork proportional on square Windows icon canvases."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QBitmap, QRegion, QPainter


def square_logo(path, size=256):
    original = QImage(str(path))
    if original.isNull():
        raise ValueError(f'Cannot load logo: {path}')
    bounds = QRegion(QBitmap.fromImage(original.createAlphaMask())).boundingRect()
    if bounds.isEmpty():
        raise ValueError('Logo contains no visible artwork')
    artwork = original.copy(bounds).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    canvas = QImage(size, size, QImage.Format_ARGB32)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawImage((size - artwork.width()) // 2, (size - artwork.height()) // 2, artwork)
    painter.end()
    return canvas
