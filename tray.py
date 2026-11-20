from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QSystemTrayIcon


class TaskNotice(QPushButton):
    selected = Signal(list)
    dismissed = Signal()

    def __init__(self, text, tasks, area):
        super().__init__()
        self.tasks = tasks
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Orbit · Codex 任务提醒")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QPushButton { background:#F5FBF7; color:#254C39; border:1px solid #BCD9C8;"
                           "border-left:4px solid #65B492; padding:12px 16px; text-align:left;"
                           "font:10pt 'Microsoft YaHei UI'; } QPushButton:hover { background:#E7F5ED; }")
        self.setFixedWidth(min(330, area.width() - 24))
        title = self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.width() - 48)
        action = "打开原聊天" if len(tasks) == 1 else f"选择聊天（{len(tasks)}）"
        self.setText(f"{title.replace('&', '&&')}\n{action}  ›")
        self.setAccessibleName(f"{text}，{action}")
        self.adjustSize()
        self.move(area.right() - self.width() - 12, area.bottom() - self.height() - 12)
        self.clicked.connect(self.select_tasks)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self.close)
        self.timeout.start(7000)

    def select_tasks(self):
        self.close()
        self.selected.emit(list(self.tasks))

    def closeEvent(self, event):
        super().closeEvent(event)
        self.dismissed.emit()


class TrayIcon(QSystemTrayIcon):
    open_page = Signal(str)
    panel_requested = Signal()
    notice_requested = Signal(list)
    restore_pet = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject):
        super().__init__(QIcon(str(Path(__file__).parent / 'assets/orbit.ico')), parent)
        self.setToolTip('Orbit · 小新桌面助手')
        self.menu = QMenu()
        self.menu.addAction('随身面板', self.panel_requested.emit)
        self.menu.addAction('打开 Orbit', lambda: self.open_page.emit('home'))
        self.menu.addAction('AI 聊天', lambda: self.open_page.emit('chat'))
        self.menu.addAction('Codex 任务', lambda: self.open_page.emit('tasks'))
        self.menu.addAction('找回宠物', self.restore_pet.emit)
        self.menu.addSeparator()
        self.menu.addAction('退出 Orbit', self.quit_requested.emit)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.task_queue = deque()
        self.task_notice = None

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_page.emit('home')

    def notify(self, text, tasks=()):
        if not tasks:
            self.showMessage('Orbit · 小新桌面助手', text, self.icon(), 5000)
            return
        self.task_queue.append((text, tuple(tasks)))
        if self.task_notice is None:
            self._next_task_notice()

    def _next_task_notice(self):
        self.task_notice = None
        if not self.task_queue:
            return
        text, tasks = self.task_queue.popleft()
        screen = QApplication.screenAt(self.geometry().center()) if self.geometry().isValid() else None
        self.task_notice = TaskNotice(text, tasks, (screen or QApplication.primaryScreen()).availableGeometry())
        self.task_notice.selected.connect(self.notice_requested.emit)
        self.task_notice.dismissed.connect(self._next_task_notice)
        self.task_notice.show()

    def hide(self):
        self.task_queue.clear()
        if self.task_notice is not None:
            self.task_notice.close()
        super().hide()
