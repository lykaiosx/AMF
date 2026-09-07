"""Convert supplied logo to Windows icon frames without stretching the artwork."""
import struct, sys
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication
root = Path(__file__).resolve().parents[1] / 'payload'
sys.path.insert(0, str(root))
from branding import square_logo
qt = QGuiApplication([])
frames = []
for size in (16, 24, 32, 48, 64, 128, 256):
    image = square_logo(root/'logo-dark.png', size)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, 'PNG')
    frames.append((size, bytes(buffer.data())))
offset = 6 + 16 * len(frames)
entries = []
for size, data in frames:
    entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(root/'AMF.ico').write_bytes(struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries) + b''.join(data for _, data in frames))
assert square_logo(root/'logo-dark.png').save(str(root/'AMF.png'))
print('Created square Windows icon with seven proportional artwork sizes.')
