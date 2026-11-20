import ctypes
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication

from hotkey import RestoreHotkey, user32


app = QApplication.instance() or QApplication([])


class RestoreHotkeyTests(unittest.TestCase):
    def test_qt_dispatch_rebind_and_release(self):
        received = []
        handler = RestoreHotkey(lambda: received.append(handler.sequence))
        self.addCleanup(handler.close)
        handler.set_shortcut("Ctrl+Alt+Shift+F22")
        first_id = handler.active_id
        handler.set_shortcut("Ctrl+Alt+Shift+F23")
        for identifier in (first_id, handler.active_id):
            self.assertTrue(user32.PostThreadMessageW(ctypes.windll.kernel32.GetCurrentThreadId(),
                                                     0x0312, identifier, 0))
        app.processEvents()
        self.assertEqual(received, ["Ctrl+Alt+Shift+F23"])
        handler.set_shortcut("")
        self.assertTrue(user32.RegisterHotKey(None, 0x2100, 7, 0x86))
        self.addCleanup(user32.UnregisterHotKey, None, 0x2100)

    def test_conflict_preserves_previous_registration(self):
        handler = RestoreHotkey(lambda: None)
        self.addCleanup(handler.close)
        handler.set_shortcut("Ctrl+Alt+Shift+F22")
        self.assertTrue(user32.RegisterHotKey(None, 0x2101, 7, 0x87))
        self.addCleanup(user32.UnregisterHotKey, None, 0x2101)
        with self.assertRaises(OSError):
            handler.set_shortcut("Ctrl+Alt+Shift+F24")
        self.assertEqual(handler.sequence, "Ctrl+Alt+Shift+F22")
        self.assertFalse(user32.RegisterHotKey(None, 0x2102, 7, 0x85))

    def test_rejects_unsupported_keys(self):
        handler = RestoreHotkey(lambda: None)
        self.addCleanup(handler.close)
        for text in ("P", "Ctrl+F12", "Ctrl+P, Ctrl+Q", "Meta+P"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                handler.set_shortcut(text)
