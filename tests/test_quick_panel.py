import os
import sys
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from quick_panel import QuickPanel


app = QApplication.instance() or QApplication([])
for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + font)


class QuickPanelTests(unittest.TestCase):
    def setUp(self):
        self.panel = QuickPanel()
        self.screen = app.primaryScreen()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()
        app.processEvents()

    def test_cards_fit_the_work_area_and_long_token_count_is_legible(self):
        area = self.screen.availableGeometry()
        self.panel.set_tokens(9_223_372_036_854_775_807)
        for corner in (area.topLeft(), area.topRight(), area.bottomLeft(), area.bottomRight()):
            self.panel.show_at(QRect(corner.x(), corner.y(), 1, 1), self.screen)
            app.processEvents()
            self.assertTrue(area.contains(self.panel.geometry()))
        label = self.panel.values["usage"]
        self.assertEqual(label.text(), "9,223,372,036,854,775,807")
        self.assertGreaterEqual(label.width(), label.fontMetrics().horizontalAdvance(label.text()))
        self.assertGreaterEqual(label.height(), label.fontMetrics().height())

    def test_each_card_closes_popup_and_navigates_once(self):
        spy = QSignalSpy(self.panel.open_page)
        anchor = self.screen.availableGeometry().adjusted(20, 20, -20, -20)
        for index, page in enumerate(("usage", "tasks", "focus")):
            self.panel.show_at(anchor, self.screen)
            app.processEvents()
            button = self.panel.buttons[page]
            if page == "tasks":
                QTest.keyClick(app.focusWidget(), Qt.Key.Key_Tab)
                self.assertEqual(app.focusWidget(), button)
                QTest.keyClick(button, Qt.Key.Key_Return)
            else:
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.assertEqual(spy.at(index), [page])
            self.assertFalse(self.panel.isVisible())
        self.panel.show_at(anchor, self.screen)
        QTest.keyClick(self.panel.buttons["usage"], Qt.Key.Key_Escape)
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(spy.count(), 3)

    def test_disconnected_tasks_and_all_focus_states(self):
        self.panel.set_tasks(None)
        self.assertEqual(self.panel.buttons["tasks"].accessibleDescription(), "未连接")
        self.panel.set_tasks(0)
        self.assertEqual(self.panel.values["tasks"].text(), "0 个")
        for phase, state, remaining, expected in (
            ("focus", "idle", 1500, "专注待开始 · 25:00"),
            ("focus", "running", 4.3, "专注中 · 00:05"),
            ("break", "paused", 62, "休息已暂停 · 01:02"),
            ("break", "idle", 0, "休息已完成 · 00:00"),
        ):
            self.panel.set_focus(phase, state, remaining)
            self.assertEqual(self.panel.values["focus"].text(), expected)
