from collections.abc import Callable
from ctypes import wintypes
from time import monotonic

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer, Signal


class PowerSuspendFilter(QAbstractNativeEventFilter):
    def __init__(self, on_suspend: Callable[[], None]):
        super().__init__()
        self.on_suspend = on_suspend

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            native = wintypes.MSG.from_address(int(message))
            if native.message == 0x0218 and native.wParam == 4:
                self.on_suspend()
        return False, 0


class FocusTimer(QObject):
    changed = Signal()
    completed = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = "focus"
        self.state = "idle"
        self.focus_minutes = 25
        self.break_minutes = 5
        self.duration = 1500
        self.remaining = 1500.0
        self.last_tick = monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._tick)
        self.power_filter = PowerSuspendFilter(self.pause)
        QCoreApplication.instance().installNativeEventFilter(self.power_filter)

    def configure(self, focus_minutes: int, break_minutes: int):
        self.focus_minutes = focus_minutes
        self.break_minutes = break_minutes
        if self.state == "idle":
            self.duration = (focus_minutes if self.phase == "focus" else break_minutes) * 60
            self.remaining = float(self.duration)
        self.changed.emit()

    def start(self):
        if self.state == "running":
            return
        if self.remaining <= 0:
            self.duration = (self.focus_minutes if self.phase == "focus" else self.break_minutes) * 60
            self.remaining = float(self.duration)
        self.last_tick = monotonic()
        self.state = "running"
        self.timer.start()
        self.changed.emit()

    def pause(self):
        if self.state != "running":
            return
        self._tick()
        if self.state != "running":
            return
        self.state = "paused"
        self.timer.stop()
        self.changed.emit()

    def reset(self):
        self.timer.stop()
        self.state = "idle"
        self.duration = (self.focus_minutes if self.phase == "focus" else self.break_minutes) * 60
        self.remaining = float(self.duration)
        self.changed.emit()

    def choose_phase(self, phase: str):
        self.phase = phase
        self.reset()

    def _tick(self):
        if self.state != "running":
            return
        now = monotonic()
        elapsed = now - self.last_tick
        self.last_tick = now
        if elapsed > 5:
            self.state = "paused"
            self.timer.stop()
            self.changed.emit()
            return
        self.remaining = max(0.0, self.remaining - elapsed)
        if self.remaining > 0:
            self.changed.emit()
            return
        self.state = "idle"
        self.timer.stop()
        self.changed.emit()
        self.completed.emit(self.phase, self.duration)

    def snapshot(self) -> dict[str, str | int | float]:
        return {"phase": self.phase, "state": self.state,
                "remaining": self.remaining, "duration": self.duration}

    def restore(self, snapshot: dict[str, str | int | float]):
        if not snapshot:
            return
        if (set(snapshot) != {"phase", "state", "remaining", "duration"}
                or snapshot["phase"] not in ("focus", "break")
                or snapshot["state"] not in ("idle", "running", "paused")
                or type(snapshot["duration"]) is not int
                or type(snapshot["remaining"]) not in (int, float)
                or not 0 < snapshot["duration"] <= 10800
                or not 0 <= snapshot["remaining"] <= snapshot["duration"]):
            raise ValueError("专注记录格式不正确。")
        self.timer.stop()
        self.phase = snapshot["phase"]
        self.state = "paused" if snapshot["state"] == "running" else snapshot["state"]
        self.duration = snapshot["duration"]
        self.remaining = float(snapshot["remaining"])
        self.changed.emit()
