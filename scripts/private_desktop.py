"""Run a bounded GUI check on a private Windows desktop, never switching input."""
import ctypes
from ctypes import wintypes as w
import os
import subprocess
import sys
import uuid


def desktop_name(handle):
    size = w.DWORD()
    user.GetUserObjectInformationW(handle, 2, None, 0, ctypes.byref(size))
    value = ctypes.create_unicode_buffer(size.value // 2)
    if not user.GetUserObjectInformationW(handle, 2, value, size, ctypes.byref(size)):
        raise ctypes.WinError()
    return value.value


if os.name == 'nt':
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.OpenInputDesktop.restype = w.HANDLE
    user.CreateDesktopW.restype = w.HANDLE
    user.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]
    user.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    user.CloseDesktop.argtypes = [w.HANDLE]


def main(args):
    if os.name != 'nt' or not args:
        raise SystemExit('private desktop requires Windows and a command')
    class Startup(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                    ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                    ('charsx', w.DWORD), ('charsy', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                    ('show', w.WORD), ('reservedsize', w.WORD), ('reservedbytes', w.LPVOID),
                    ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]
    class Process(ctypes.Structure):
        _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]
    kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD,
                                     w.LPVOID, w.LPCWSTR, ctypes.POINTER(Startup), ctypes.POINTER(Process)]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    before = user.OpenInputDesktop(0, False, 1)
    if not before: raise ctypes.WinError()
    initial = desktop_name(before)
    name = 'ReviewCheck_' + uuid.uuid4().hex
    desktop = user.CreateDesktopW(name, None, None, 0, 0x01ff, None)
    if not desktop: raise ctypes.WinError()
    process = Process()
    try:
        import msvcrt
        startup = Startup(cb=ctypes.sizeof(Startup), desktop='WinSta0\\' + name, flags=0x100)
        handles = [msvcrt.get_osfhandle(stream.fileno()) for stream in (sys.stdin, sys.stdout, sys.stderr)]
        old = [os.get_handle_inheritable(h) for h in handles]
        for h in handles: os.set_handle_inheritable(h, True)
        startup.stdin, startup.stdout, startup.stderr = handles
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        print(f'PRIVATE DESKTOP before={initial} child={name}', flush=True)
        try:
            if not kernel.CreateProcessW(None, command, None, None, True, 0, None, os.getcwd(), ctypes.byref(startup), ctypes.byref(process)):
                raise ctypes.WinError()
        finally:
            for h, state in zip(handles, old): os.set_handle_inheritable(h, state)
        if kernel.WaitForSingleObject(process.process, 1200000) != 0:
            kernel.TerminateProcess(process.process, 124)
            kernel.WaitForSingleObject(process.process, 10000)
            raise RuntimeError('private desktop check timed out')
        result = w.DWORD()
        if not kernel.GetExitCodeProcess(process.process, ctypes.byref(result)): raise ctypes.WinError()
        after = user.OpenInputDesktop(0, False, 1)
        if not after: raise ctypes.WinError()
        try: final = desktop_name(after)
        finally: user.CloseDesktop(after)
        print(f'PRIVATE DESKTOP after={final} unchanged={initial == final} exit={result.value}', flush=True)
        if initial != final: raise RuntimeError('input desktop changed during check')
        return result.value
    finally:
        if process.thread: kernel.CloseHandle(process.thread)
        if process.process: kernel.CloseHandle(process.process)
        user.CloseDesktop(desktop)
        user.CloseDesktop(before)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
