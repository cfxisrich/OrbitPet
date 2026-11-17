import ctypes
from ctypes import wintypes
from dataclasses import dataclass


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


@dataclass(frozen=True)
class Screen:
    name: str
    left: int
    top: int
    right: int
    bottom: int
    primary: bool


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                      MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL

for name, arguments, result in (
    ("CreateEventW", [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
    ("CreateMutexW", [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
    ("SetEvent", [wintypes.HANDLE], wintypes.BOOL),
    ("WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
    ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
):
    getattr(kernel32, name).argtypes = arguments
    getattr(kernel32, name).restype = result


def get_screens() -> list[Screen]:
    screens = []
    errors = []

    @MONITORENUMPROC
    def collect(monitor, dc, rect, context):
        info = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            errors.append(ctypes.get_last_error())
            return False
        screens.append(Screen(info.szDevice, info.rcWork.left, info.rcWork.top,
                              info.rcWork.right, info.rcWork.bottom, bool(info.dwFlags & 1)))
        return True

    if not user32.EnumDisplayMonitors(None, None, collect, 0):
        raise ctypes.WinError(errors[0] if errors else ctypes.get_last_error())
    return screens


def screen_for_rect(x: int, y: int, width: int, height: int, screens: list[Screen]) -> Screen:
    overlap = [max(0, min(x + width, screen.right) - max(x, screen.left))
               * max(0, min(y + height, screen.bottom) - max(y, screen.top))
               for screen in screens]
    if max(overlap) == 0:
        return next(screen for screen in screens if screen.primary)
    return screens[overlap.index(max(overlap))]


def clamp_position(x: int, y: int, width: int, height: int, screen: Screen) -> tuple[int, int]:
    return (max(screen.left, min(max(screen.left, screen.right - width), x)),
            max(screen.top, min(max(screen.top, screen.bottom - height), y)))


def raise_window(widget_hwnd: int, topmost: bool):
    window = user32.GetAncestor(widget_hwnd, 2)
    if not window:
        raise OSError("无法取得 Tk 顶层窗口。")
    if not user32.SetWindowPos(window, -1 if topmost else 0, 0, 0, 0, 0, 0x0013):
        raise ctypes.WinError(ctypes.get_last_error())


class SingleInstance:
    def __init__(self, name="OrbitPet"):
        self._event = kernel32.CreateEventW(None, False, False, "Local\\" + name + ".Wake")
        if not self._event:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.set_last_error(0)
        self._mutex = kernel32.CreateMutexW(None, False, "Local\\" + name + ".Instance")
        error = ctypes.get_last_error()
        if not self._mutex:
            kernel32.CloseHandle(self._event)
            raise ctypes.WinError(error)
        self.primary = error != 183

    def wake(self):
        if not kernel32.SetEvent(self._event):
            raise ctypes.WinError(ctypes.get_last_error())

    def consume_wake(self) -> bool:
        result = kernel32.WaitForSingleObject(self._event, 0)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def close(self):
        for handle in (self._mutex, self._event):
            if not kernel32.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
