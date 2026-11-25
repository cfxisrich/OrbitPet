import math
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QByteArray, QRectF, QSignalBlocker, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QKeySequenceEdit,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
    QSplitter, QStackedWidget, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from models import STATE_LABELS, Settings, Task
from theme import STYLE, icon
from usage_page import UsagePage
from updater import UpdateBox
from wardrobe import ACTIONS, OUTFITS, Wardrobe


ASSETS = Path(__file__).parent / "assets"


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setObjectName("Primary" if primary else "")
    widget.clicked.connect(callback)
    return widget


def card(name="Card", margins=22):
    widget = QFrame()
    widget.setObjectName(name)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(12)
    return widget, layout


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()


class ChatEditor(QPlainTextEdit):
    submitted = Signal()

    def __init__(self):
        super().__init__()
        self.composing = False
        self.setPlaceholderText("今天想聊些什么？")
        self.setFixedHeight(82)

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier and not self.composing:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class MarkdownView(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDefaultStyleSheet("p { margin: 5px 0; } pre { background: #F0F4EF; padding: 12px; font-family: Consolas; } code { font-family: Consolas; } a { color: #33866B; }")
        self.document().documentLayout().documentSizeChanged.connect(self.fit_height)
        self.anchorClicked.connect(self.open_link)

    def loadResource(self, resource_type, url):
        if resource_type == QTextDocument.ResourceType.ImageResource:
            return QByteArray()
        return super().loadResource(resource_type, url)

    def open_link(self, url):
        if url.scheme() in ("https", "http"):
            QDesktopServices.openUrl(url)

    def fit_height(self):
        self.setFixedHeight(max(34, math.ceil(self.document().size().height()) + 12))

    def set_content(self, text):
        self.document().setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML)
        self.fit_height()


class MessageCard(QFrame):
    def __init__(self, message):
        super().__init__()
        self.content = ""
        self.status = ""
        self.setObjectName("UserMessage" if message.role == "user" else "Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(3)
        header = QHBoxLayout()
        header.addWidget(label("你" if message.role == "user" else "小新 · Orbit", "SectionTitle"))
        header.addStretch()
        self.status_label = label("", "Muted")
        header.addWidget(self.status_label)
        copy_button = button("复制", lambda: QApplication.clipboard().setText(self.content))
        copy_button.setObjectName("Quiet")
        header.addWidget(copy_button)
        layout.addLayout(header)
        self.body = MarkdownView()
        layout.addWidget(self.body)
        self.update_message(message.content, message.status)

    def update_message(self, content, status):
        if self.content != content or self.status != status:
            self.content, self.status = content, status
            self.body.set_content(content or ("正在想一想…" if status == "streaming" else "本次回复没有内容。"))
            self.status_label.setText({"streaming": "正在回复", "error": "回复失败", "interrupted": "回复已中断", "completed": ""}[status])


class FocusDial(QWidget):
    def __init__(self):
        super().__init__()
        self.remaining = 25 * 60
        self.total = 25 * 60
        self.caption = "准备好，开始一段专注"
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = min(self.width() - 24, self.height() - 20, 270)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.setPen(QPen(QColor("#E6F0E7"), 9))
        painter.drawEllipse(QRectF(-diameter / 2, -diameter / 2, diameter, diameter))
        pen = QPen(QColor("#6ABD99"), 9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(QRectF(-diameter / 2, -diameter / 2, diameter, diameter), 90 * 16,
                        -round(360 * 16 * min(1, self.remaining / self.total)))
        painter.setPen(QColor("#25332F"))
        painter.setFont(QFont("Segoe UI", 37, QFont.Weight.DemiBold))
        seconds = max(0, math.ceil(self.remaining))
        painter.drawText(QRectF(-diameter / 2, -40, diameter, 65), Qt.AlignmentFlag.AlignCenter, f"{seconds // 60:02}:{seconds % 60:02}")
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor("#7B8B81"))
        painter.drawText(QRectF(-diameter / 2, 30, diameter, 30), Qt.AlignmentFlag.AlignCenter, self.caption)


class MainWindow(QMainWindow):
    send_requested = Signal(str, bool)
    new_chat_requested = Signal()
    select_chat_requested = Signal(str)
    rename_chat_requested = Signal(str, str)
    delete_chat_requested = Signal(str)
    open_codex_requested = Signal(str)
    inbox_requested = Signal(bool)
    notice_open_requested = Signal(str, str)
    mark_all_read_requested = Signal()
    pet_visibility_requested = Signal(bool)
    pet_size_requested = Signal(int)
    pet_topmost_requested = Signal(bool)
    pet_restore_requested = Signal()
    pet_interact_requested = Signal(str)
    outfit_requested = Signal(str)
    wardrobe_action_requested = Signal(str)
    focus_action_requested = Signal(str)
    focus_config_requested = Signal(int, int)
    settings_save_requested = Signal(str, str, bool, bool, bool)
    autostart_refresh_requested = Signal()
    restore_shortcut_requested = Signal(str)
    quit_requested = Signal()
    usage_requested = Signal(str, str, str)
    usage_refresh_requested = Signal()

    def __init__(self, settings: Settings, data_dir: Path, wardrobe: Wardrobe | None = None):
        super().__init__()
        self.settings = settings
        self.form_snapshot = (settings.api_key, settings.model, settings.focus_minutes,
                              settings.break_minutes, settings.quiet, settings.pet_visible)
        self.data_dir = data_dir
        self.selected_id = ""
        self.message_conversation = ""
        self.busy = False
        self.tasks: list[Task] = []
        self.message_cards: dict[str, MessageCard] = {}
        self.conversation_titles: dict[str, str] = {}
        self.scroll_positions: dict[str, int] = {}
        self.current_page = "home"
        self.geometry_ready = False
        self.wardrobe = wardrobe if wardrobe is not None else Wardrobe()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(50)
        self.preview_timer.timeout.connect(self._advance_preview)
        self.setWindowTitle("Orbit · 小新桌面助手")
        self.setWindowIcon(QIcon(str(ASSETS / "orbit.ico")))
        self.setStyleSheet(STYLE)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        shell = QWidget()
        shell.setObjectName("Page")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.setCentralWidget(shell)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(self.sidebar)
        side_layout.setContentsMargins(20, 30, 20, 20)
        side_layout.setSpacing(9)
        brand = QHBoxLayout()
        app_image = QPixmap()
        app_image.loadFromData((ASSETS / "orbit.png").read_bytes())
        brand_icon = QLabel()
        brand_icon.setPixmap(app_image.scaled(43, 43, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(brand_icon)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        brand_text.addWidget(label("Orbit", "Brand"))
        brand_text.addWidget(label("小新桌面助手", "Muted"))
        brand.addLayout(brand_text)
        brand.addStretch()
        side_layout.addLayout(brand)
        side_layout.addSpacing(32)
        side_layout.addWidget(label("你的陪伴空间", "Muted"))
        side_layout.addSpacing(4)
        self.nav_buttons = {}
        self.stack = QStackedWidget()
        self.pages = {}
        for name, title in (("home", "首页"), ("chat", "AI 聊天"), ("tasks", "Codex 任务"), ("usage", "Token 用量"), ("pet", "宠物空间"), ("focus", "专注时间"), ("settings", "设置")):
            nav = button("  " + title, lambda checked=False, page=name: self._select_page(page))
            nav.setObjectName("Nav")
            nav.setIcon(icon(name))
            nav.setIconSize(QSize(20, 20))
            nav.setCheckable(True)
            side_layout.addWidget(nav)
            self.nav_buttons[name] = nav
        side_layout.addStretch()
        self.side_note, note_layout = card("SoftCard", 14)
        note_layout.addWidget(label("●  小新在这里", "SectionTitle"))
        note_layout.addWidget(label("陪你聊天，也陪你等代码完成。", "Muted", True))
        side_layout.addWidget(self.side_note)
        side_layout.addSpacing(4)
        self.side_footer = label("ORBIT 2.4  /  MADE FOR YOUR DAY", "Muted", True)
        side_layout.addWidget(self.side_footer)
        shell_layout.addWidget(self.sidebar)
        shell_layout.addWidget(self.stack, 1)
        self._build_home()
        self._build_inbox()
        self._build_chat()
        self._build_tasks()
        self.usage_page = UsagePage()
        self.usage_page.requested.connect(self.usage_requested.emit)
        self.usage_page.refresh_requested.connect(self.usage_refresh_requested.emit)
        self.pages['usage'] = self.stack.addWidget(self.usage_page)
        self._build_pet()
        self.show_outfit("classic")
        self._build_focus()
        self._build_settings()
        self._select_page("home")
        self.statusBar().setSizeGripEnabled(True)
        self.statusBar().showMessage("小新已准备好。任务监测正在连接本机 Codex…")
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1120, available.width() - 36), min(760, available.height() - 44))
        self.setMinimumSize(min(740, available.width() - 24), min(520, available.height() - 24))
        if settings.main_geometry:
            self.restoreGeometry(QByteArray.fromHex(settings.main_geometry.encode()))
        if not any(screen.availableGeometry().intersects(self.frameGeometry()) for screen in QApplication.screens()):
            self.move(available.center() - self.rect().center())
        self.geometry_ready = True
        self.sync_settings()

    def _page(self, name, title, subtitle, scroll=False):
        page = QWidget()
        page.setObjectName("Page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(18)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(label(title, "Title"))
        heading.addWidget(label(subtitle, "Muted", True))
        layout.addLayout(heading)
        self.pages[name] = self.stack.count()
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(page)
            self.stack.addWidget(area)
            return layout
        self.stack.addWidget(page)
        return layout

    def _build_home(self):
        layout = self._page("home", "每一天，都有小新陪你", "你的桌面小伙伴，也是一间安静的工作室。", True)
        hero, hero_layout = card("Hero", 22)
        row = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(9)
        eyebrow = label("HELLO, FRIEND", "Muted")
        words.addWidget(eyebrow)
        words.addWidget(label("一起把今天\n过得有趣一点。", "HeroTitle"))
        words.addWidget(label("和我聊聊，或者安心做事。\n我会替你留意 Codex 的任务动态。", "Muted", True))
        actions = QHBoxLayout()
        actions.addWidget(button("和小新聊聊  →", lambda: self._select_page("chat"), True))
        actions.addWidget(button("打开 Codex  ↗", lambda: self.open_codex_requested.emit("")))
        actions.addStretch()
        words.addLayout(actions)
        row.addLayout(words, 1)
        self.home_pet = QLabel()
        self.home_pet.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.home_pet)
        hero_layout.addLayout(row)
        layout.addWidget(hero)
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_values = {}
        for key, title, subtitle in (("running", "正在进行", "当前监测的 Codex 聊天"), ("completed", "本轮完成", "最近 20 个聊天中的记录"), ("focus", "今日专注", "已完成的专注分钟")):
            box, content = card(margins=16)
            content.setSpacing(4)
            content.addWidget(label(title, "Muted"))
            self.stat_values[key] = label("—" if key != "focus" else "0", "Stat")
            content.addWidget(self.stat_values[key])
            content.addWidget(label(subtitle, "Muted", True))
            stats.addWidget(box, 1)
        layout.addLayout(stats)
        self.home_monitor = label("监测范围：本机最近 20 个未归档主聊天", "Muted", True)
        layout.addWidget(self.home_monitor)
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        activity_box, activity_layout = card()
        activity_tools = QHBoxLayout()
        activity_tools.addWidget(label("最近动态", "SectionTitle"))
        activity_tools.addStretch()
        self.inbox_entry = button("任务提醒", lambda: self._select_page("inbox"))
        activity_tools.addWidget(self.inbox_entry)
        activity_layout.addLayout(activity_tools)
        self.home_activity = QVBoxLayout()
        self.home_activity.setSpacing(12)
        self.home_activity.addWidget(label("这里会记录任务进展与专注时刻。", "Muted", True))
        activity_layout.addLayout(self.home_activity)
        activity_layout.addStretch()
        bottom.addWidget(activity_box, 3)
        quick_box, quick_layout = card("SoftCard", 18)
        quick_layout.setSpacing(8)
        quick_layout.addWidget(label("给自己一点专注时间", "SectionTitle", True))
        self.home_timer = label("25:00", "Stat")
        quick_layout.addWidget(self.home_timer)
        quick_layout.addWidget(label("一次只做一件事，小新陪你。", "Muted", True))
        quick_layout.addWidget(button("进入专注  →", lambda: self._select_page("focus"), True))
        quick_layout.addWidget(button("找回桌面上的小新", self.pet_restore_requested.emit))
        bottom.addWidget(quick_box, 2)
        layout.addLayout(bottom)
        layout.addStretch()

    def _build_inbox(self):
        layout = self._page("inbox", "任务提醒", "查看 Codex 任务的完成、失败和中断记录。")
        tools = QHBoxLayout()
        tools.addWidget(button("返回首页", lambda: self._select_page("home")))
        self.inbox_unread = QCheckBox("仅看未读")
        self.inbox_unread.setChecked(True)
        self.inbox_unread.toggled.connect(self.inbox_requested.emit)
        tools.addWidget(self.inbox_unread)
        tools.addStretch()
        self.read_all = button("全部标为已读", self.mark_all_read_requested.emit)
        tools.addWidget(self.read_all)
        layout.addLayout(tools)
        self.inbox_list = QListWidget()
        self.inbox_list.setAccessibleName("任务提醒列表")
        self.inbox_list.setWordWrap(True)
        self.inbox_list.itemActivated.connect(self._open_inbox_item)
        layout.addWidget(self.inbox_list, 1)
        self.inbox_empty = label("暂无未读提醒。", "Muted", True)
        layout.addWidget(self.inbox_empty)
        self.inbox_open = button("打开原聊天", lambda: self._open_inbox_item(self.inbox_list.currentItem()), True)
        layout.addWidget(self.inbox_open)

    def _open_inbox_item(self, item):
        activity = item.data(Qt.ItemDataRole.UserRole)
        self.notice_open_requested.emit(activity.thread_id, activity.event_key)

    def set_inbox(self, activities):
        current = self.inbox_list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole).id if current else ""
        self.inbox_list.clear()
        for index, activity in enumerate(activities):
            status = "未读" if activity.unread else "已读"
            stamp = activity.created_at[:16].replace("T", " ")
            item = QListWidgetItem(f"{status}  ·  {stamp}\n{activity.text}")
            item.setData(Qt.ItemDataRole.UserRole, activity)
            self.inbox_list.addItem(item)
            if not index or activity.id == selected:
                self.inbox_list.setCurrentItem(item)
        self.inbox_open.setEnabled(bool(activities))
        self.inbox_empty.setVisible(not activities)
        self.inbox_empty.setText("暂无未读提醒。" if self.inbox_unread.isChecked() else "暂无任务提醒。")

    def _build_chat(self):
        layout = self._page("chat", "和小新聊一聊", "想法、灵感，或者今天的小心事，都可以放在这里。")
        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        left, left_layout = card(margins=12)
        left.setMinimumWidth(150)
        left_layout.addWidget(button("＋  新对话", self.new_chat_requested.emit, True))
        self.conversation_list = QListWidget()
        self.conversation_list.setWordWrap(True)
        self.conversation_list.currentItemChanged.connect(self._conversation_selected)
        left_layout.addWidget(self.conversation_list, 1)
        chat_tools = QHBoxLayout()
        self.rename_button = button("重命名", self._rename_chat)
        self.delete_button = button("删除", self._delete_chat)
        self.rename_button.setObjectName("Quiet")
        self.delete_button.setObjectName("Quiet")
        chat_tools.addWidget(self.rename_button)
        chat_tools.addWidget(self.delete_button)
        left_layout.addLayout(chat_tools)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(12)
        self.chat_title = label("新的故事，从这里开始", "SectionTitle")
        right_layout.addWidget(self.chat_title)
        self.message_scroll = QScrollArea()
        self.message_scroll.setWidgetResizable(True)
        self.message_host = QWidget()
        self.message_host.setObjectName("MessageHost")
        self.message_host.setStyleSheet("#MessageHost { background: transparent; }")
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(0, 0, 8, 0)
        self.message_layout.setSpacing(12)
        self.message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.message_scroll.setWidget(self.message_host)
        right_layout.addWidget(self.message_scroll, 1)
        compose, compose_layout = card(margins=12)
        self.chat_input = ChatEditor()
        self.chat_input.submitted.connect(self._send)
        compose_layout.addWidget(self.chat_input)
        compose_footer = QHBoxLayout()
        self.include_tasks = QCheckBox("结合当前任务状态")
        self.include_tasks.setToolTip("选中后，发送当前任务的标题、状态与时间；不会读取 Codex 聊天正文。")
        compose_footer.addWidget(self.include_tasks)
        compose_footer.addStretch()
        self.send_button = button("发送  ↑", self._send, True)
        compose_footer.addWidget(self.send_button)
        compose_layout.addLayout(compose_footer)
        right_layout.addWidget(compose)
        self.chat_hint = label("Enter 发送 · Shift+Enter 换行 · 会话仅保存在本机", "Muted", True)
        right_layout.addWidget(self.chat_hint)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 620])
        layout.addWidget(splitter, 1)
        self.set_messages([])

    def _build_tasks(self):
        layout = self._page("tasks", "Codex 任务", "把进展放在眼前，安心做自己的事。")
        toolbar = QHBoxLayout()
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText("搜索任务标题…")
        self.task_search.textChanged.connect(self._filter_tasks)
        toolbar.addWidget(self.task_search, 1)
        self.task_filter = QComboBox()
        for key, title in (("", "全部状态"), ("running", "执行中"), ("completed", "本轮完成"), ("failed", "失败"), ("interrupted", "已中断"), ("unknown", "状态未确认")):
            self.task_filter.addItem(title, key)
        self.task_filter.currentIndexChanged.connect(self._filter_tasks)
        toolbar.addWidget(self.task_filter)
        toolbar.addWidget(button("打开 Codex  ↗", lambda: self.open_codex_requested.emit(""), True))
        layout.addLayout(toolbar)
        self.task_status = label("正在读取本机任务…", "Muted", True)
        layout.addWidget(self.task_status)
        task_box, task_layout = card(margins=12)
        self.task_list = QListWidget()
        self.task_list.setWordWrap(True)
        self.task_list.currentRowChanged.connect(self._task_selected)
        self.task_list.itemDoubleClicked.connect(lambda item: self.open_codex_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        task_layout.addWidget(self.task_list, 1)
        self.task_empty = label("还没有任务记录\n在 Codex 中开始一次对话吧。", "Empty", True)
        self.task_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        task_layout.addWidget(self.task_empty)
        layout.addWidget(task_box, 1)
        details, detail_layout = card("SoftCard", 18)
        self.task_detail_title = label("选中任务查看详情", "SectionTitle", True)
        self.task_detail_text = label("这里显示最新一轮的真实记录。本轮完成不代表整个项目已经完成。", "Muted", True)
        detail_layout.addWidget(self.task_detail_title)
        detail_layout.addWidget(self.task_detail_text)
        detail_actions = QHBoxLayout()
        detail_actions.addStretch()
        self.task_open = button("打开原聊天  ↗", self._open_selected_task)
        self.task_open.setEnabled(False)
        detail_actions.addWidget(self.task_open)
        detail_layout.addLayout(detail_actions)
        layout.addWidget(details)

    def _build_pet(self):
        layout = self._page("pet", "小新的陪伴空间", "选一套造型，点播小新的拿手动作。", True)
        closet, closet_layout = card(margins=16)
        closet_layout.addWidget(label("小新的衣橱", "SectionTitle"))
        self.outfit_grid = QGridLayout()
        self.outfit_grid.setSpacing(8)
        self.outfit_buttons = {}
        for key, title in OUTFITS.items():
            tile = QToolButton()
            tile.setText(title)
            tile.setAccessibleName(title)
            tile.setAccessibleIdentifier(f"outfit-{key}")
            tile.setCheckable(True)
            tile.setAutoExclusive(True)
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setIcon(QIcon(self.wardrobe.idle(key)))
            tile.setIconSize(QSize(64, 64))
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setStyleSheet(
                "QToolButton {background: #F7FAF6; border: 1px solid #DCE5DD; border-radius: 12px; padding: 5px;}"
                "QToolButton:hover {background: #EFF7F0; border-color: #A6D4BC;}"
                "QToolButton:checked {background: #E2F3E8; color: #216749; border: 2px solid #71B797;}"
            )
            tile.clicked.connect(lambda checked=False, value=key: self.outfit_requested.emit(value))
            self.outfit_buttons[key] = tile
            self.outfit_grid.addWidget(tile, 0, len(self.outfit_buttons) - 1)
        self.outfit_columns = len(self.outfit_buttons)
        closet_layout.addLayout(self.outfit_grid)
        layout.addWidget(closet)
        display, display_layout = card("Hero", 18)
        self.pet_stage = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.pet_stage.setSpacing(16)
        portrait = QVBoxLayout()
        self.pet_preview = QLabel()
        self.pet_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pet_preview.setFixedSize(174, 174)
        portrait.addWidget(self.pet_preview, 0, Qt.AlignmentFlag.AlignHCenter)
        self.preview_caption = label("", "SectionTitle")
        self.preview_caption.setAccessibleIdentifier("wardrobe-caption")
        self.preview_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        portrait.addWidget(self.preview_caption)
        self.pet_stage.addLayout(portrait)
        show = QVBoxLayout()
        show.addWidget(label("动作放映室", "SectionTitle"))
        self.classic_hint = label("选一套新造型，就能点播它的专属动作。", "Muted", True)
        show.addWidget(self.classic_hint)
        self.action_grid = QGridLayout()
        self.action_grid.setSpacing(8)
        show.addLayout(self.action_grid)
        show.addStretch()
        self.pet_stage.addLayout(show, 1)
        display_layout.addLayout(self.pet_stage)
        layout.addWidget(display)
        preferences, pref_layout = card()
        pref_layout.addWidget(label("桌面上的小新", "SectionTitle"))
        actions = QHBoxLayout()
        actions.addWidget(button("摸摸小新", lambda: self.pet_interact_requested.emit("pat")))
        actions.addWidget(button("喂一份小零食", lambda: self.pet_interact_requested.emit("feed")))
        actions.addStretch()
        pref_layout.addLayout(actions)
        toggles = QHBoxLayout()
        self.pet_visible = QCheckBox("显示桌面宠物")
        self.pet_visible.toggled.connect(self.pet_visibility_requested.emit)
        toggles.addWidget(self.pet_visible)
        self.pet_topmost = QCheckBox("让宠物保持置顶")
        self.pet_topmost.toggled.connect(self.pet_topmost_requested.emit)
        toggles.addWidget(self.pet_topmost)
        toggles.addStretch()
        pref_layout.addLayout(toggles)
        size_row = QHBoxLayout()
        size_row.addWidget(label("宠物大小", "Muted"))
        self.pet_size = QSlider(Qt.Orientation.Horizontal)
        self.pet_size.setRange(120, 320)
        self.pet_size.setSingleStep(20)
        self.pet_size.setPageStep(20)
        self.pet_size.valueChanged.connect(self._pet_size_changed)
        size_row.addWidget(self.pet_size, 1)
        self.pet_size_value = label("200 px", "Muted")
        size_row.addWidget(self.pet_size_value)
        pref_layout.addLayout(size_row)
        pref_layout.addWidget(button("找回宠物 · 回到主屏右下角", self.pet_restore_requested.emit))
        pref_layout.addWidget(label("单击回应 · 双击打开助手 · 拖动换位置 · 右键更多操作", "Muted", True))
        layout.addWidget(preferences)
        layout.addStretch()

    def show_outfit(self, key):
        self.outfit = key
        self.outfit_buttons[key].setChecked(True)
        self._stop_preview()
        self.home_pet.setPixmap(self.wardrobe.idle(key).scaled(185, 185, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        clear_layout(self.action_grid)
        self.classic_hint.setVisible(not ACTIONS[key])
        for index, (action, title) in enumerate(ACTIONS[key].items()):
            play = button(title, lambda checked=False, value=action: self.wardrobe_action_requested.emit(value))
            play.setAccessibleIdentifier(f"action-{action}")
            self.action_grid.addWidget(play, index // 3, index % 3)

    def preview_action(self, action):
        if self.current_page != "pet" or not self.isVisible() or self.isMinimized():
            return
        self.preview_action_id = action
        self.preview_started = monotonic()
        self.preview_caption.setText(ACTIONS[self.outfit][action])
        self._advance_preview()
        self.preview_timer.start()

    def _advance_preview(self):
        elapsed = monotonic() - self.preview_started
        if elapsed >= self.wardrobe.duration(self.outfit, self.preview_action_id):
            self._stop_preview()
            return
        self._set_preview_image(self.wardrobe.frame(self.outfit, self.preview_action_id, elapsed))

    def _stop_preview(self):
        self.preview_timer.stop()
        self.preview_caption.setText(OUTFITS[self.outfit])
        self._set_preview_image(self.wardrobe.idle(self.outfit))

    def _set_preview_image(self, image: QPixmap):
        self.pet_preview.setPixmap(image.scaled(self.pet_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _build_focus(self):
        layout = self._page("focus", "留一段时间，认真做一件事", "放慢一点也没关系。每一次专注，都值得被记录。", True)
        timer_box, timer_layout = card()
        modes = QHBoxLayout()
        modes.addStretch()
        self.focus_phase_buttons = {}
        for phase, text in (("focus", "专注"), ("break", "休息")):
            phase_button = button(text, lambda checked=False, value=phase: self.focus_action_requested.emit(value))
            phase_button.setObjectName("Phase")
            phase_button.setCheckable(True)
            modes.addWidget(phase_button)
            self.focus_phase_buttons[phase] = phase_button
        modes.addStretch()
        timer_layout.addLayout(modes)
        self.focus_dial = FocusDial()
        timer_layout.addWidget(self.focus_dial)
        controls = QHBoxLayout()
        controls.addStretch()
        self.focus_start = button("开始专注", lambda: self.focus_action_requested.emit("start"), True)
        self.focus_pause = button("暂停", lambda: self.focus_action_requested.emit("pause"))
        self.focus_reset = button("结束本次", lambda: self.focus_action_requested.emit("reset"))
        controls.addWidget(self.focus_start)
        controls.addWidget(self.focus_pause)
        controls.addWidget(self.focus_reset)
        controls.addStretch()
        timer_layout.addLayout(controls)
        timer_layout.addWidget(label("关闭主窗口后仍会计时；退出程序或电脑休眠时暂停。", "Muted", True))
        layout.addWidget(timer_box)
        duration_box, duration_layout = card(margins=18)
        duration_row = QHBoxLayout()
        duration_row.addWidget(label("专注", "Muted"))
        self.focus_duration = QSpinBox()
        self.focus_duration.setRange(1, 180)
        self.focus_duration.setValue(self.settings.focus_minutes)
        self.focus_duration.setSuffix(" 分钟")
        duration_row.addWidget(self.focus_duration)
        duration_row.addSpacing(14)
        duration_row.addWidget(label("休息", "Muted"))
        self.break_duration = QSpinBox()
        self.break_duration.setRange(1, 60)
        self.break_duration.setValue(self.settings.break_minutes)
        self.break_duration.setSuffix(" 分钟")
        duration_row.addWidget(self.break_duration)
        duration_row.addStretch()
        self.duration_apply = button("保存时长", lambda: self.focus_config_requested.emit(self.focus_duration.value(), self.break_duration.value()))
        duration_row.addWidget(self.duration_apply)
        duration_layout.addLayout(duration_row)
        self.focus_stats = label("今日完成 0 次专注 · 累计 0 分钟", "SectionTitle")
        duration_layout.addWidget(self.focus_stats)
        duration_layout.addWidget(label("专注与休息都由你手动开始，只统计已完成的专注。", "Muted", True))
        layout.addWidget(duration_box)
        layout.addStretch()

    def _build_settings(self):
        layout = self._page("settings", "让 Orbit 更懂你的习惯", "连接 AI，安排陪伴方式。所有偏好都在这里。", True)
        ai_box, ai_layout = card()
        ai_heading = QHBoxLayout()
        ai_heading.addWidget(label("AI 连接", "SectionTitle"))
        ai_heading.addStretch()
        self.ai_status = label("尚未配置", "Chip")
        ai_heading.addWidget(self.ai_status)
        ai_layout.addLayout(ai_heading)
        ai_layout.addWidget(label("OpenAI API Key", "Muted"))
        key_row = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("填写 API Key，仅本次运行使用")
        self.api_key.setText(self.settings.api_key)
        key_row.addWidget(self.api_key, 1)
        self.key_reveal = button("显示", self._toggle_key)
        key_row.addWidget(self.key_reveal)
        ai_layout.addLayout(key_row)
        ai_layout.addWidget(label("模型名称", "Muted"))
        self.model_name = QLineEdit()
        self.model_name.setPlaceholderText("填写你的账户可用模型")
        self.model_name.setText(self.settings.model)
        ai_layout.addWidget(self.model_name)
        ai_layout.addWidget(label("也可通过 OPENAI_API_KEY / OPENAI_MODEL 环境变量配置。API Key 不写入本地文件。", "Muted", True))
        layout.addWidget(ai_box)
        preferences, pref_layout = card()
        pref_layout.addWidget(label("陪伴偏好", "SectionTitle"))
        self.quiet = QCheckBox("免打扰 · 保留动态记录，关闭任务与计时弹出提示")
        self.quiet.setChecked(self.settings.quiet)
        pref_layout.addWidget(self.quiet)
        self.startup_pet = QCheckBox("显示桌面宠物，下次启动也保持此选择")
        self.startup_pet.setChecked(self.settings.pet_visible)
        pref_layout.addWidget(self.startup_pet)
        self.autostart = QCheckBox("登录 Windows 时自动启动 Orbit")
        pref_layout.addWidget(self.autostart)
        pref_layout.addWidget(button("保存设置", lambda: self.settings_save_requested.emit(
            self.api_key.text().strip(), self.model_name.text().strip(), self.quiet.isChecked(),
            self.startup_pet.isChecked(), self.autostart.isChecked()), True))
        layout.addWidget(preferences)
        shortcut_box, shortcut_layout = card()
        shortcut_layout.addWidget(label("找回小新的全局快捷键", "SectionTitle"))
        shortcut_layout.addWidget(label("点击输入框并按下组合键。清空后点击应用即可关闭快捷键。", "Muted", True))
        shortcut_row = QHBoxLayout()
        self.restore_shortcut_edit = QKeySequenceEdit()
        self.restore_shortcut_edit.setAccessibleName("找回小新的全局快捷键")
        self.restore_shortcut_edit.setMaximumSequenceLength(1)
        self.restore_shortcut_edit.setClearButtonEnabled(True)
        shortcut_row.addWidget(self.restore_shortcut_edit, 1)
        shortcut_row.addWidget(button("应用快捷键", lambda: self.restore_shortcut_requested.emit(
            self.restore_shortcut_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))))
        shortcut_layout.addLayout(shortcut_row)
        self.shortcut_status = label("", "Muted", True)
        shortcut_layout.addWidget(self.shortcut_status)
        self.set_restore_shortcut(self.settings.restore_shortcut)
        layout.addWidget(shortcut_box)
        about, about_layout = card("SoftCard", 18)
        about_layout.addWidget(label("Orbit 2.4 · 小新桌面助手", "SectionTitle"))
        about_layout.addWidget(label("历史会话、专注记录和偏好保存在本机。", "Muted", True))
        path_label = label(str(self.data_dir), "Muted", True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        about_layout.addWidget(path_label)
        about_actions = QHBoxLayout()
        about_actions.addWidget(button("打开数据目录", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_dir)))))
        about_actions.addStretch()
        quit_button = button("退出 Orbit", self.quit_requested.emit)
        quit_button.setObjectName("Danger")
        about_actions.addWidget(quit_button)
        about_layout.addLayout(about_actions)
        layout.addWidget(about)
        self.update_box = UpdateBox(self.data_dir)
        layout.addWidget(self.update_box)
        layout.addStretch()

    def _select_page(self, name):
        if self.preview_timer.isActive() and name != "pet":
            self._stop_preview()
        self.current_page = name
        self.stack.setCurrentIndex(self.pages[name])
        for page, nav in self.nav_buttons.items():
            nav.setChecked(page == ("home" if name == "inbox" else name))
        if name == "inbox":
            with QSignalBlocker(self.inbox_unread):
                self.inbox_unread.setChecked(True)
            self.inbox_requested.emit(True)
        if name == 'usage':
            self.usage_requested.emit(*self.usage_page.current_query())
        if name == 'settings':
            self.autostart_refresh_requested.emit()

    def set_usage(self, report):
        self.usage_page.set_report(report)

    def set_restore_shortcut(self, sequence: str, message=""):
        self.restore_shortcut_edit.setKeySequence(QKeySequence.fromString(sequence, QKeySequence.SequenceFormat.PortableText))
        self.shortcut_status.setText(message or (f"当前快捷键：{sequence}" if sequence else "快捷键已关闭"))

    def set_usage_status(self, text):
        self.usage_page.set_status(text)

    def show_page(self, name):
        self._select_page(name)
        self.activate()

    def activate(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        if self.settings.main_maximized and not self.isVisible():
            self.showMaximized()
        self.show()
        self.raise_()
        self.activateWindow()

    def _send(self):
        if self.busy or not self.chat_input.toPlainText().strip():
            return
        self.send_requested.emit(self.chat_input.toPlainText().strip(), self.include_tasks.isChecked())

    def _conversation_selected(self, current, previous):
        if current:
            self.scroll_positions[self.selected_id] = self.message_scroll.verticalScrollBar().value()
            self.select_chat_requested.emit(current.data(Qt.ItemDataRole.UserRole))

    def _rename_chat(self):
        if not self.selected_id:
            return
        title, accepted = QInputDialog.getText(self, "重命名对话", "对话名称", text=self.conversation_titles[self.selected_id])
        if accepted and title.strip():
            self.rename_chat_requested.emit(self.selected_id, title.strip())

    def _delete_chat(self):
        if not self.selected_id:
            return
        if QMessageBox.question(self, "删除对话", "删除这段对话及其本地消息？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.delete_chat_requested.emit(self.selected_id)

    def set_conversations(self, conversations, selected_id):
        changed = self.selected_id != selected_id
        self.selected_id = selected_id
        self.conversation_titles = {item.id: item.title for item in conversations}
        with QSignalBlocker(self.conversation_list):
            self.conversation_list.clear()
            for conversation in conversations:
                item = QListWidgetItem(conversation.title)
                item.setToolTip(conversation.title + "\n" + conversation.updated_at)
                item.setData(Qt.ItemDataRole.UserRole, conversation.id)
                self.conversation_list.addItem(item)
                if conversation.id == selected_id:
                    self.conversation_list.setCurrentItem(item)
        self.chat_title.setText(self.conversation_titles.get(selected_id, "新的故事，从这里开始"))
        self.rename_button.setEnabled(bool(selected_id))
        self.delete_button.setEnabled(bool(selected_id) and not self.busy)
        if changed:
            clear_layout(self.message_layout)
            self.message_cards.clear()

    def set_messages(self, messages):
        scrollbar = self.message_scroll.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 30
        position = self.scroll_positions.get(self.selected_id) if self.message_conversation != self.selected_id else (None if at_bottom else scrollbar.value())
        self.message_conversation = self.selected_id
        ids = [message.id for message in messages]
        fresh = list(self.message_cards) != ids
        if fresh or not messages:
            clear_layout(self.message_layout)
            self.message_cards.clear()
            for message in messages:
                message_card = MessageCard(message)
                self.message_cards[message.id] = message_card
                self.message_layout.addWidget(message_card)
            if not messages:
                empty = label("嗨，我是小新。\n\n想聊什么都可以，从一句“你好”开始吧。\n首次聊天，请先在设置中连接 AI。", "Empty", True)
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.message_layout.addWidget(empty)
        if not fresh:
            for message in messages:
                self.message_cards[message.id].update_message(message.content, message.status)
        conversation_id = self.selected_id
        QTimer.singleShot(0, lambda: self._scroll_to(conversation_id, position))

    def _scroll_to(self, conversation_id, position):
        if conversation_id != self.selected_id:
            return
        scrollbar = self.message_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() if position is None else position)

    def append_reply(self, message_id, text):
        if message_id not in self.message_cards:
            return
        scrollbar = self.message_scroll.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 30
        message = self.message_cards[message_id]
        message.update_message(message.content + text, "streaming")
        if at_bottom:
            conversation_id = self.selected_id
            QTimer.singleShot(0, lambda: self._scroll_to(conversation_id, None))

    def set_busy(self, busy):
        self.busy = busy
        self.chat_input.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.send_button.setText("回复中…" if busy else "发送  ↑")
        self.delete_button.setEnabled(bool(self.selected_id) and not busy)
        if busy:
            self.chat_input.clear()
        self.chat_hint.setText("小新正在回复。你可以切换页面，回复会保存在原对话。" if busy else "Enter 发送 · Shift+Enter 换行 · 会话仅保存在本机")

    def set_tasks(self, tasks, status):
        self.tasks = tasks
        self.task_status.setText(status)
        self.statusBar().showMessage("Codex · " + status)
        self.home_monitor.setText("监测范围：最近 20 个未归档主聊天 · " + ("未连接" if status.startswith(("未连接", "读取任务失败")) else f"当前读取 {len(tasks)} 个"))
        self.stat_values["running"].setText(str(sum(task.state == "running" for task in tasks)))
        self.stat_values["completed"].setText(str(sum(task.state == "completed" for task in tasks)))
        self._filter_tasks()

    def _filter_tasks(self):
        selected = self.task_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.task_list.currentItem() else ""
        with QSignalBlocker(self.task_list):
            self.task_list.clear()
            for task in self.tasks:
                if self.task_search.text().casefold() not in task.title.casefold() or (self.task_filter.currentData() and task.state != self.task_filter.currentData()):
                    continue
                item = QListWidgetItem(f"{task.title}\n{STATE_LABELS[task.state]}   ·   {task.updated_at}")
                item.setData(Qt.ItemDataRole.UserRole, task.id)
                item.setToolTip(task.detail)
                self.task_list.addItem(item)
                if task.id == selected:
                    self.task_list.setCurrentItem(item)
            if self.task_list.count() and self.task_list.currentRow() < 0:
                self.task_list.setCurrentRow(0)
        self.task_empty.setVisible(self.task_list.count() == 0)
        self.task_empty.setText("没有匹配的任务\n试试其他关键词或状态。" if self.tasks else "还没有任务记录\n在 Codex 中开始一次对话吧。")
        self._task_selected()

    def _task_selected(self):
        current = self.task_list.currentItem()
        self.task_open.setEnabled(current is not None)
        if current is None:
            self.task_detail_title.setText("选中任务查看详情")
            self.task_detail_text.setText("这里显示最新一轮的真实记录。本轮完成不代表整个项目已经完成。")
            return
        task = next(task for task in self.tasks if task.id == current.data(Qt.ItemDataRole.UserRole))
        self.task_detail_title.setText(task.title)
        self.task_detail_text.setText(f"{STATE_LABELS[task.state]} · {task.updated_at}\n{task.detail}")

    def _open_selected_task(self):
        self.open_codex_requested.emit(self.task_list.currentItem().data(Qt.ItemDataRole.UserRole))

    def set_activity(self, activities, unread_count=0):
        self.inbox_entry.setText(f"任务提醒 · {unread_count} 未读" if unread_count else "任务提醒")
        self.read_all.setEnabled(unread_count > 0)
        clear_layout(self.home_activity)
        if not activities:
            self.home_activity.addWidget(label("这里会记录任务进展与专注时刻。", "Muted", True))
            return
        for activity in activities[:5]:
            if activity.thread_id:
                title = ("未读 · " if activity.unread else "") + activity.text
                entry = button(title.replace("&", "&&"), lambda checked=False, a=activity:
                               self.notice_open_requested.emit(a.thread_id, a.event_key))
                entry.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                entry.setToolTip(activity.text + "\n" + activity.created_at)
                self.home_activity.addWidget(entry)
                continue
            entry = label("●  " + activity.text, wrap=True)
            entry.setToolTip(activity.created_at)
            self.home_activity.addWidget(entry)

    def _pet_size_changed(self, value):
        self.pet_size_value.setText(f"{value} px")
        self.pet_size_requested.emit(value)

    def set_focus(self, phase, state, remaining, stats):
        seconds = max(0, math.ceil(remaining))
        self.home_timer.setText(f"{seconds // 60:02}:{seconds % 60:02}")
        self.stat_values["focus"].setText(str(stats[1] // 60))
        self.focus_stats.setText(f"今日完成 {stats[0]} 次专注 · 累计 {stats[1] // 60} 分钟")
        self.focus_dial.remaining = remaining
        self.focus_dial.total = (self.settings.focus_minutes if phase == "focus" else self.settings.break_minutes) * 60
        self.focus_dial.caption = {"idle": "准备好，随时可以开始", "running": "小新陪你" + ("专注中" if phase == "focus" else "休息中"), "paused": "已暂停，慢慢来"}[state]
        if state == "idle" and remaining == 0:
            self.focus_dial.caption = "完成啦，给自己一个微笑"
        self.focus_dial.update()
        self.focus_start.setText("继续" if state == "paused" else ("开始专注" if phase == "focus" else "开始休息"))
        self.focus_start.setEnabled(state != "running")
        self.focus_pause.setEnabled(state == "running")
        self.focus_reset.setEnabled(state != "idle")
        for key, phase_button in self.focus_phase_buttons.items():
            phase_button.setChecked(key == phase)
            phase_button.setEnabled(state == "idle")
        for control in (self.focus_duration, self.break_duration, self.duration_apply):
            control.setEnabled(state == "idle")

    def sync_settings(self):
        for control, value in ((self.pet_visible, self.settings.pet_visible), (self.pet_topmost, self.settings.topmost)):
            with QSignalBlocker(control):
                control.setChecked(value)
        with QSignalBlocker(self.pet_size):
            self.pet_size.setValue(self.settings.pet_size)
        self.pet_size_value.setText(f"{self.settings.pet_size} px")
        values = (self.settings.api_key, self.settings.model, self.settings.focus_minutes,
                  self.settings.break_minutes, self.settings.quiet, self.settings.pet_visible)
        if values[0] != self.form_snapshot[0]:
            self.api_key.setText(self.settings.api_key)
        if values[1] != self.form_snapshot[1]:
            self.model_name.setText(self.settings.model)
        if values[2] != self.form_snapshot[2]:
            self.focus_duration.setValue(self.settings.focus_minutes)
        if values[3] != self.form_snapshot[3]:
            self.break_duration.setValue(self.settings.break_minutes)
        if values[4] != self.form_snapshot[4]:
            self.quiet.setChecked(self.settings.quiet)
        if values[5] != self.form_snapshot[5]:
            self.startup_pet.setChecked(self.settings.pet_visible)
        self.form_snapshot = values
        self.ai_status.setText("已填写 · 待请求验证" if self.settings.api_key and self.settings.model else "尚未配置")

    def _toggle_key(self):
        reveal = self.api_key.echoMode() == QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if reveal else QLineEdit.EchoMode.Password)
        self.key_reveal.setText("隐藏" if reveal else "显示")

    def show_error(self, text):
        QMessageBox.warning(self, "Orbit 提示", text)

    def show_notice(self, text):
        self.statusBar().showMessage(text, 8000)

    def remember_geometry(self):
        if not self.geometry_ready or self.isMinimized():
            return
        self.settings.main_geometry = bytes(self.saveGeometry().toHex()).decode()
        self.settings.main_maximized = self.isMaximized()

    def closeEvent(self, event):
        self.remember_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event):
        if self.preview_timer.isActive():
            self._stop_preview()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sidebar.setFixedWidth(175 if self.width() < 950 else 210)
        for nav in self.nav_buttons.values():
            nav.setStyleSheet("padding: 6px 12px;" if self.height() < 680 else "")
        self.side_note.setVisible(self.height() >= 740)
        self.side_footer.setVisible(self.height() >= 680)
        self.home_pet.setVisible(self.width() >= 850)
        compact = self.width() < 960
        self.pet_stage.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        columns = 2 if self.width() < 780 else len(self.outfit_buttons)
        if columns != self.outfit_columns:
            self.outfit_columns = columns
            for index, tile in enumerate(self.outfit_buttons.values()):
                self.outfit_grid.addWidget(tile, index // columns, index % columns)
        self.remember_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.remember_geometry()
