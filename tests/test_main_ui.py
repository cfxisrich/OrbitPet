import os
from pathlib import Path
import sys
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(Path(__file__).parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QInputMethodEvent, QKeySequence
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QPushButton

from models import Activity, Conversation, Message, Settings, Task
from ui import MainWindow


application = QApplication.instance() or QApplication([])
for font in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)


class MainWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = MainWindow(Settings(), Path(__file__).parent / 'data')
        self.window.show()
        application.processEvents()

    def tearDown(self):
        self.window.hide()
        self.window.deleteLater()
        application.processEvents()

    def test_pages_render_and_chat_input_survives_small_window(self):
        for page in self.window.pages:
            self.window.show_page(page)
            application.processEvents()
            self.assertFalse(self.window.grab().isNull())
        self.window.resize(740, 520)
        self.window.show_page('chat')
        application.processEvents()
        self.assertTrue(self.window.chat_input.isVisible())
        self.assertTrue(self.window.send_button.isVisible())
        self.assertLessEqual(self.window.send_button.mapTo(self.window, self.window.send_button.rect().bottomRight()).y(), self.window.height())

    def test_enter_submits_and_shift_enter_and_ime_do_not(self):
        self.window.show_page('chat')
        spy = QSignalSpy(self.window.send_requested)
        self.window.chat_input.setPlainText('hello')
        QTest.keyClick(self.window.chat_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(spy.count(), 0)
        QTest.keyClick(self.window.chat_input, Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)
        QApplication.sendEvent(self.window.chat_input, QInputMethodEvent('拼', []))
        QTest.keyClick(self.window.chat_input, Qt.Key.Key_Return)
        self.assertEqual(spy.count(), 1)

    def test_messages_follow_selected_conversation(self):
        conversations = [Conversation('a', '第一段', ''), Conversation('b', '第二段', '')]
        self.window.set_conversations(conversations, 'a')
        self.window.set_messages([Message('m1', 'a', 'assistant', '你好', 'streaming', '')])
        self.window.append_reply('m1', '，朋友')
        self.assertEqual(self.window.message_cards['m1'].content, '你好，朋友')
        self.window.set_conversations(conversations, 'b')
        self.window.set_messages([Message('m2', 'b', 'user', '新会话', 'completed', '')])
        self.window.append_reply('m1', '晚到的数据')
        self.assertEqual(list(self.window.message_cards), ['m2'])
        self.assertEqual(self.window.message_cards['m2'].content, '新会话')
        self.window.set_busy(True)
        self.assertFalse(self.window.send_button.isEnabled())
        self.assertFalse(self.window.delete_button.isEnabled())

    def test_task_filters_and_summary_use_real_snapshot(self):
        self.window.set_tasks([
            Task('a', '修复聊天界面', 'running', '最近有活动', '11-17 10:00'),
            Task('b', '完成图标', 'completed', '本轮完成', '11-17 09:00')], '本地只读监测')
        self.assertEqual(self.window.stat_values['running'].text(), '1')
        self.assertEqual(self.window.stat_values['completed'].text(), '1')
        self.window.task_search.setText('图标')
        self.assertEqual(self.window.task_list.count(), 1)
        self.assertEqual(self.window.task_detail_title.text(), '完成图标')
        self.window.task_filter.setCurrentIndex(1)
        self.assertEqual(self.window.task_list.count(), 0)
        self.assertFalse(self.window.task_open.isEnabled())

    def test_focus_and_close_preserve_background_lifecycle(self):
        self.window.set_focus('focus', 'running', 65, (2, 3000))
        self.assertEqual(self.window.home_timer.text(), '01:05')
        self.assertFalse(self.window.focus_start.isEnabled())
        self.assertTrue(self.window.focus_pause.isEnabled())
        self.assertEqual(self.window.stat_values['focus'].text(), '50')
        spy = QSignalSpy(self.window.quit_requested)
        self.window.close()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(spy.count(), 0)
        self.assertTrue(self.window.settings.main_geometry)
        self.window.activate()
        self.assertTrue(self.window.isVisible())

    def test_pet_updates_do_not_overwrite_settings_drafts(self):
        self.window.api_key.setText('draft-key')
        self.window.model_name.setText('draft-model')
        self.window.focus_duration.setValue(40)
        self.window.quiet.setChecked(True)
        self.window.settings.pet_size = 240
        self.window.sync_settings()
        self.assertEqual(self.window.api_key.text(), 'draft-key')

        self.assertEqual(self.window.model_name.text(), 'draft-model')
        self.assertEqual(self.window.focus_duration.value(), 40)
        self.assertTrue(self.window.quiet.isChecked())
        self.assertEqual(self.window.pet_size.value(), 240)
        self.window.settings.model = 'saved-model'
        self.window.sync_settings()
        self.assertEqual(self.window.model_name.text(), 'saved-model')
        self.assertEqual(self.window.api_key.text(), 'draft-key')

    def test_waking_minimized_window_keeps_maximized_state(self):
        self.window.showMaximized()
        application.processEvents()
        self.window.showMinimized()
        self.window.activate()
        application.processEvents()
        self.assertTrue(self.window.isMaximized())
        self.assertFalse(self.window.isMinimized())

    def test_settings_refresh_and_save_autostart_independently_of_pet(self):
        refresh = QSignalSpy(self.window.autostart_refresh_requested)
        saved = QSignalSpy(self.window.settings_save_requested)
        self.window.nav_buttons['settings'].click()
        self.assertEqual(refresh.count(), 1)
        save_button = next(b for b in self.window.findChildren(QPushButton) if b.text() == '保存设置')
        for pet_visible, autostart in ((False, True), (True, False)):
            self.window.startup_pet.setChecked(pet_visible)
            self.window.autostart.setChecked(autostart)
            save_button.click()
            self.assertEqual(saved.at(saved.count() - 1)[3:], [pet_visible, autostart])
        self.window.show_page('home')
        self.window.show_page('settings')
        self.assertEqual(refresh.count(), 2)

    def test_restore_shortcut_can_change_and_clear_independently(self):
        self.window.show_page('settings')
        shortcuts = QSignalSpy(self.window.restore_shortcut_requested)
        settings = QSignalSpy(self.window.settings_save_requested)
        apply = next(b for b in self.window.findChildren(QPushButton) if b.text() == '应用快捷键')
        self.assertEqual(self.window.restore_shortcut_edit.keySequence().toString(), 'Ctrl+Alt+P')
        self.window.restore_shortcut_edit.setKeySequence(QKeySequence('Ctrl+Alt+K'))
        apply.click()
        self.window.restore_shortcut_edit.clear()
        apply.click()
        self.assertEqual([shortcuts.at(i) for i in range(shortcuts.count())], [['Ctrl+Alt+K'], ['']])
        self.assertEqual(settings.count(), 0)


if __name__ == '__main__':
    unittest.main()
