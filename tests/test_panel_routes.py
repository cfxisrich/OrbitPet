import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu

from app import Companion
from models import Settings, Task
from usage_store import LOCAL_TIME, UsageRecord
from windows import SingleInstance


class PanelRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        data = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, CODEX_HOME=str(data / 'codex')))
        instance = SingleInstance(f'OrbitPet.TestPanel.{os.getpid()}')
        self.addCleanup(instance.close)
        self.orbit = Companion(Settings(restore_shortcut='', pet_visible=False), instance, data, autostart=True)
        self.addCleanup(self.orbit.quit)

    def test_focus_queries_once_after_completion_and_updates_pet_pose(self):
        counts = []
        self.orbit.storage.db.set_trace_callback(lambda sql: counts.append(sql) if 'FROM focus_sessions' in sql else None)
        self.orbit.focus_action('start')
        for _ in range(3):
            self.orbit.focus_changed()
        self.assertEqual(counts, [])
        self.assertEqual(self.orbit.pet.focus_pose, 'focus')
        self.orbit.focus_action('pause')
        self.assertEqual(self.orbit.pet.focus_pose, '')
        self.orbit.focus_completed('focus', 1500)
        self.assertEqual(len(counts), 1)
        self.assertEqual(self.orbit.focus_stats, (1, 1500))
        self.orbit.focus_action('break')
        self.orbit.focus_action('start')
        self.assertEqual(self.orbit.pet.focus_pose, 'break')

    def test_metrics_land_on_matching_period_and_status(self):
        window = self.orbit.window
        now = datetime.now(LOCAL_TIME)
        self.orbit.record_usage(UsageRecord('a', 'orbit', int(now.timestamp()), 3, 2, 5))
        window.usage_page.source.setCurrentIndex(window.usage_page.source.findData('codex'))
        self.orbit.panel.open_page.emit('usage')
        self.assertEqual(window.usage_page.current_query(), ('day', 'all', now.date().isoformat()))
        self.assertEqual(window.usage_page.values['total_tokens'].text(), '5')
        window.task_search.setText('旧搜索')
        self.orbit.panel.open_page.emit('tasks')
        self.assertEqual((window.current_page, window.task_filter.currentData(), window.task_search.text()),
                         ('tasks', 'running', ''))
        self.orbit.panel.open_page.emit('focus')
        self.assertEqual(window.current_page, 'focus')

    def test_group_selection_uses_notified_thread_ids(self):
        group = [Task('first', '同名任务', 'failed', '', ''), Task('second', '同名任务', 'completed', '', '')]
        with patch.object(self.orbit, 'open_codex') as open_chat:
            self.orbit.tray.notice_requested.emit(group)
            menu = self.orbit.window.findChild(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly)
            action = next(action for action in menu.actions() if action.data() == 'second')
            self.orbit.tasks = []
            action.trigger()
            open_chat.assert_called_once_with('second')
            menu.hide()
            self.orbit.pet.notice_requested.emit(group[:1])
            self.assertEqual(open_chat.call_args.args, ('first',))

    def test_same_poll_groups_terminal_results_and_quiet_keeps_activity(self):
        a = Task('a', '任务 A', 'completed', '', '', 'turn1')
        b = Task('b', '任务 B', 'interrupted', '', '', 'turn2')
        self.orbit.update_tasks([], '已连接')
        with patch.object(self.orbit.tray, 'notify') as deliver:
            self.orbit.update_tasks([a, b], '已连接')
            self.orbit.update_tasks([a, b], '已连接')
            self.assertEqual(deliver.call_count, 1)
            self.assertEqual(list(deliver.call_args.args[1]), [a, b])
            self.orbit.settings.quiet = True
            self.orbit.update_tasks([Task('c', '任务 C', 'failed', '', '', 'turn3')], '已连接')
            self.assertEqual(deliver.call_count, 1)
        self.assertEqual(len(self.orbit.storage.activities()), 3)

    def test_unread_inbox_deep_link_failure_and_clear(self):
        self.orbit.settings.quiet = True
        self.orbit.update_tasks([], '已连接')
        a = Task('one', '项目一', 'failed', '', '', 'turn1')
        b = Task('two', '项目二', 'completed', '', '', 'turn2')
        self.orbit.update_tasks([a, b], '已连接')
        self.assertIn('2 条未读', self.orbit.panel.inbox.text())
        self.orbit.panel.inbox.click()
        w = self.orbit.window
        self.assertEqual((w.current_page, w.inbox_list.count()), ('inbox', 2))
        with patch('os.startfile', side_effect=OSError), patch.object(w, 'show_error'):
            w.inbox_open.click()
        self.assertEqual(self.orbit.storage.unread_count(), 2)
        with patch('os.startfile') as opened:
            self.orbit.tray.notice_requested.emit([a, b])
            menu = w.findChild(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly)
            next(action for action in menu.actions() if action.data() == a.id).trigger()
            opened.assert_called_once_with('codex://threads/one')
            menu.hide()
        self.assertEqual(w.inbox_list.count(), 1)
        self.assertEqual(w.inbox_list.item(0).data(Qt.ItemDataRole.UserRole).thread_id, b.id)
        w.read_all.click()
        self.assertEqual((w.inbox_list.count(), self.orbit.storage.unread_count()), (0, 0))
        w.inbox_unread.setChecked(False)
        self.assertEqual(w.inbox_list.count(), 2)
