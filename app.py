import os
import sqlite3
import sys
import threading
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QDate, QObject, QRect, QSignalBlocker, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from ai_client import AiError, stream_reply
from codex_monitor import CodexMonitor
from codex_usage import CodexUsageImporter
from configuration import load_settings, save_settings
from focus import FocusTimer
from hotkey import RestoreHotkey
from models import Task, STATE_LABELS
from pet_window import PetWindow
from quick_panel import QuickPanel
from storage import Storage
from tray import TrayIcon
from ui import MainWindow
from usage_store import LOCAL_TIME, UsageRecord, UsageStore
from wardrobe import OUTFITS, Wardrobe
from windows import SingleInstance, autostart_enabled, set_autostart
from updater import confirm_startup, start_install


BASE = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent
DATA = BASE / 'data'
CONFIG = DATA / 'settings.json'
VERSION = '2.4.1'


class Events(QObject):
    tasks = Signal(list, str)
    monitor_error = Signal(str)
    delta = Signal(str, str)
    finished = Signal(str, str, str)
    usage = Signal(object)
    usage_scanned = Signal(str)


class Companion(QObject):
    def __init__(self, settings, instance: SingleInstance, data_dir=DATA, *, autostart=False):
        super().__init__()
        self.settings = settings
        self.instance = instance
        self.data_dir = data_dir
        self.config = data_dir / 'settings.json'
        self.storage = Storage(data_dir / 'orbit.sqlite')
        self.usage_store = UsageStore(data_dir / 'orbit.sqlite')
        self.usage_scanning = False
        self.events = Events(self)
        self.stopped = threading.Event()
        self.tasks: list[Task] = []
        self.seen: set[tuple[str, str, str]] = set()
        self.initialized = False
        self.monitor_ok = False
        self.closing = False
        self.active_message = ''
        self.active_conversation = ''
        self.reply_text = ''
        self.reply_dirty = False
        self.selected_id = ''
        wardrobe = Wardrobe()
        self.window = MainWindow(settings, data_dir, wardrobe)
        self.pet = PetWindow(settings, wardrobe)
        outfit = self.storage.pet_outfit()
        selected = outfit if outfit in OUTFITS else 'classic'
        self.window.show_outfit(selected)
        self.pet.set_outfit(selected)
        self.panel = QuickPanel()
        self.hotkey = RestoreHotkey(self.pet.restore_on_cursor_screen)
        try:
            self.hotkey.set_shortcut(settings.restore_shortcut)
        except (OSError, ValueError) as error:
            self.window.set_restore_shortcut(settings.restore_shortcut, '当前快捷键未启用：' + str(error))
        self.focus = FocusTimer(self)
        self.focus.configure(settings.focus_minutes, settings.break_minutes)
        self.focus.restore(self.storage.get_focus())
        self.tray = TrayIcon(self)
        self.focus_state = ''
        self.focus_stats_day = None
        self.saved_focus = None
        self._connect()
        self.refresh_usage(*self.window.usage_page.current_query())
        self.select_chat(next((item.id for item in self.storage.conversations()), ''))
        self.refresh_activity()
        self.focus_changed()
        self.pet.set_state('offline')
        if not autostart:
            self.window.show_page('home')
        self.tray.show()
        self.ticker = QTimer(self)
        self.ticker.setInterval(500)
        self.ticker.timeout.connect(self.tick)
        self.ticker.start()
        self.checkpoint = QTimer(self)
        self.checkpoint.setInterval(10000)
        self.checkpoint.timeout.connect(self.persist_focus)
        self.checkpoint.start()
        threading.Thread(target=self.watch, name='codex-monitor', daemon=True).start()
        self.usage_timer = QTimer(self)
        self.usage_timer.setInterval(30000)
        self.usage_timer.timeout.connect(self.scan_usage)
        self.usage_timer.start()
        QTimer.singleShot(0, self.scan_usage)

    def _connect(self):
        self.window.send_requested.connect(self.send)
        self.window.new_chat_requested.connect(self.new_chat)
        self.window.select_chat_requested.connect(self.select_chat)
        self.window.rename_chat_requested.connect(self.rename_chat)
        self.window.delete_chat_requested.connect(self.delete_chat)
        self.window.open_codex_requested.connect(self.open_codex)
        self.window.inbox_requested.connect(self.refresh_inbox)
        self.window.notice_open_requested.connect(self.open_recorded_notice)
        self.window.mark_all_read_requested.connect(self.mark_all_read)
        self.window.pet_visibility_requested.connect(self.pet.set_visible)
        self.window.pet_restore_requested.connect(self.pet.restore_pet)
        self.window.pet_interact_requested.connect(self.pet.interact)
        self.window.outfit_requested.connect(self.select_outfit)
        self.window.wardrobe_action_requested.connect(self.perform_action)
        self.window.pet_size_requested.connect(self.set_pet_size)
        self.window.pet_topmost_requested.connect(self.set_topmost)
        self.window.focus_action_requested.connect(self.focus_action)
        self.window.focus_config_requested.connect(self.configure_focus)
        self.window.settings_save_requested.connect(self.save_preferences)
        self.window.autostart_refresh_requested.connect(self.refresh_autostart)
        self.window.restore_shortcut_requested.connect(self.apply_shortcut)
        self.window.quit_requested.connect(self.quit)
        self.window.update_box.install_requested.connect(self.install_update)
        self.window.usage_requested.connect(self.refresh_usage)
        self.window.usage_page.chat_requested.connect(self.open_usage_chat)
        self.window.usage_refresh_requested.connect(self.scan_usage)
        self.pet.open_page.connect(self.window.show_page)
        self.pet.outfit_requested.connect(self.select_outfit)
        self.pet.action_requested.connect(self.perform_action)
        self.pet.panel_requested.connect(lambda: self.show_panel(self.pet.frameGeometry()))
        self.pet.notice_requested.connect(self.open_notice)
        self.pet.settings_changed.connect(self.pet_changed)
        self.pet.quit_requested.connect(self.quit)
        self.tray.open_page.connect(self.window.show_page)
        self.tray.panel_requested.connect(lambda: self.show_panel(self.tray.geometry()))
        self.tray.notice_requested.connect(self.open_notice)
        self.panel.open_page.connect(self.open_panel_page)
        self.tray.restore_pet.connect(self.pet.restore_pet)
        self.tray.quit_requested.connect(self.quit)
        self.events.tasks.connect(self.update_tasks)
        self.events.monitor_error.connect(self.monitor_failed)
        self.events.delta.connect(self.receive_delta)
        self.events.finished.connect(self.reply_finished)
        self.events.usage.connect(self.record_usage)
        self.events.usage_scanned.connect(self.usage_scanned)
        self.focus.changed.connect(self.focus_changed)
        self.focus.completed.connect(self.focus_completed)

    def save(self) -> bool:
        try:
            save_settings(self.config, self.settings)
        except OSError as error:
            self.window.show_error('无法保存设置：' + str(error))
            return False
        return True

    @Slot()
    def pet_changed(self):
        self.window.sync_settings()
        self.save()

    @Slot(str)
    def select_outfit(self, outfit):
        self.storage.set_pet_outfit(outfit)
        self.pet.set_outfit(outfit)
        self.window.show_outfit(outfit)

    @Slot(str)
    def perform_action(self, action):
        if self.pet.isVisible():
            self.pet.perform(action)
        self.window.preview_action(action)

    @Slot(str)
    def apply_shortcut(self, sequence):
        try:
            self.hotkey.set_shortcut(sequence)
        except (OSError, ValueError) as error:
            self.window.set_restore_shortcut(self.settings.restore_shortcut, str(error))
            return
        self.settings.restore_shortcut = sequence
        if self.save():
            self.window.set_restore_shortcut(sequence, '已启用' if sequence else '已关闭')

    def show_panel(self, anchor):
        if not anchor.isValid():
            anchor = QRect(QCursor.pos(), QCursor.pos())
        self.refresh_panel_tokens()
        self.panel.show_at(anchor, QApplication.screenAt(anchor.center()) or QApplication.primaryScreen())

    def refresh_panel_tokens(self):
        today = datetime.now(LOCAL_TIME).date()
        self.panel.set_tokens(self.usage_store.today_total(today))

    @Slot(str)
    def open_panel_page(self, page):
        if page == 'usage':
            usage = self.window.usage_page
            with QSignalBlocker(usage):
                usage.period.setCurrentIndex(usage.period.findData('day'))
                usage.source.setCurrentIndex(usage.source.findData('all'))
                usage.anchor.setDate(QDate(datetime.now(LOCAL_TIME).date()))
        if page == 'tasks':
            self.window.task_search.clear()
            self.window.task_filter.setCurrentIndex(self.window.task_filter.findData('running'))
        self.window.show_page(page)

    @Slot(list)
    def open_notice(self, tasks):
        if len(tasks) == 1:
            self.open_recorded_notice(tasks[0].id, tasks[0].notice_key)
            return
        menu = QMenu(self.window)
        menu.setTitle('选择要打开的 Codex 聊天')
        menu.addSection(menu.title())
        for task in tasks:
            title = task.title.replace('&', '&&')
            action = menu.addAction(f'{title} · {STATE_LABELS[task.state]}')
            action.setData(task.id)
            action.triggered.connect(lambda checked=False, target=task:
                                     self.open_recorded_notice(target.id, target.notice_key))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(QCursor.pos())

    @Slot(str, str)
    def open_recorded_notice(self, thread_id, event_key):
        if self.open_codex(thread_id):
            self.storage.mark_tasks_read(event_key)
            self.refresh_activity()

    @Slot()
    def mark_all_read(self):
        self.storage.mark_tasks_read()
        self.refresh_activity()

    @Slot(bool)
    def refresh_inbox(self, unread_only):
        self.window.set_inbox(self.storage.activities(-1, task_filter='unread' if unread_only else 'all'))

    @Slot(int)
    def set_pet_size(self, size):
        self.settings.pet_size = size
        self.pet.apply_settings()
        self.pet_changed()

    @Slot(bool)
    def set_topmost(self, enabled):
        self.settings.topmost = enabled
        self.pet.apply_settings()
        self.pet_changed()

    @Slot()
    def refresh_autostart(self):
        try:
            self.window.autostart.setChecked(autostart_enabled())
        except OSError as error:
            self.window.autostart.setEnabled(False)
            self.window.show_notice('无法读取 Windows 登录启动项：' + str(error))
            return
        self.window.autostart.setEnabled(True)

    @Slot(str, str, bool, bool, bool)
    def save_preferences(self, api_key, model, quiet, pet_visible, autostart):
        if self.window.autostart.isEnabled():
            try:
                set_autostart(autostart)
            except OSError as error:
                self.refresh_autostart()
                self.window.show_error('无法保存 Windows 登录启动项：' + str(error))
                return
        self.settings.api_key = api_key.strip()
        self.settings.model = model.strip()
        self.settings.quiet = quiet
        with QSignalBlocker(self.pet):
            self.pet.set_visible(pet_visible)
        self.window.sync_settings()
        if self.save():
            self.window.show_notice('设置已保存，API Key 仅在本次运行使用。')

    @Slot(str)
    def open_codex(self, thread_id):
        try:
            os.startfile('codex://threads/' + (quote(thread_id, safe='') if thread_id else 'new'))
        except OSError:
            self.window.show_error('无法打开 Codex，请确认已安装并注册 Codex 桌面应用。')
            return False
        return True

    def watch(self):
        monitor = CodexMonitor(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
        previous = ()
        while not self.stopped.is_set():
            try:
                tasks, status = monitor.poll()
                if self.stopped.is_set():
                    return
                if (tasks, status) != previous:
                    self.events.tasks.emit(tasks, status)
                    previous = tasks, status
                self.stopped.wait(3 if any(task.state == 'running' for task in tasks) else 8)
            except (OSError, ValueError) as error:
                previous = ()
                if not self.stopped.is_set():
                    self.events.monitor_error.emit(str(error))
                self.stopped.wait(8)

    @Slot(list, str)
    def update_tasks(self, tasks, status):
        if self.closing:
            return
        self.tasks = tasks
        self.monitor_ok = not status.startswith('未连接')
        self.window.set_tasks(tasks, status)
        terminal = [task for task in tasks if task.state in ('completed', 'failed', 'interrupted')]
        fresh = [task for task in terminal if (task.id, task.turn_id, task.state) not in self.seen]
        self.seen.update((task.id, task.turn_id, task.state) for task in terminal)
        if self.initialized:
            notices = [task for task in fresh if self.storage.add_activity(
                task.title + ' · ' + STATE_LABELS[task.state], 'task',
                task.notice_key, unread=True)]
            if notices:
                text = (notices[0].title[:32] + ' · ' + STATE_LABELS[notices[0].state] if len(notices) == 1
                        else f'{len(notices)} 个 Codex 任务有结果，点击选择聊天')
                self.notify(text, notices[0].state, notices)
                self.refresh_activity()
        if self.monitor_ok:
            self.initialized = True
        self.refresh_pet()

    @Slot(str)
    def monitor_failed(self, text):
        if self.closing:
            return
        self.tasks = []
        self.monitor_ok = False
        self.window.set_tasks([], '读取任务失败：' + text)
        self.refresh_pet()

    def refresh_pet(self):
        self.panel.set_tasks(sum(task.state == 'running' for task in self.tasks) if self.monitor_ok else None)
        self.pet.set_state('thinking' if self.active_message else
                           'running' if any(task.state == 'running' for task in self.tasks) else
                           'idle' if self.monitor_ok else 'offline')

    def notify(self, text, state='completed', tasks=()):
        if self.settings.quiet:
            return
        if self.settings.pet_visible:
            self.pet.notify(text, state, tasks)
            return
        self.tray.notify(text, tasks)

    def refresh_activity(self):
        unread = self.storage.unread_count()
        self.window.set_activity(self.storage.activities(5), unread)
        self.panel.set_unread(unread)
        if self.window.current_page == 'inbox':
            self.refresh_inbox(self.window.inbox_unread.isChecked())

    @Slot()
    def new_chat(self):
        self.select_chat(self.storage.create_conversation())
        self.window.show_page('chat')

    @Slot(str)
    def select_chat(self, identity):
        self.selected_id = identity
        self.window.set_conversations(self.storage.conversations(), identity)
        self.show_messages()

    def show_messages(self):
        self.window.set_messages([
            replace(message, content=self.reply_text) if message.id == self.active_message else message
            for message in self.storage.messages(self.selected_id)
        ])

    @Slot(str, str)
    def rename_chat(self, identity, title):
        if not title.strip():
            return
        self.storage.rename_conversation(identity, title.strip())
        self.window.set_conversations(self.storage.conversations(), self.selected_id)

    @Slot(str)
    def delete_chat(self, identity):
        if identity == self.active_conversation:
            self.window.show_notice('这个会话正在回复，完成后再删除。')
            return
        self.storage.delete_conversation(identity)
        self.select_chat(next((item.id for item in self.storage.conversations()), ''))

    @Slot(str, bool)
    def send(self, text, include_tasks):
        if self.active_message or not text.strip():
            return
        if not self.settings.api_key or not self.settings.model:
            self.window.show_page('settings')
            self.window.show_notice('先填写 API Key 和模型名称，再开始聊天。')
            return
        if not self.selected_id:
            self.new_chat()
        history = self.storage.messages(self.selected_id)
        if not history:
            self.storage.rename_conversation(self.selected_id, text.strip()[:28])
        messages = [(message.role, message.content) for message in history if message.status == 'completed'][-12:]
        messages.append(('user', text.strip()))
        self.storage.add_message(self.selected_id, 'user', text.strip())
        self.active_conversation = self.selected_id
        self.active_message = self.storage.add_message(self.selected_id, 'assistant', '', 'streaming')
        self.reply_text = ''
        self.window.set_busy(True)
        self.window.update_box.set_busy(True)
        self.window.set_conversations(self.storage.conversations(), self.selected_id)
        self.show_messages()
        self.refresh_pet()
        context = '\n'.join(task.title + ' | ' + STATE_LABELS[task.state] + ' | ' + task.detail + ' | ' + task.updated_at
                            for task in self.tasks) if include_tasks else ''
        threading.Thread(target=self.reply, args=(self.active_message, self.active_conversation, self.settings.api_key,
                         self.settings.model, messages, context), name='ai-reply', daemon=True).start()

    def reply(self, identity, conversation_id, api_key, model, messages, context):
        pieces = []
        try:
            for piece in stream_reply(api_key, model, messages, context, self.stopped,
                                      on_usage=lambda record: self.events.usage.emit(replace(record, chat_id=conversation_id))):
                if self.stopped.is_set():
                    return
                pieces.append(piece)
                self.events.delta.emit(identity, piece)
            if not self.stopped.is_set():
                self.events.finished.emit(identity, ''.join(pieces), '')
        except AiError as error:
            if not self.stopped.is_set():
                self.events.finished.emit(identity, ''.join(pieces), str(error))

    @Slot(str, str)
    def receive_delta(self, identity, text):
        if self.closing or identity != self.active_message:
            return
        self.reply_text += text
        self.reply_dirty = True

    @Slot(str, str, str)
    def reply_finished(self, identity, content, error):
        if self.closing or identity != self.active_message:
            return
        self.storage.update_message(identity, content + ('\n\n' + error if error else ''), 'error' if error else 'completed')
        self.active_message = ''
        self.active_conversation = ''
        self.reply_text = ''
        self.reply_dirty = False
        self.window.set_busy(False)
        self.window.update_box.set_busy(self.focus.state != 'idle')
        self.window.set_conversations(self.storage.conversations(), self.selected_id)
        self.show_messages()
        self.refresh_pet()

    @Slot()
    def tick(self):
        interval = 100 if self.active_message else 500
        if self.ticker.interval() != interval:
            self.ticker.setInterval(interval)
        if self.instance.consume_wake():
            self.window.activate()
        if self.reply_dirty and self.selected_id == self.active_conversation:
            self.show_messages()
            self.reply_dirty = False

    @Slot(object)
    def record_usage(self, record: UsageRecord):
        if self.closing:
            return
        self.usage_store.add(record)
        self.refresh_usage(*self.window.usage_page.current_query())

    @Slot(str, str, str)
    def refresh_usage(self, period, source, anchor):
        report = self.usage_store.report(period, source, date.fromisoformat(anchor))
        index = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'state_5.sqlite'
        self.window.usage_page.set_report(report, self.usage_store.chat_titles(report.chats, index))
        if self.panel.isVisible():
            self.refresh_panel_tokens()

    @Slot(str, str)
    def open_usage_chat(self, source, chat_id):
        if source == 'codex':
            self.open_codex(chat_id)
            return
        if not self.storage.db.execute('SELECT 1 FROM conversations WHERE id=?', (chat_id,)).fetchone():
            self.window.show_notice('这段桌宠聊天已删除。')
            self.refresh_usage(*self.window.usage_page.current_query())
            return
        self.select_chat(chat_id)
        self.window.show_page('chat')

    @Slot()
    def scan_usage(self):
        if self.closing or self.usage_scanning:
            return
        self.usage_scanning = True
        self.window.set_usage_status('正在读取本机 Codex 用量记录…')
        threading.Thread(target=self.scan_usage_worker, name='token-usage', daemon=True).start()

    def scan_usage_worker(self):
        try:
            with closing(UsageStore(self.data_dir / 'orbit.sqlite')) as store:
                status = CodexUsageImporter(
                    Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))), store).scan()
            if not self.stopped.is_set():
                self.events.usage_scanned.emit(status)
        except (OSError, ValueError, sqlite3.Error) as error:
            if not self.stopped.is_set():
                self.events.usage_scanned.emit('Codex 用量读取失败：' + str(error))

    @Slot(str)
    def usage_scanned(self, status):
        if self.closing:
            return
        self.usage_scanning = False
        self.window.set_usage_status(status)
        self.refresh_usage(*self.window.usage_page.current_query())

    @Slot(str)
    def focus_action(self, action):
        if action == 'start':
            self.focus.start()
        if action == 'pause':
            self.focus.pause()
        if action == 'reset':
            self.focus.reset()
        if action in ('focus', 'break'):
            self.focus.choose_phase(action)
        self.persist_focus()

    @Slot(int, int)
    def configure_focus(self, focus_minutes, break_minutes):
        self.settings.focus_minutes = focus_minutes
        self.settings.break_minutes = break_minutes
        self.focus.configure(focus_minutes, break_minutes)
        self.save()
        self.persist_focus()

    @Slot()
    def focus_changed(self):
        if self.closing:
            return
        today = datetime.now(LOCAL_TIME).date()
        if self.focus_stats_day != today:
            self.focus_stats = self.storage.focus_stats()
            self.focus_stats_day = today
        self.pet.set_focus_pose(self.focus.phase if self.focus.state == 'running' else '')
        self.panel.set_focus(self.focus.phase, self.focus.state, self.focus.remaining)
        self.window.set_focus(self.focus.phase, self.focus.state, self.focus.remaining, self.focus_stats)
        if self.focus_state != self.focus.state:
            self.window.update_box.set_busy(bool(self.active_message) or self.focus.state != 'idle')
            self.focus_state = self.focus.state
            self.persist_focus()

    @Slot()
    def persist_focus(self):
        snapshot = self.focus.snapshot()
        if snapshot != self.saved_focus:
            self.storage.set_focus(snapshot)
            self.saved_focus = snapshot
        if not self.closing and self.focus_stats_day != datetime.now(LOCAL_TIME).date():
            self.focus_changed()
        if self.active_message:
            self.storage.update_message(self.active_message, self.reply_text, 'streaming')

    @Slot(str, int)
    def focus_completed(self, phase, seconds):
        if phase == 'focus':
            self.storage.add_focus_session(seconds)
            self.focus_stats_day = None
        text = f'完成了 {seconds // 60} 分钟' + ('专注，辛苦啦！' if phase == 'focus' else '休息，准备好了再出发。')
        self.storage.add_activity(text, 'focus')
        self.refresh_activity()
        self.focus_changed()
        self.notify(text)

    @Slot()
    def install_update(self):
        box = self.window.update_box
        if self.active_message or self.focus.state != 'idle':
            box.set_busy(True)
            return
        try:
            # The one-file bootloader owns the executable until its Python child has exited.
            start_install(Path(sys.executable), box.stage, box.release.digest, os.getppid())
        except OSError as error:
            box.show_error(str(error))
            return
        self.quit()

    @Slot()
    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.stopped.set()
        self.focus.pause()
        self.persist_focus()
        if self.active_message:
            self.storage.update_message(self.active_message, self.reply_text, 'interrupted')
        self.window.remember_geometry()
        self.save()
        self.ticker.stop()
        self.checkpoint.stop()
        self.usage_timer.stop()
        self.hotkey.close()
        self.panel.hide()
        self.tray.hide()
        self.pet.hide()
        self.window.hide()
        self.storage.close()
        self.usage_store.close()
        QApplication.instance().quit()


def main():
    autostart = '--autostart' in sys.argv[1:]
    application = QApplication(sys.argv)
    application.setApplicationName('Orbit')
    application.setApplicationVersion(VERSION)
    application.setQuitOnLastWindowClosed(False)
    application.setWindowIcon(QIcon(str(Path(__file__).parent / 'assets/orbit.ico')))
    instance = SingleInstance()
    if not instance.primary:
        if not autostart:
            instance.wake()
        instance.close()
        return 0
    try:
        try:
            companion = Companion(load_settings(CONFIG, application.screens()), instance, autostart=autostart)
        except (OSError, ValueError, sqlite3.Error) as error:
            if os.environ.get('ORBIT_UPDATE_ID'):
                return 1
            QMessageBox.critical(None, 'Orbit 启动失败', str(error))
            return 1
        def report_error(error_type, error, traceback):
            if isinstance(error, (OSError, sqlite3.Error)):
                companion.window.show_error('本地数据读写失败：' + str(error))
                return
            sys.__excepthook__(error_type, error, traceback)
        sys.excepthook = report_error
        confirm_startup(DATA)
        if '--update-error' in sys.argv[1:]:
            companion.window.show_page('settings')
            companion.window.update_box.show_error((DATA / 'updates' / 'last-error.txt').read_text('utf-8'))
        return application.exec()
    finally:
        instance.close()


if __name__ == '__main__':
    raise SystemExit(main())
