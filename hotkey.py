import ctypes
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, Qt
from PySide6.QtGui import QKeySequence


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


class RestoreHotkey(QAbstractNativeEventFilter):
    def __init__(self, callback: Callable[[], None]):
        super().__init__()
        self.callback = callback
        self.sequence = ""
        self.active_id = 0
        QCoreApplication.instance().installNativeEventFilter(self)

    def set_shortcut(self, sequence: str):
        if self.sequence == sequence:
            return
        next_id = 0
        if sequence:
            shortcut = QKeySequence.fromString(sequence, QKeySequence.SequenceFormat.PortableText)
            if shortcut.count() != 1:
                raise ValueError("请录入一组快捷键。")
            combo = shortcut[0]
            modifiers = combo.keyboardModifiers()
            allowed = Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier
            if not modifiers or modifiers & ~allowed:
                raise ValueError("请使用 Ctrl、Alt 或 Shift 搭配字母、数字或功能键。")
            key = combo.key()
            alphanumeric = Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9
            function_key = Qt.Key_F1 <= key <= Qt.Key_F24 and key != Qt.Key_F12
            if not (alphanumeric or function_key):
                raise ValueError("请选择字母、数字或功能键（F12 为系统保留键）。")
            vk = int(key) if alphanumeric else 0x70 + key - Qt.Key_F1
            flags = sum(flag for modifier, flag in ((Qt.AltModifier, 1), (Qt.ControlModifier, 2),
                                                     (Qt.ShiftModifier, 4)) if modifiers & modifier)
            next_id = 0x4F51 if self.active_id == 0x4F50 else 0x4F50
            if not user32.RegisterHotKey(None, next_id, flags | 0x4000, vk):
                error = ctypes.get_last_error()
                if error == 1409:
                    raise OSError("这组快捷键已被占用，请试试其他组合。")
                raise ctypes.WinError(error)
        if self.active_id and not user32.UnregisterHotKey(None, self.active_id):
            error = ctypes.get_last_error()
            if next_id:
                user32.UnregisterHotKey(None, next_id)
            raise ctypes.WinError(error)
        self.active_id = next_id
        self.sequence = sequence

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            native = wintypes.MSG.from_address(int(message))
            if native.message == 0x0312 and self.active_id and native.wParam == self.active_id:
                self.callback()
                return True, 0
        return False, 0

    def close(self):
        self.set_shortcut("")
        QCoreApplication.instance().removeNativeEventFilter(self)
