import ctypes
import math
from ctypes import wintypes
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from models import Settings, STATE_LABELS


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL

STATE_COLORS = {
    "idle": "#59B99A", "thinking": "#A19BD3", "running": "#60AFC8",
    "waiting": "#DAAB50", "completed": "#59B99A", "failed": "#D97878",
    "interrupted": "#A19BD3", "unknown": "#81958D", "offline": "#81958D",
}


class PetWindow(QWidget):
    open_page = Signal(str)
    panel_requested = Signal()
    notice_requested = Signal(list)
    settings_changed = Signal()
    quit_requested = Signal()

    def __init__(self, settings: Settings):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.settings = settings
        self.setWindowTitle("Orbit · 小新桌宠")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets/orbit.ico")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image = QPixmap()
        if not self.image.loadFromData((Path(__file__).parent / "assets/shinchan.png").read_bytes(), "PNG"):
            raise ValueError("无法读取小新角色图片。")
        self.focus_pose = ''
        self.poses = {'': self.image}
        for phase, name in (('focus', 'reading'), ('break', 'stretch')):
            pose = QPixmap(str(Path(__file__).parent / f"assets/shinchan-{name}.png"))
            if pose.isNull():
                raise ValueError(f"无法读取小新的动作素材：{name}")
            self.poses[phase] = pose.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self.state = "idle"
        self.notice_state = "idle"
        self.notice = ""
        self.notice_until = 0.0
        self.notice_tasks = ()
        self.pressed_tasks = ()
        self.effect = ""
        self.started = monotonic()
        self.drag_origin = QPoint()
        self.drag_window_origin = QPoint()
        self.dragged = False
        self.double_clicked = False
        self.single_click = QTimer(self)
        self.single_click.setSingleShot(True)
        self.single_click.timeout.connect(self.panel_requested.emit)
        self.animation = QTimer(self)
        self.animation.timeout.connect(self._animate)
        self.recovery = QTimer(self)
        self.recovery.timeout.connect(self._keep_visible)
        self.recovery.start(2000)
        self.screen_signature = ()
        self.apply_settings()

    def _screen(self):
        return next((screen for screen in QApplication.screens()
                     if screen.name() == self.settings.monitor), QApplication.primaryScreen())

    def _place(self):
        screen = self._screen()
        area = screen.availableGeometry()
        self.render_size = min(self.settings.pet_size, area.width() - 60, area.height() - 118)
        self.setFixedSize(max(220, self.render_size + 60), self.render_size + 118)
        default_position = (self.settings.pet_x, self.settings.pet_y) == (-1, -1)
        x = area.right() - self.width() - 24 if default_position else area.left() + self.settings.pet_x
        y = area.bottom() - self.height() - 16 if default_position else area.top() + self.settings.pet_y
        self.move(max(area.left(), min(x, area.right() - self.width() + 1)),
                  max(area.top(), min(y, area.bottom() - self.height() + 1)))
        self._remember(screen)

    def _remember(self, screen):
        self.settings.monitor = screen.name()
        self.settings.pet_x = self.x() - screen.availableGeometry().left()
        self.settings.pet_y = self.y() - screen.availableGeometry().top()

    def _native_raise(self):
        user32.SetWindowPos(int(self.winId()), -1 if self.settings.topmost else -2,
                            0, 0, 0, 0, 0x0013)

    def apply_settings(self):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.settings.topmost)
        self._place()
        self.setVisible(self.settings.pet_visible)
        if self.settings.pet_visible:
            self._native_raise()
        self.update()

    def set_visible(self, visible: bool):
        self.single_click.stop()
        self.settings.pet_visible = visible
        self.setVisible(visible)
        if visible:
            self._place()
            self._native_raise()
        self.settings_changed.emit()

    def restore_pet(self, screen=None):
        self.settings.monitor = (screen or QApplication.primaryScreen()).name()
        self.settings.pet_x = -1
        self.settings.pet_y = -1
        self.set_visible(True)

    def restore_on_cursor_screen(self):
        self.restore_pet(QApplication.screenAt(QCursor.pos()))

    def set_state(self, state: str):
        self.state = state
        self.update()

    def set_focus_pose(self, phase):
        if self.focus_pose != phase:
            self.focus_pose = phase
            self.update()

    def notify(self, text: str, state="idle", tasks=()):
        self.effect = ""
        self.notice = text
        self.notice_tasks = tuple(tasks)
        self.notice_state = 'failed' if any(task.state == 'failed' for task in tasks) else state
        self.notice_until = monotonic() + 6
        self.started = monotonic()
        self.update()

    def _bubble(self):
        return QRectF(7, 6, self.width() - 14, 61)

    def interact(self, action: str):
        self.notify("嘿嘿，摸摸头，烦恼飞走啦！" if action == "pat"
                    else "小饼干收到！再陪你努力一会儿～", "completed")
        self.effect = action

    def _keep_visible(self):
        signature = tuple((screen.name(), screen.availableGeometry().getRect(), screen.devicePixelRatio())
                          for screen in QApplication.screens())
        if signature != self.screen_signature:
            self.screen_signature = signature
            self._place()
            self.settings_changed.emit()
        if not self.settings.pet_visible or not self.settings.topmost:
            return
        area = self._screen().availableGeometry()
        if not area.contains(self.geometry()):
            self._place()
            self.settings_changed.emit()
        if (not self.isVisible() or not user32.IsWindowVisible(int(self.winId()))
                or user32.IsIconic(int(self.winId()))):
            self.show()
            user32.ShowWindow(int(self.winId()), 4)
        if not user32.GetWindowLongPtrW(int(self.winId()), -20) & 0x00000008:
            self._native_raise()

    def showEvent(self, event):
        super().showEvent(event)
        self.animation.start(250)

    def hideEvent(self, event):
        self.animation.stop()
        super().hideEvent(event)

    def _animate(self):
        active = monotonic() < self.notice_until
        self.animation.setInterval(70 if active or self.state in ("thinking", "running") else 250)
        self.update()

    def paintEvent(self, event):
        now = monotonic()
        state = self.notice_state if now < self.notice_until else self.state
        elapsed = now - self.started
        active = now < self.notice_until
        sign = active and state == 'failed' and self.notice_tasks
        pose = '' if sign else self.focus_pose
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(42, 76, 63, 22))
        painter.drawEllipse(QRectF(self.width() * 0.26, self.height() - 41,
                                   self.width() * 0.48, 10))
        bounce = math.sin(elapsed * 2.1) * 2
        if state == "completed" and active:
            bounce = -abs(math.sin(elapsed * 4)) * 9
        angle = math.sin(elapsed * 4) * 3 if state == "thinking" else 0
        shake = math.sin(elapsed * 15) * 3 if state == "failed" and active else 0
        if state == "running":
            bounce = math.sin(elapsed * 5) * 3
        image_rect = QRectF((self.width() - self.render_size) / 2 + shake,
                            77 + bounce, self.render_size, self.render_size)
        if sign:
            painter.setPen(QPen(QColor("#A87A50"), 5))
            painter.drawLine(int(self.width() * 0.29), 63, int(self.width() * 0.33), int(image_rect.center().y()) + 18)
        painter.save()
        painter.translate(image_rect.center())
        painter.rotate(angle)
        painter.translate(-image_rect.center())
        painter.drawPixmap(image_rect.toRect(), self.poses[pose])
        painter.restore()
        if active:
            bubble = self._bubble()
            painter.setPen(QPen(QColor("#C78A63" if sign else "#CCE5D9"), 2 if sign else 1))
            painter.setBrush(QColor("#FFF2D9" if sign else "#FFFFFA"))
            painter.drawRoundedRect(bubble, 16, 16)
            tail = QPainterPath()
            tail.moveTo(self.width() / 2 - 6, 67)
            tail.lineTo(self.width() / 2, 75)
            tail.lineTo(self.width() / 2 + 7, 67)
            if not sign:
                painter.drawPath(tail)
            painter.setPen(QColor("#344F43"))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(bubble.adjusted(12, 4, -12, -21 if self.notice_tasks else -4),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.notice)
            if self.notice_tasks:
                painter.setFont(QFont("Microsoft YaHei UI", 8))
                painter.setPen(QColor("#35775A"))
                painter.drawText(bubble.adjusted(8, 38, -8, -4), Qt.AlignmentFlag.AlignCenter,
                                 "打开聊天  ›" if len(self.notice_tasks) == 1 else "选择聊天  ›")
            if self.effect:
                painter.setFont(QFont("Segoe UI Symbol", 18))
                painter.setPen(QColor("#E29AB4" if self.effect == "pat" else "#C89A49"))
                painter.drawText(QRectF(self.width() - 49, 82 + bounce, 38, 38),
                                 Qt.AlignmentFlag.AlignCenter, "♥" if self.effect == "pat" else "✦")
        label = "开心" if active and self.effect else STATE_LABELS[state]
        if pose and not active:
            label = "专注看书" if pose == "focus" else "休息伸展"
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        chip_width = painter.fontMetrics().horizontalAdvance(label) + 34
        chip = QRectF((self.width() - chip_width) / 2, self.height() - 25, chip_width, 23)
        painter.setPen(QPen(QColor("#D5E5DD"), 1))
        painter.setBrush(QColor("#F9FCF7"))
        painter.drawRoundedRect(chip, 11, 11)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(STATE_COLORS[state]))
        painter.drawEllipse(QRectF(chip.left() + 9, chip.top() + 9, 5, 5))
        painter.setPen(QColor("#4B6458"))
        painter.drawText(chip.adjusted(15, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, label)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.drag_origin = event.globalPosition().toPoint()
        self.drag_window_origin = self.pos()
        self.dragged = False
        self.double_clicked = False
        self.pressed_tasks = self.notice_tasks if (
            monotonic() < self.notice_until and self._bubble().contains(event.position())) else ()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return
        delta = event.globalPosition().toPoint() - self.drag_origin
        if delta.manhattanLength() < QApplication.startDragDistance() and not self.dragged:
            return
        self.single_click.stop()
        self.dragged = True
        self.move(self.drag_window_origin + delta)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.dragged:
            screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
            self._remember(screen)
            self._place()
            self.settings_changed.emit()
            return
        if self.double_clicked:
            return
        if self.pressed_tasks:
            if (self.pressed_tasks is self.notice_tasks and monotonic() < self.notice_until
                    and self._bubble().contains(event.position())):
                self.notice_requested.emit(list(self.pressed_tasks))
            return
        self.single_click.start(QApplication.doubleClickInterval())

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.single_click.stop()
        self.double_clicked = True
        if self.notice_tasks and monotonic() < self.notice_until and self._bubble().contains(event.position()):
            return
        self.open_page.emit("home")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background:#FAFCF8; color:#294B3D; border:1px solid #D7E6DD; padding:6px; }"
                           "QMenu::item { padding:8px 24px; border-radius:6px; }"
                           "QMenu::item:selected { background:#DDF2E7; }")
        menu.addAction("和小新聊聊", lambda: self.open_page.emit("chat"))
        menu.addAction("查看 Codex 任务", lambda: self.open_page.emit("tasks"))
        menu.addSeparator()
        menu.addAction("摸摸头", lambda: self.interact("pat"))
        menu.addAction("喂零食", lambda: self.interact("feed"))
        menu.addSeparator()
        menu.addAction("隐藏桌宠", lambda: self.set_visible(False))
        menu.addAction("退出 Orbit", self.quit_requested.emit)
        menu.exec(event.globalPos())

    def closeEvent(self, event):
        event.ignore()
        self.set_visible(False)
