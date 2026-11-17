import ctypes
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from threading import Event, Thread


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                            wintypes.WPARAM, wintypes.LPARAM)
WM_TRAY = 0x8001


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON)]


for name, arguments, result in (
    ("RegisterClassW", [ctypes.POINTER(WNDCLASSW)], wintypes.ATOM),
    ("UnregisterClassW", [wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
    ("CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                         wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                         wintypes.HINSTANCE, wintypes.LPVOID], wintypes.HWND),
    ("DefWindowProcW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                        wintypes.LPARAM], ctypes.c_ssize_t),
    ("DestroyWindow", [wintypes.HWND], wintypes.BOOL),
    ("LoadImageW", [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                    ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.HANDLE),
    ("DestroyIcon", [wintypes.HICON], wintypes.BOOL),
    ("CreatePopupMenu", [], wintypes.HMENU),
    ("AppendMenuW", [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                     wintypes.LPCWSTR], wintypes.BOOL),
    ("DestroyMenu", [wintypes.HMENU], wintypes.BOOL),
    ("GetCursorPos", [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
    ("SetForegroundWindow", [wintypes.HWND], wintypes.BOOL),
    ("TrackPopupMenu", [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                        ctypes.c_int, ctypes.c_int, wintypes.HWND,
                        ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
    ("PostMessageW", [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                      wintypes.LPARAM], wintypes.BOOL),
    ("GetMessageW", [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                     wintypes.UINT, wintypes.UINT], ctypes.c_int),
    ("TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
    ("DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
    ("PostQuitMessage", [ctypes.c_int], None),
):
    getattr(user32, name).argtypes = arguments
    getattr(user32, name).restype = result

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL


class TrayIcon:
    def __init__(self, on_open: Callable[[], None], on_quit: Callable[[], None], on_restore: Callable[[], None]):
        self.on_open = on_open
        self.on_quit = on_quit
        self.on_restore = on_restore
        self.error: OSError | None = None
        self._ready = Event()
        self._thread = Thread(target=self._run, name="Orbit tray", daemon=True)
        self._procedure = WNDPROC(self._window_proc)
        self._hwnd = 0
        self._menu = 0

    def start(self):
        self._thread.start()
        if not self._ready.wait(5):
            raise TimeoutError("系统托盘启动超时。")
        if self.error:
            raise self.error

    def stop(self):
        if not user32.PostMessageW(self._hwnd, 0x0010, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self._thread.join(timeout=3)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0010:
            user32.PostQuitMessage(0)
            return 0
        if message != WM_TRAY:
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)
        if lparam == 0x0202:
            self.on_open()
        if lparam == 0x0205:
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(hwnd)
            selection = user32.TrackPopupMenu(self._menu, 0x0102, point.x, point.y,
                                              0, hwnd, None)
            user32.PostMessageW(hwnd, 0, 0, 0)
            if selection == 1:
                self.on_open()
            if selection == 2:
                self.on_quit()
            if selection == 3:
                self.on_restore()
        return 0

    def _run(self):
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"OrbitPet.Tray.{id(self)}"
        window_class = WNDCLASSW(lpfnWndProc=self._procedure, hInstance=instance,
                                 lpszClassName=class_name)
        registered = False
        added = False
        icon = 0
        notification = NOTIFYICONDATAW()
        try:
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            registered = True
            self._hwnd = user32.CreateWindowExW(0, class_name, "Orbit", 0,
                                                0, 0, 0, 0, None, None, instance, None)
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            self._menu = user32.CreatePopupMenu()
            if not self._menu:
                raise ctypes.WinError(ctypes.get_last_error())
            for command, label in ((3, "找回宠物"), (1, "打开面板"), (2, "退出")):
                if not user32.AppendMenuW(self._menu, 0, command, label):
                    raise ctypes.WinError(ctypes.get_last_error())
            icon = user32.LoadImageW(None, str(Path(__file__).parent / "assets" / "orbit.ico"),
                                      1, 32, 32, 0x0010)
            if not icon:
                raise ctypes.WinError(ctypes.get_last_error())
            notification = NOTIFYICONDATAW(
                cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self._hwnd, uID=1,
                uFlags=7, uCallbackMessage=WM_TRAY,
                hIcon=icon, szTip="Orbit · AI 桌面宠物")
            if not shell32.Shell_NotifyIconW(0, ctypes.byref(notification)):
                raise OSError("无法添加系统托盘图标。")
            added = True
            if not shell32.Shell_NotifyIconW(4, ctypes.byref(notification)):
                raise OSError("无法设置系统托盘通知版本。")
            self._ready.set()
            message = wintypes.MSG()
            while (result := user32.GetMessageW(ctypes.byref(message), None, 0, 0)) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
        except OSError as error:
            self.error = error
        finally:
            self._ready.set()
            if added:
                shell32.Shell_NotifyIconW(2, ctypes.byref(notification))
            if icon:
                user32.DestroyIcon(icon)
            if self._menu:
                user32.DestroyMenu(self._menu)
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
            if registered:
                user32.UnregisterClassW(class_name, instance)
