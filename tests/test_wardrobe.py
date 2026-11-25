import os
import unittest
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from models import Settings, Task
from pet_window import PetWindow
from wardrobe import ACTIONS, Wardrobe


app = QApplication.instance() or QApplication([])


class WardrobeTests(unittest.TestCase):
    def test_actions_have_distinct_poses_and_return_to_the_selected_idle(self):
        wardrobe = Wardrobe()
        for outfit, actions in ACTIONS.items():
            idle = wardrobe.idle(outfit)
            self.assertFalse(idle.isNull())
            for action in actions:
                with self.subTest(outfit=outfit, action=action):
                    duration = wardrobe.duration(outfit, action)
                    self.assertGreater(duration, 1)
                    self.assertEqual(wardrobe.frame(outfit, action, 0).cacheKey(), idle.cacheKey())
                    windup = wardrobe.frame(outfit, action, duration * .22).toImage()
                    peak = wardrobe.frame(outfit, action, duration * .56).toImage()
                    self.assertEqual(peak.size(), idle.size())
                    self.assertTrue(peak.hasAlphaChannel())
                    self.assertEqual(peak.pixelColor(0, 0).alpha(), 0)
                    self.assertNotEqual(windup, peak)
                    self.assertNotEqual(peak, idle.toImage())
                    self.assertEqual(wardrobe.frame(outfit, action, duration).cacheKey(), idle.cacheKey())

    def test_new_action_preserves_task_click_and_focus(self):
        pet = PetWindow(Settings(pet_visible=False))
        self.addCleanup(app.sendPostedEvents, None, QEvent.Type.DeferredDelete)
        self.addCleanup(pet.deleteLater)
        pet.set_outfit("hero")
        pet.set_focus_pose("focus")
        pet.perform("kick")
        self.assertEqual(pet.gesture, "kick")
        self.assertFalse(pet.animation.isActive())
        pet.gesture_started = monotonic() - 10
        pet._animate()
        self.assertEqual((pet.gesture, pet.outfit, pet.focus_pose), ("", "hero", "focus"))

        pet.perform("beam")
        task = Task("a", "构建项目", "failed", "", "")
        pet.notify("构建失败", tasks=[task])
        point = QPoint(30, 30)
        clicked = []
        pet.notice_requested.connect(clicked.append)
        QTest.mousePress(pet, Qt.MouseButton.LeftButton, pos=point)
        pet.perform("beam")
        pet.interact("feed")
        pet.set_outfit("pajama")
        QTest.mouseRelease(pet, Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(pet.gesture, "")
        self.assertEqual(pet.notice, "构建失败")
        self.assertEqual(clicked, [[task]])
        pet.notice_until = 0
        pet.perform("roll")
        self.assertEqual(pet.gesture, "roll")
