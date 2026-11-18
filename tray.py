from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QSystemTrayIcon):
    open_page = Signal(str)
    restore_pet = Signal()
    quit_requested = Signal()

    def __init__(self, parent: QObject):
        super().__init__(QIcon(str(Path(__file__).parent / 'assets/orbit.ico')), parent)
        self.setToolTip('Orbit · 小新桌面助手')
        self.menu = QMenu()
        self.menu.addAction('打开 Orbit', lambda: self.open_page.emit('home'))
        self.menu.addAction('AI 聊天', lambda: self.open_page.emit('chat'))
        self.menu.addAction('Codex 任务', lambda: self.open_page.emit('tasks'))
        self.menu.addAction('找回宠物', self.restore_pet.emit)
        self.menu.addSeparator()
        self.menu.addAction('退出 Orbit', self.quit_requested.emit)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)

    def _activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.open_page.emit('home')

    def notify(self, text):
        self.showMessage('Orbit · 小新桌面助手', text, self.icon(), 5000)
