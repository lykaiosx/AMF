"""Verify installed imports, version and window construction without changing user state."""
import os
import sys
import tempfile
from pathlib import Path


def main():
    # A script launched by its absolute path can resolve all sibling modules,
    # independent of the installer's working directory.
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    os.environ['QT_QPA_PLATFORM'] = 'windows' if sys.platform == 'win32' else 'offscreen'
    import app
    from PySide6.QtWidgets import QApplication
    expected = sys.argv[1]
    if app.APP_VERSION != expected:
        raise RuntimeError(f'Expected AMF {expected}, found {app.APP_VERSION}')
    qt = QApplication([])
    with tempfile.TemporaryDirectory(prefix='amf-verify-') as directory:
        temporary = Path(directory)
        app.APP_DIR = temporary
        app.CONFIG_FILE = temporary / 'config.json'
        app.CART_FILE = temporary / 'cart.json'
        app.PID_FILE = temporary / 'amf.pid'
        app.migrate_previous_state = lambda: None
        window = app.AnimeDownloader()
        qt.processEvents()
        window.close()
    print(f'AMF {expected}: imports, version and application window verified.')


if __name__ == '__main__':
    main()

