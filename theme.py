from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


STYLE = """QWidget { color: #25332F; font-family: 'Microsoft YaHei UI'; font-size: 13px; }
QMainWindow, QWidget#Page { background: #F6F8F5; }
QFrame#Sidebar { background: #FFFFFF; border-right: 1px solid #E6ECE6; }
QFrame#Card { background: #FFFFFF; border: 1px solid #E3EAE3; border-radius: 18px; }
QFrame#Hero { background: #E6F4EA; border: 1px solid #D5E9DC; border-radius: 22px; }
QFrame#SoftCard { background: #F0F6F0; border: none; border-radius: 14px; }
QFrame#UserMessage { background: #E7F3EC; border: 1px solid #D8E9DF; border-radius: 15px; }
QLabel { background: transparent; border: none; }
QLabel#Brand { font-size: 24px; font-weight: 700; letter-spacing: 1px; }
QLabel#Title { font-size: 26px; font-weight: 700; }
QLabel#HeroTitle { font-size: 30px; font-weight: 700; }
QLabel#SectionTitle { font-size: 16px; font-weight: 600; }
QLabel#Muted { color: #7B8B81; font-size: 12px; }
QLabel#UsageValue { font-size: 22px; font-weight: 650; }
QLabel#Stat { font-size: 30px; font-weight: 650; }
QLabel#Chip { color: #3B8B6C; background: #E6F4EA; border-radius: 10px; padding: 5px 10px; font-size: 11px; }
QLabel#Error { color: #B85F58; }
QLabel#Empty { color: #87968C; padding: 25px; }
QPushButton { background: #FFFFFF; border: 1px solid #DCE5DD; border-radius: 10px; padding: 9px 15px; font-weight: 500; }
QPushButton:hover { background: #EDF6EF; border-color: #BCD8C7; }
QPushButton:pressed { background: #DCEEE2; }
QPushButton:disabled { color: #A0ADA4; background: #F0F3EF; border-color: #E5EAE4; }
QPushButton#Primary { background: #5EBA9C; color: #FFFFFF; border-color: #5EBA9C; font-weight: 600; }
QPushButton#Primary:hover { background: #4DAA8B; border-color: #4DAA8B; }
QPushButton#Primary:disabled { background: #BEDDCF; border-color: #BEDDCF; }
QPushButton#Quiet { background: transparent; border: none; color: #6B7D71; padding: 6px 8px; }
QPushButton#Quiet:hover { background: #EDF4ED; color: #267A59; }
QPushButton#Danger { color: #B85F58; }
QPushButton#Nav { text-align: left; background: transparent; border: none; border-radius: 11px; padding: 13px 16px; color: #76877C; }
QPushButton#Nav:checked { background: #E5F3E9; color: #287D5C; font-weight: 600; }
QPushButton#Nav:hover { background: #EFF6EF; }
QPushButton#Phase { background: #F3F7F2; }
QPushButton#Phase:checked { background: #DFF0E6; border-color: #AFD6BF; color: #287D5C; }
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox { background: #FBFCFA; border: 1px solid #DCE5DD; border-radius: 10px; padding: 9px; selection-background-color: #BBDEC9; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #77B99A; }
QLineEdit:disabled, QPlainTextEdit:disabled { color: #8C9A90; background: #F4F6F2; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #E1F1E7; color: #25332F; border: 1px solid #DCE5DD; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border: none; border-radius: 10px; padding: 12px; margin: 2px 0; }
QListWidget::item:selected { color: #287D5C; background: #E4F2E8; }
QListWidget::item:hover { background: #F0F6F0; }
QTextBrowser { background: transparent; border: none; selection-background-color: #B9DEC9; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #CFDCD1; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 7px; }
QScrollBar::handle:horizontal { background: #CFDCD1; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #C8D6CA; border-radius: 5px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #5EBA9C; border-color: #5EBA9C; image: none; }
QSlider::groove:horizontal { height: 5px; background: #E0EAE1; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #81C8A5; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #5EBA9C; }
QSplitter::handle { background: transparent; width: 10px; }
QDateEdit { background: #FFFFFF; border: 1px solid #DCE5DD; border-radius: 9px; padding: 8px; }
QDateEdit::drop-down { border: none; width: 24px; }
QTableWidget { background: #FFFFFF; alternate-background-color: #F5F9F5; border: none; selection-background-color: #E1F0E6; selection-color: #25332F; }
QHeaderView::section { background: #F0F6F0; color: #61776A; border: none; padding: 9px 7px; font-weight: 500; }
QStatusBar { background: #F6F8F5; color: #7B8B81; font-size: 11px; }
QToolTip { background: #FFFFFF; border: 1px solid #DCE5DD; color: #25332F; padding: 6px; }
QMenu { background: #FFFFFF; border: 1px solid #E0EAE1; padding: 5px; }
QMenu::item { padding: 8px 24px; }
QMenu::item:selected { background: #E4F2E8; }
"""


def icon(name, color="#698B77"):
    paths = {
        "home": '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
        "chat": '<path d="M20 16a3 3 0 0 1-3 3H9l-5 3v-6a7 7 0 0 1-2-5 9 9 0 0 1 18 0z"/><path d="M7 10h10M7 14h6"/>',
        "tasks": '<rect x="4" y="4" width="16" height="18" rx="3"/><path d="M9 2h6v4H9zM8 11h1m3 0h4m-8 5h1m3 0h4"/>',
        "usage": '<path d="M4 20V10h4v10m4 0V4h4v16m4 0v-6h2v6M2 22h22"/>',
        "pet": '<path d="M12 21s-9-5.6-9-12a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6.4-9 12-9 12z"/>',
        "focus": '<circle cx="12" cy="13" r="8"/><path d="M12 9v5l3 2M9 2h6m-3 0v3m6 1 2-2"/>',
        "settings": '<path d="m10 2-1 3-3 1-3-1-1 4 3 2v3l-3 2 2 4 3-1 3 2 1 2 4-1v-3l3-2 3 1 1-4-3-2V9l2-2-2-3-3 1-3-1-1-2z"/><circle cx="12" cy="12" r="3"/>',
    }
    renderer = QSvgRenderer(QByteArray(f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</g></svg>'.encode()))
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)
