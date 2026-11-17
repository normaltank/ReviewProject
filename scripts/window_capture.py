"""Capture only the requested native window; never read the screen desktop."""
import ctypes
from ctypes import wintypes as w


def capture_window(widget, path):
    from PIL import Image
    widget.update_idletasks()
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetAncestor.argtypes = [w.HWND, w.UINT]; user.GetAncestor.restype = w.HWND
    user.GetWindowDC.argtypes = [w.HWND]; user.GetWindowDC.restype = w.HDC
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    gdi.CreateCompatibleDC.argtypes = [w.HDC]; gdi.CreateCompatibleDC.restype = w.HDC
    gdi.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]; gdi.CreateCompatibleBitmap.restype = w.HBITMAP
    gdi.SelectObject.argtypes = [w.HDC, w.HANDLE]; gdi.SelectObject.restype = w.HANDLE
    gdi.DeleteObject.argtypes = [w.HANDLE]; gdi.DeleteDC.argtypes = [w.HDC]
    gdi.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, w.LPVOID, w.LPVOID, w.UINT]
    hwnd = user.GetAncestor(widget.winfo_id(), 2)
    rect = w.RECT()
    if not user.GetWindowRect(hwnd, ctypes.byref(rect)): raise ctypes.WinError()
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0: raise RuntimeError('window has no capture area')
    source = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(source)
    bitmap = gdi.CreateCompatibleBitmap(source, width, height)
    if not source or not memory or not bitmap: raise ctypes.WinError()
    previous = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 0): raise RuntimeError('PrintWindow failed')
        gdi.SelectObject(memory, previous)
        class Header(ctypes.Structure):
            _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG), ('planes', w.WORD),
                        ('bits', w.WORD), ('compression', w.DWORD), ('image', w.DWORD),
                        ('x', w.LONG), ('y', w.LONG), ('used', w.DWORD), ('important', w.DWORD)]
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32)
        data = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(memory, bitmap, 0, height, data, ctypes.byref(header), 0) != height:
            raise RuntimeError('GetDIBits did not capture the complete window')
        image = Image.frombuffer('RGB', (width, height), data.raw, 'raw', 'BGRX', 0, 1)
        if all(low == high for low, high in image.getextrema()): raise RuntimeError('window capture is blank')
        image.save(path)
    finally:
        gdi.SelectObject(memory, previous)
        gdi.DeleteObject(bitmap); gdi.DeleteDC(memory); user.ReleaseDC(hwnd, source)
