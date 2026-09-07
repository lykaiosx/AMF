"""Check icon geometry and, optionally, the exact icons embedded in Setup.exe."""
import ctypes, struct, sys
from pathlib import Path
from PySide6.QtGui import QGuiApplication, QImage, QBitmap, QRegion, QIcon, QPixmap
root = Path(__file__).resolve().parents[1]/'payload'
sys.path.insert(0, str(root))
from branding import square_logo
qt = QGuiApplication([])
data = (root/'AMF.ico').read_bytes()
reserved, kind, count = struct.unpack_from('<HHH', data)
assert (reserved, kind, count) == (0, 1, 7)
frames = []
for index in range(count):
    width, height, _, _, _, _, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * index)
    width, height = width or 256, height or 256
    frame = data[offset:offset+length]
    image = QImage.fromData(frame)
    assert image.width() == image.height() == width == height
    bounds = QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect()
    assert abs(bounds.height()/bounds.width() - 0.562) < 2/width
    assert image.pixelColor(width//2, 0).alpha() == 0
    frames.append(frame)
for name in ('logo-dark.png', 'logo-light.png'):
    icon = QIcon(QPixmap.fromImage(square_logo(root/name)))
    for size in (16, 32, 48):
        pixmap = icon.pixmap(size, size)
        assert pixmap.width() == pixmap.height()
        assert abs(pixmap.width() / pixmap.devicePixelRatio() - size) <= 1
print('PASS: seven square icon frames preserve original artwork proportions; white/black Windows icons remain square.')

if len(sys.argv) > 1:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    module = kernel.LoadLibraryExW(str(Path(sys.argv[1]).resolve()), None, 0x22)
    assert module, ctypes.get_last_error()
    kernel.FindResourceW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel.FindResourceW.restype = ctypes.c_void_p
    kernel.SizeofResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.SizeofResource.restype = ctypes.c_uint
    kernel.LoadResource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel.LoadResource.restype = ctypes.c_void_p
    kernel.LockResource.argtypes = [ctypes.c_void_p]
    kernel.LockResource.restype = ctypes.c_void_p
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    embedded = []
    @callback_type
    def collect(handle, resource_type, name, parameter):
        resource = kernel.FindResourceW(handle, name, resource_type)
        pointer = kernel.LockResource(kernel.LoadResource(handle, resource))
        embedded.append(ctypes.string_at(pointer, kernel.SizeofResource(handle, resource)))
        return True
    kernel.EnumResourceNamesW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, callback_type, ctypes.c_ssize_t]
    kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
    try:
        assert kernel.EnumResourceNamesW(module, 3, collect, 0)
        assert all(frame in embedded for frame in frames), 'Setup does not contain the expected logo frames'
    finally:
        kernel.FreeLibrary(module)
    print('PASS: setup executable embeds all seven exact new logo frames.')
