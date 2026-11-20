import os
from pathlib import Path
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from models import Settings, Task
from pet_window import PetWindow
from tray import TrayIcon


app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
first = Task('a', '第一段聊天', 'completed', '', '')
second = Task('b', '第二段聊天', 'failed', '', '')
left = Qt.MouseButton.LeftButton


class PetAlerts(unittest.TestCase):
    def setUp(self):
        self.pet = PetWindow(Settings(pet_visible=False))
        self.notices = []
        self.pet.notice_requested.connect(self.notices.append)

    def tearDown(self):
        self.pet.hide()
        self.pet.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_single_double_and_drag_are_distinct(self):
        actions = []
        self.pet.panel_requested.connect(lambda: actions.append('panel'))
        self.pet.open_page.connect(actions.append)
        position = self.pet.rect().center()
        QTest.mouseClick(self.pet, left, pos=position)
        QTest.qWait(app.doubleClickInterval() + 80)
        QTest.mouseClick(self.pet, left, pos=position)
        QTest.mouseDClick(self.pet, left, pos=position)
        QTest.mouseRelease(self.pet, left, pos=position)
        QTest.mousePress(self.pet, left, pos=position)
        moved = position + QPoint(-30, -30)
        app.sendEvent(self.pet, QMouseEvent(QEvent.Type.MouseMove, QPointF(moved),
                      QPointF(self.pet.mapToGlobal(moved)), Qt.MouseButton.NoButton,
                      left, Qt.KeyboardModifier.NoModifier))
        QTest.mouseRelease(self.pet, left, pos=moved)
        QTest.qWait(app.doubleClickInterval() + 80)
        self.assertEqual(actions, ['panel', 'home'])

    def test_task_bubble_click_and_replacement(self):
        point = QPoint(26, 26)
        batch = [first, second]
        self.pet.notify('两条更新', tasks=batch)
        batch.clear()
        QTest.mouseClick(self.pet, left, pos=point)
        self.assertEqual(self.notices, [[first, second]])
        QTest.mousePress(self.pet, left, pos=point)
        self.pet.notify('新更新', tasks=[second])
        QTest.mouseRelease(self.pet, left, pos=point)
        QTest.mousePress(self.pet, left, pos=point)
        self.pet.notice_until = 0
        QTest.mouseRelease(self.pet, left, pos=point)
        self.pet.interact('pat')
        QTest.mouseClick(self.pet, left, pos=point)
        self.assertEqual(self.notices, [[first, second]])

    def test_restore_to_cursor_screen(self):
        self.pet.restore_on_cursor_screen()
        screen = app.screenAt(QCursor.pos()) or app.primaryScreen()
        self.assertTrue(self.pet.settings.pet_visible)
        self.assertEqual(self.pet.settings.monitor, screen.name())
        self.assertTrue(screen.availableGeometry().contains(self.pet.geometry()))


class TrayAlerts(unittest.TestCase):
    def test_queued_clicks_keep_their_tasks_and_panel_is_accessible(self):
        tray = TrayIcon(app)
        self.addCleanup(tray.hide)
        opened = []
        tray.panel_requested.connect(lambda: opened.append('panel'))
        tray.notice_requested.connect(opened.append)
        next(action for action in tray.menu.actions() if action.text() == '随身面板').trigger()
        tasks = [first]
        tray.notify('第一条', tasks)
        tasks.append(second)
        tray.notify('全部完成', tasks)
        tasks.clear()
        tray.task_notice.click()
        tray.task_notice.click()
        self.assertEqual(opened, ['panel', [first], [first, second]])
        self.assertIsNone(tray.task_notice)

    def test_expired_notification_does_not_dispatch(self):
        tray = TrayIcon(app)
        self.addCleanup(tray.hide)
        opened = []
        tray.notice_requested.connect(opened.append)
        tray.notify('过期', [first])
        tray.notify('新的', [second])
        tray.task_notice.timeout.timeout.emit()
        tray.task_notice.click()
        self.assertEqual(opened, [[second]])
