import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from focus import FocusTimer
from models import Settings
from pet_window import PetWindow, user32


application = QApplication.instance() or QApplication([])
application.setQuitOnLastWindowClosed(False)


class FocusTests(unittest.TestCase):
    def setUp(self):
        self.focus = FocusTimer()

    def tearDown(self):
        self.focus.timer.stop()
        application.removeNativeEventFilter(self.focus.power_filter)

    def test_actual_completion_once(self):
        done = []
        self.focus.completed.connect(lambda phase, seconds: done.append((phase, seconds)))
        self.focus.restore({"phase": "focus", "state": "paused", "remaining": 0.05, "duration": 1})
        self.focus.start()
        QTest.qWait(400)
        self.assertEqual(done, [("focus", 1)])
        self.assertEqual(self.focus.state, "idle")
        self.assertEqual(self.focus.remaining, 0)
        QTest.qWait(300)
        self.assertEqual(done, [("focus", 1)])

    def test_pause_restore_and_manual_break(self):
        self.focus.start()
        QTest.qWait(300)
        self.focus.pause()
        snapshot = self.focus.snapshot()
        QTest.qWait(300)
        self.assertEqual(self.focus.snapshot(), snapshot)
        self.assertLess(snapshot["remaining"], 1500)
        self.focus.restore({**snapshot, "state": "running"})
        self.assertEqual(self.focus.state, "paused")
        self.focus.choose_phase("break")
        self.assertEqual((self.focus.state, self.focus.remaining), ("idle", 300))
        self.focus.start()
        self.assertEqual(self.focus.state, "running")

    def test_windows_suspend_pauses_timer(self):
        self.focus.start()
        event = wintypes.MSG(message=0x0218, wParam=4)
        self.assertEqual(self.focus.power_filter.nativeEventFilter(
            b"windows_generic_MSG", ctypes.addressof(event)), (False, 0))
        self.assertEqual(self.focus.state, "paused")
        self.assertFalse(self.focus.timer.isActive())

    def test_invalid_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            self.focus.restore({"phase": "focus", "state": "paused", "duration": 60, "remaining": 100})


class PetTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(pet_visible=False)
        self.pet = PetWindow(self.settings)

    def tearDown(self):
        self.pet.animation.stop()
        self.pet.recovery.stop()
        self.pet.single_click.stop()
        self.pet.hide()
        self.pet.deleteLater()
        application.processEvents()

    def test_user_hidden_stays_hidden_and_recovery_restores_accident(self):
        self.pet._keep_visible()
        self.assertFalse(self.pet.isVisible())
        self.pet.set_visible(True)
        self.pet.hide()
        self.pet._keep_visible()
        self.assertTrue(self.pet.isVisible())
        self.settings.topmost = False
        self.pet.apply_settings()
        self.pet.hide()
        self.pet._keep_visible()
        self.assertFalse(self.pet.isVisible())

    def test_restore_and_bounds(self):
        self.settings.pet_x = 100000
        self.settings.pet_y = 100000
        self.pet.apply_settings()
        self.assertTrue(self.pet._screen().availableGeometry().contains(self.pet.geometry()))
        self.pet.restore_pet()
        self.assertTrue(self.settings.pet_visible)
        self.assertEqual(self.settings.monitor, application.primaryScreen().name())
        self.assertTrue(self.pet._screen().availableGeometry().contains(self.pet.geometry()))

    def test_native_hide_and_lost_topmost_recover(self):
        self.pet.set_visible(True)
        hwnd = int(self.pet.winId())
        user32.ShowWindow(hwnd, 0)
        self.assertFalse(user32.IsWindowVisible(hwnd))
        self.pet._keep_visible()
        self.assertTrue(user32.IsWindowVisible(hwnd))
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0013)
        self.assertFalse(user32.GetWindowLongPtrW(hwnd, -20) & 8)
        self.pet._keep_visible()
        self.assertTrue(user32.GetWindowLongPtrW(hwnd, -20) & 8)
        self.assertFalse(self.pet.hasFocus())

    def test_interaction_render_and_double_click(self):
        opened = []
        self.pet.open_page.connect(opened.append)
        self.pet.set_visible(True)
        self.pet.set_state("running")
        self.pet.interact("pat")
        self.assertEqual(self.pet.effect, "pat")
        self.assertIn("摸摸", self.pet.notice)
        application.processEvents()
        preview = self.pet.grab()
        self.assertFalse(preview.isNull())
        preview.save(str(Path(__file__).parent / "pet-preview.png"))
        QTest.mouseDClick(self.pet, Qt.MouseButton.LeftButton)
        self.assertEqual(opened, ["home"])
        self.assertFalse(self.pet.single_click.isActive())
        self.pet.notify("任务完成", "completed")
        self.assertEqual(self.pet.effect, "")
        self.assertEqual(self.pet.state, "running")


if __name__ == "__main__":
    unittest.main()
