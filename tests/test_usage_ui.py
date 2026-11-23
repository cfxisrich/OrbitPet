import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))

from PySide6.QtCore import QDate
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from models import Settings
from ui import MainWindow
from usage_store import UsageRecord, UsageStore


application = QApplication.instance() or QApplication([])
for font in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)


class UsageUITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = UsageStore(Path(self.directory.name) / 'usage.sqlite')
        self.window = MainWindow(Settings(), Path(self.directory.name))
        self.page = self.window.usage_page
        self.window.usage_requested.connect(lambda period, source, anchor: self.window.set_usage(self.store.report(period, source, date.fromisoformat(anchor))))
        self.window.show_page('usage')
        application.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        application.processEvents()
        self.store.close()
        self.directory.cleanup()

    def test_query_controls_and_month_week_navigation(self):
        spy = QSignalSpy(self.window.usage_requested)
        self.page.anchor.setDate(QDate(2024, 1, 31))
        self.page.next.click()
        self.assertEqual(self.page.current_query(), ('month', 'all', '2024-02-29'))
        self.page.period.setCurrentIndex(1)
        self.page.previous.click()
        self.assertEqual(self.page.current_query(), ('week', 'all', '2024-02-22'))
        self.page.source.setCurrentIndex(2)
        self.assertEqual(spy.at(spy.count()-1), ['week', 'orbit', '2024-02-22'])
        self.assertIn('2024-02-19 — 2024-02-25', self.page.range_label.text())

    def test_real_report_and_source_filters(self):
        moment = int(datetime(2026, 11, 17, 14, tzinfo=timezone(timedelta(hours=8))).timestamp())
        self.store.add(UsageRecord('c', 'codex', moment, 1200, 300, 1500, 900, 100))
        self.store.add(UsageRecord('o', 'orbit', moment, 700, 200, 900, 500, 50))
        self.page.anchor.setDate(QDate(2026, 11, 17))
        self.window.show_page('usage')
        self.assertEqual(self.page.values['total_tokens'].text(), '2,400')
        self.assertEqual(self.page.values['input_tokens'].text(), '1,900')
        self.assertEqual(self.page.values['cached_tokens'].text(), '1,400')
        self.assertFalse(self.page.empty.isVisible())
        self.assertEqual(self.page.table.rowCount(), 30)
        self.assertEqual(self.page.table.item(16, 5).text(), '2,400')
        self.page.source.setCurrentIndex(1)
        self.assertEqual(self.page.values['total_tokens'].text(), '1,500')
        self.page.period.setCurrentIndex(0)
        self.assertEqual(self.page.table.rowCount(), 24)
        self.assertEqual(self.page.table.item(14, 4).text(), '100')

    def test_empty_data_and_status_refresh(self):
        self.page.anchor.setDate(QDate(2026, 1, 1))
        self.assertEqual(self.page.values['total_tokens'].text(), '0')
        self.assertTrue(self.page.empty.isVisible())
        self.assertEqual(self.page.table.rowCount(), 31)
        spy = QSignalSpy(self.window.usage_refresh_requested)
        self.page.refresh_button.click()
        self.assertEqual(spy.count(), 1)
        self.window.set_usage_status('已更新 · 测试来源')
        self.assertEqual(self.page.status.text(), '已更新 · 测试来源')

    def test_small_window_navigation_and_content_render(self):
        for width, height in ((1120, 760), (800, 600)):
            self.window.resize(width, height)
            application.processEvents()
            self.assertTrue(self.page.refresh_button.isVisible())
            self.assertTrue(self.window.nav_buttons['settings'].isVisible())
            self.assertLess(self.window.nav_buttons['settings'].mapTo(self.window, self.window.nav_buttons['settings'].rect().bottomRight()).y(), self.window.height())
            self.assertFalse(self.window.grab().isNull())
        self.assertEqual(self.page.columns, 2)
        self.page.scroll.verticalScrollBar().setValue(self.page.scroll.verticalScrollBar().maximum())
        application.processEvents()
        self.assertTrue(self.page.table.isVisible())

    def test_chat_and_model_rankings_and_navigation(self):
        now = datetime.now().timestamp()
        self.store.add(UsageRecord('response', 'orbit', int(now), 2, 3, 5, model='Test', chat_id='chat'))
        report = self.store.report('day', 'all', datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date())
        spy = QSignalSpy(self.page.chat_requested)
        self.page.set_report(report, {('orbit', 'chat'): '示例 & 聊天'})
        self.page.ranks.cellWidget(0, 0).click()
        self.assertEqual(spy.at(0), ['orbit', 'chat'])
        self.page.rank_by.setCurrentIndex(1)
        self.assertEqual(self.page.ranks.item(0, 0).text(), 'Test')
        self.assertEqual(self.page.ranks.item(0, 2).text(), '5')
        self.page.set_report(report, {})
        self.page.rank_by.setCurrentIndex(0)
        self.assertIsNone(self.page.ranks.cellWidget(0, 0))
        self.assertIn('无法定位', self.page.ranks.item(0, 0).text())


if __name__ == '__main__':
    unittest.main()
