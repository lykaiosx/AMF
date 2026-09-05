"""Visible application entry point with persistent startup diagnostics."""
import os
import sys
import traceback
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
os.environ['QT_QPA_PLATFORM'] = 'windows'
try:
    import app
    app.main()
except Exception:
    details = traceback.format_exc()
    (root / 'startup-error.log').write_text(details, encoding='utf-8')
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, 'AMF could not start.\n\n' + details[-1800:], 'AMF startup error', 16)
    sys.exit(1)
