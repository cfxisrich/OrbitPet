from math import pi, sin
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap


OUTFITS = {
    "classic": "经典红衣", "school": "幼稚园小新", "hero": "动感超人小新", "pajama": "睡衣小新",
    "bike": "骑车小新",
}
ACTIONS = {
    "classic": {},
    "school": {"wave": "帽子挥挥", "salute": "防卫队敬礼", "wiggle": "扭屁股舞"},
    "hero": {"leap": "超人登场", "beam": "动感光波", "kick": "正义飞踢"},
    "pajama": {"nap": "抱枕打瞌睡", "brush": "刷牙扭扭舞", "roll": "抱枕翻滚"},
    "bike": {"pedal": "踩踏出发"},
}

# Cell numbers follow the artwork. Repeated cells hold the drawn pose for a beat.
TIMELINES = {
    "wave": (2.15, (0, 1, 2, 1, 2, 1, 2, 1, 0)),
    "salute": (1.9, (0, 3, 4, 5, 5, 5, 4, 3, 0)),
    "wiggle": (2.65, (0, 6, 7, 8, 7, 6, 7, 8, 7, 6, 0)),
    "leap": (1.85, (0, 1, 1, 2, 2, 2, 1, 0)),
    "beam": (2.25, (0, 3, 4, 4, 5, 5, 5, 4, 3, 0)),
    "kick": (1.75, (0, 6, 7, 8, 8, 8, 7, 6, 0)),
    "nap": (3.4, (0, 1, 2, 2, 2, 2, 2, 1, 0)),
    "brush": (2.5, (0, 3, 4, 5, 4, 5, 4, 5, 4, 3, 0)),
    "roll": (2.4, (0, 6, 7, 8, 8, 7, 6, 0)),
    "pedal": (3.2, (0,) + (1, 2, 3, 7, 5, 6, 4, 8) * 3 + (0,)),
}

ASSETS = Path(__file__).parent / "assets"


class Wardrobe:
    def __init__(self):
        self._cells: dict[str, tuple[QPixmap, ...]] = {}

    def _load(self, outfit):
        if outfit in self._cells:
            return self._cells[outfit]
        path = ASSETS / ("shinchan.png" if outfit == "classic" else f"wardrobe/{outfit}.png")
        sheet = QPixmap(str(path))
        if sheet.isNull():
            raise ValueError(f"无法读取小新的造型素材：{path.name}")
        if outfit == "classic":
            self._cells[outfit] = (sheet.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation),)
            return self._cells[outfit]
        if sheet.width() != sheet.height() or sheet.width() % 3:
            raise ValueError(f"小新动作图需要九个等大的方格：{path.name}")
        side = sheet.width() // 3
        self._cells[outfit] = tuple(
            sheet.copy(i % 3 * side, i // 3 * side, side, side) for i in range(9)
        )
        return self._cells[outfit]

    def idle(self, outfit):
        return self._load(outfit)[0]

    def duration(self, outfit, action):
        return TIMELINES[action][0] if action in ACTIONS[outfit] else 0.0

    def frame(self, outfit, action, elapsed_seconds):
        duration = self.duration(outfit, action)
        if elapsed_seconds <= 0 or elapsed_seconds >= duration:
            return self.idle(outfit)

        progress = elapsed_seconds / duration
        poses = TIMELINES[action][1]
        cell = poses[int(progress * len(poses))]
        if not cell:
            return self.idle(outfit)

        sprite = self._load(outfit)[cell]
        if action == "pedal":
            return sprite
        frame = QPixmap(sprite.size())
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Work in a 100 × 100 square for identical motion at all asset sizes.
        painter.scale(frame.width() / 100, frame.height() / 100)
        swell = sin(pi * progress)
        swing = sin(6 * pi * progress) * swell
        x = y = angle = 0.0
        match action:
            case "wave":
                angle = 4 * swing
            case "salute":
                y = -2 * swell
            case "wiggle":
                x, angle = 4 * swing, 8 * swing
            case "leap":
                y, angle = -8 * swell ** 3, -7 * swell
            case "beam":
                x = -2 * swell
            case "kick":
                x, y, angle = 4 * swell, -4 * swell, -7 * swell
            case "nap":
                angle = 3 * swell
            case "brush":
                x, angle = 2 * swing, 5 * swing
            case "roll":
                x = -5 * sin(2 * pi * progress)
                turn = min(1, max(0, (progress - .24) / .52))
                angle = 360 * turn * turn * (3 - 2 * turn)

        painter.translate(50 + x, 52 + y)
        painter.rotate(angle)
        inset = 1 - (0.20 if action == "roll" else 0.05) * swell
        painter.scale(inset, inset)
        painter.translate(-50, -52)
        painter.drawPixmap(QRectF(0, 0, 100, 100), sprite, QRectF(sprite.rect()))
        painter.end()
        return frame
