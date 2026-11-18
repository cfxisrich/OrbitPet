import math
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QToolTip, QVBoxLayout, QWidget,
)

from usage_store import UsageReport


LOCAL_TIME = timezone(timedelta(hours=8))


class UsageChart(QWidget):
    def __init__(self):
        super().__init__()
        self.buckets = []
        self.setMinimumHeight(190)
        self.setMouseTracking(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(60, 18, max(1, self.width() - 76), self.height() - 51)
        largest = max((bucket.totals.total_tokens for bucket in self.buckets), default=0)
        ceiling = max(1, largest)
        painter.setFont(QFont('Segoe UI', 8))
        for fraction in (0, .5, 1):
            y = plot.bottom() - plot.height() * fraction
            painter.setPen(QPen(QColor('#E8EEE8'), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor('#87978C'))
            value = math.ceil(ceiling * fraction) if largest else 0
            text = f'{value / 1000000:.1f}M' if value >= 1000000 else f'{value / 1000:.1f}k' if value >= 10000 else str(value)
            painter.drawText(QRectF(0, y - 10, 49, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        if not self.buckets:
            return
        step = plot.width() / len(self.buckets)
        label_every = max(1, math.ceil(len(self.buckets) * 40 / plot.width()))
        for index, bucket in enumerate(self.buckets):
            height = plot.height() * bucket.totals.total_tokens / ceiling
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#65BE9D'))
            if height > 0:
                painter.drawRoundedRect(QRectF(plot.left() + index * step + step * .18,
                                               plot.bottom() - max(2, height), step * .64, max(2, height)), 3, 3)
            if index % label_every == 0:
                painter.setPen(QColor('#87978C'))
                painter.drawText(QRectF(plot.left() + index * step - 13, plot.bottom() + 7, step + 26, 20),
                                 Qt.AlignmentFlag.AlignCenter, bucket.label[-5:])

    def mouseMoveEvent(self, event):
        if not self.buckets or event.position().x() < 60 or event.position().x() >= self.width() - 16:
            return
        index = int((event.position().x() - 60) / max(1, self.width() - 76) * len(self.buckets))
        bucket = self.buckets[index]
        QToolTip.showText(event.globalPosition().toPoint(), f'{bucket.label}\n{bucket.totals.total_tokens:,} tokens', self)


class UsagePage(QWidget):
    requested = Signal(str, str, str)
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName('Page')
        self.columns = 4
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll)
        content = QWidget()
        content.setObjectName('Page')
        self.scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(16)
        title = QLabel('Token 用量')
        title.setObjectName('Title')
        layout.addWidget(title)
        subtitle = QLabel('看看每一天的消耗，把用量变化看清楚。')
        subtitle.setObjectName('Muted')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        filters = QFrame()
        filters.setObjectName('Card')
        filter_layout = QVBoxLayout(filters)
        filter_layout.setContentsMargins(16, 14, 16, 14)
        filter_layout.setSpacing(12)
        first_row = QHBoxLayout()
        self.period = QComboBox()
        for text, value in (('按日', 'day'), ('按周', 'week'), ('按月', 'month')):
            self.period.addItem(text, value)
        self.period.setCurrentIndex(2)
        self.source = QComboBox()
        for text, value in (('全部来源', 'all'), ('Codex', 'codex'), ('桌宠 AI 聊天', 'orbit')):
            self.source.addItem(text, value)
        first_row.addWidget(self.period)
        first_row.addWidget(self.source)
        first_row.addStretch()
        self.refresh_button = QPushButton('刷新用量')
        self.refresh_button.setObjectName('Primary')
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        first_row.addWidget(self.refresh_button)
        filter_layout.addLayout(first_row)
        second_row = QHBoxLayout()
        self.previous = QPushButton('← 上一月')
        self.previous.clicked.connect(lambda: self._step(-1))
        self.next = QPushButton('下一月 →')
        self.next.clicked.connect(lambda: self._step(1))
        self.anchor = QDateEdit()
        self.anchor.setCalendarPopup(True)
        self.anchor.setDisplayFormat('yyyy-MM-dd')
        today = datetime.now(LOCAL_TIME).date()
        self.anchor.setDate(QDate(today.year, today.month, today.day))
        self.today = QPushButton('本月')
        self.today.clicked.connect(self._today)
        second_row.addWidget(self.previous)
        second_row.addWidget(self.anchor, 1)
        second_row.addWidget(self.next)
        second_row.addWidget(self.today)
        filter_layout.addLayout(second_row)
        layout.addWidget(filters)
        self.range_label = QLabel('正在读取已记录用量…')
        self.range_label.setObjectName('Muted')
        self.range_label.setWordWrap(True)
        layout.addWidget(self.range_label)
        self.summary = QGridLayout()
        self.summary.setSpacing(12)
        self.cards = []
        self.values = {}
        for index, (key, text, note) in enumerate((
            ('total_tokens', '总 Token', '输入 + 输出'),
            ('input_tokens', '输入 Token', '含缓存命中'),
            ('output_tokens', '输出 Token', '含推理 Token'),
            ('cached_tokens', '缓存命中', '已包含在输入中'),
        )):
            box = QFrame()
            box.setObjectName('Card')
            card_layout = QVBoxLayout(box)
            card_layout.setContentsMargins(16, 15, 16, 15)
            card_layout.setSpacing(5)
            label = QLabel(text)
            label.setObjectName('Muted')
            card_layout.addWidget(label)
            value = QLabel('—')
            value.setObjectName('UsageValue')
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(value)
            footnote = QLabel(note)
            footnote.setObjectName('Muted')
            card_layout.addWidget(footnote)
            self.values[key] = value
            self.cards.append(box)
            self.summary.addWidget(box, 0, index)
        layout.addLayout(self.summary)
        trend = QFrame()
        trend.setObjectName('Card')
        trend_layout = QVBoxLayout(trend)
        trend_layout.setContentsMargins(18, 18, 18, 14)
        trend_title = QLabel('用量趋势')
        trend_title.setObjectName('SectionTitle')
        trend_layout.addWidget(trend_title)
        self.empty = QLabel('这个周期还没有已记录的用量。')
        self.empty.setObjectName('Muted')
        self.empty.setWordWrap(True)
        self.empty.hide()
        trend_layout.addWidget(self.empty)
        self.chart = UsageChart()
        trend_layout.addWidget(self.chart)
        layout.addWidget(trend)
        details = QFrame()
        details.setObjectName('Card')
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(18, 18, 18, 18)
        details_title = QLabel('用量明细')
        details_title.setObjectName('SectionTitle')
        details_layout.addWidget(details_title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(('时间', '输入', '输出', '缓存', '推理', '总量'))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(75)
        self.table.setMinimumHeight(210)
        self.table.setMaximumHeight(290)
        details_layout.addWidget(self.table)
        self.count_label = QLabel('用量以实际返回的记录为准。')
        self.count_label.setObjectName('Muted')
        self.count_label.setWordWrap(True)
        details_layout.addWidget(self.count_label)
        layout.addWidget(details)
        self.status = QLabel('正在读取本机用量记录…')
        self.status.setObjectName('Muted')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        help_text = QLabel('统计时间：北京时间（UTC+8），周一开周，按自然月汇总。\n'
                           'Codex：仅统计本机日志可还原用量，包含子代理和归档。桌宠 AI：从 2.1 版本开始记录接口返回的真实用量。\n'
                           '缓存已计入输入，推理已计入输出；未返回用量的请求不计入，历史缺失无法补算。这不是账户账单。')
        help_text.setObjectName('Muted')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addStretch()
        self.period.currentIndexChanged.connect(self._period_changed)
        self.source.currentIndexChanged.connect(self._request)
        self.anchor.dateChanged.connect(self._request)

    def current_query(self) -> tuple[str, str, str]:
        return self.period.currentData(), self.source.currentData(), self.anchor.date().toString('yyyy-MM-dd')

    def _request(self):
        self.requested.emit(*self.current_query())

    def _period_changed(self):
        unit = {'day': '日', 'week': '周', 'month': '月'}[self.period.currentData()]
        self.previous.setText('← 上一' + unit)
        self.next.setText('下一' + unit + ' →')
        self.today.setText('今' + unit if unit == '日' else '本' + unit)
        self._request()

    def _step(self, direction):
        current = self.anchor.date()
        period = self.period.currentData()
        self.anchor.setDate(current.addMonths(direction) if period == 'month' else current.addDays(direction * (7 if period == 'week' else 1)))

    def _today(self):
        today = datetime.now(LOCAL_TIME).date()
        current = QDate(today.year, today.month, today.day)
        if self.anchor.date() == current:
            self._request()
            return
        self.anchor.setDate(current)

    def set_report(self, report: UsageReport):
        for key, widget in self.values.items():
            widget.setText(f'{getattr(report.totals, key):,}')
        self.range_label.setText(f'{report.start:%Y-%m-%d} — {report.end - timedelta(days=1):%Y-%m-%d}  ·  北京时间 UTC+8')
        self.empty.setVisible(report.totals.records == 0)
        self.chart.buckets = report.buckets
        self.chart.update()
        self.table.setRowCount(len(report.buckets))
        for row, bucket in enumerate(report.buckets):
            self.table.setItem(row, 0, QTableWidgetItem(bucket.label))
            for column, key in enumerate(('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens', 'total_tokens'), 1):
                item = QTableWidgetItem(f'{getattr(bucket.totals, key):,}')
                item.setToolTip(item.text())
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, column, item)
        self.count_label.setText(f'本周期共 {report.totals.records:,} 条已记录用量 · 推理 Token {report.totals.reasoning_tokens:,}（已包含在输出中）')

    def set_status(self, text):
        self.status.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        columns = 2 if self.width() < 850 else 4
        if columns == self.columns:
            return
        self.columns = columns
        for index, box in enumerate(self.cards):
            self.summary.removeWidget(box)
            self.summary.addWidget(box, index // columns, index % columns)
