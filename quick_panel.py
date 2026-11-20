from math import ceil

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout

from theme import icon


class MetricButton(QPushButton):
    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.sizeHint()


class QuickPanel(QFrame):
    open_page = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Orbit · 随身面板")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setStyleSheet("""
            QFrame#PanelBody { background: #FAFCF7; border: 1px solid #C9DDD0; border-radius: 16px; }
            QLabel { background: transparent; border: none; font-family: 'Microsoft YaHei UI'; color: #294A3B; }
            QLabel#Heading { font-size: 15px; font-weight: 600; }
            QLabel#Caption { font-size: 12px; color: #466959; }
            QLabel#Value { font-size: 15px; font-weight: 600; }
            QLabel#TokenValue { font-size: 23px; font-weight: 650; color: #245C46; }
            QLabel#Arrow { font-size: 18px; color: #5B816B; }
            QPushButton { background: #FFF; border: 1px solid #DCE6DC; border-radius: 10px; }
            QPushButton#usage { background: #E3F3E9; border-color: #CDE5D7; }
            QPushButton:hover, QPushButton#usage:hover { background: #D9EFE0; }
            QPushButton:focus, QPushButton#usage:focus { border: 2px solid #4F997B; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QFrame()
        body.setObjectName("PanelBody")
        outer.addWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)
        heading = QLabel("随身面板")
        heading.setObjectName("Heading")
        layout.addWidget(heading)
        self.values = {}
        self.buttons = {}
        for page, caption in (("usage", "今日 Token"), ("tasks", "执行中的 Codex 任务"), ("focus", "专注计时")):
            row = MetricButton()
            row.setObjectName(page)
            row.setAccessibleName(caption)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row.clicked.connect(lambda checked=False, target=page: self._open(target))
            grid = QGridLayout(row)
            grid.setContentsMargins(12, 7, 12, 7)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(2)
            grid.setColumnStretch(1, 1)
            glyph = QLabel()
            glyph.setPixmap(icon(page).pixmap(17, 17))
            title = QLabel(caption)
            title.setObjectName("Caption")
            value = QLabel("—")
            value.setObjectName("TokenValue" if page == "usage" else "Value")
            arrow = QLabel("›")
            arrow.setObjectName("Arrow")
            for label in (glyph, title, value, arrow):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            grid.addWidget(glyph, 0, 0)
            grid.addWidget(title, 0, 1)
            grid.addWidget(value, 1, 0, 1, 2)
            grid.addWidget(arrow, 0, 2, 2, 1)
            self.buttons[page] = row
            self.values[page] = value
            layout.addWidget(row)
        self.setMinimumWidth(286)

    def _open(self, page):
        self.hide()
        self.open_page.emit(page)

    def _set_value(self, page, text):
        self.values[page].setText(text)
        self.buttons[page].setAccessibleDescription(text)
        self.buttons[page].updateGeometry()

    def set_tokens(self, total: int):
        self._set_value("usage", f"{total:,}")

    def set_tasks(self, running: int | None):
        self._set_value("tasks", "未连接" if running is None else f"{running} 个")

    def set_focus(self, phase, state, remaining):
        name = "专注" if phase == "focus" else "休息"
        status = {"idle": "待开始", "paused": "已暂停", "running": "中"}[state]
        if state == "idle" and remaining == 0:
            status = "已完成"
        minutes, seconds = divmod(ceil(remaining), 60)
        self._set_value("focus", f"{name}{status} · {minutes:02}:{seconds:02}")

    def show_at(self, anchor: QRect, screen: QScreen):
        self.setScreen(screen)
        self.adjustSize()
        area = screen.availableGeometry()
        right_x = anchor.right() + 9
        x = right_x if right_x + self.width() <= area.right() + 1 else anchor.left() - 8 - self.width()
        y = anchor.center().y() - self.height() // 2
        self.move(max(area.left(), min(x, area.right() + 1 - self.width())),
                  max(area.top(), min(y, area.bottom() + 1 - self.height())))
        self.show()
        self.buttons["usage"].setFocus(Qt.FocusReason.PopupFocusReason)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and isinstance(self.focusWidget(), QPushButton):
            self.focusWidget().click()
            event.accept()
            return
        super().keyPressEvent(event)
