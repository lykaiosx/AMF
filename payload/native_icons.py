"""Use a themed taskbar icon and a white native title-bar icon on Windows."""
import sys,ctypes
from pathlib import Path
_cache={}
def set_native_icons(window,theme):
    if sys.platform!='win32':return
    from ctypes import wintypes
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.LoadImageW.argtypes=[wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    user.LoadImageW.restype=wintypes.HANDLE
    user.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t]
    user.SendMessageW.restype=ctypes.c_ssize_t
    for which,filename,size in [(0,'AMF.ico',32),(1,'AMF-light.ico' if theme=='Light' else 'AMF.ico',48)]:
        key=(filename,size)
        if key not in _cache:
            _cache[key]=user.LoadImageW(None,str(Path(__file__).parent/filename),1,size,size,0x10)
        if _cache[key]:user.SendMessageW(int(window.winId()),0x80,which,_cache[key])
