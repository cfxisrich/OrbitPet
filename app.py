import ctypes
import json
import os
import queue
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import asdict, fields
from pathlib import Path
from tkinter import messagebox
from urllib.parse import quote

from ai_client import AiError, stream_reply
from codex_monitor import CodexMonitor
from models import Settings, Task, STATE_LABELS
from tray import TrayIcon
from ui import PetUI
from windows import SingleInstance


CONFIG = Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent / "data" / "settings.json"


def load_settings():
    saved = json.loads(CONFIG.read_text("utf-8")) if CONFIG.exists() else {}
    allowed = {field.name: type(field.default) for field in fields(Settings)
               if field.name != "api_key"}
    if not isinstance(saved, dict) or any(
        key not in allowed or type(value) is not allowed[key]
        for key, value in saved.items()
    ):
        raise ValueError("设置文件格式错误，请移走 data/settings.json 后重新启动。")
    settings = Settings(**saved, api_key=os.environ.get("OPENAI_API_KEY", ""))
    settings.model = settings.model or os.environ.get("OPENAI_MODEL", "")
    if not 120 <= settings.pet_size <= 320:
        raise ValueError("宠物尺寸应在 120 到 320 之间。")
    return settings


class Companion:
    def __init__(self, root: tk.Tk, settings: Settings, instance: SingleInstance):
        self.root = root
        self.settings = settings
        self.instance = instance
        self.events: queue.Queue[Callable[[], None]] = queue.Queue()
        self.stopped = threading.Event()
        self.tasks: list[Task] = []
        self.history: list[tuple[str, str]] = []
        self.seen: set[tuple[str, str, str]] = set()
        self.initialized = False
        self.replying = False
        self.monitor_ok = False
        self.ui = PetUI(root, settings, self.send, self.open_codex, self.save, self.quit)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.tray = TrayIcon(
            lambda: self.events.put(lambda: self.ui.show_panel("chat")),
            lambda: self.events.put(self.quit),
            lambda: self.events.put(self.ui.restore_pet),
        )
        self.tray.start()
        root.after(50, self.drain_events)
        threading.Thread(target=self.watch, daemon=True, name="codex-monitor").start()

    def save(self):
        values = asdict(self.settings)
        del values["api_key"]
        try:
            CONFIG.parent.mkdir(exist_ok=True)
            temporary = CONFIG.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), "utf-8")
            temporary.replace(CONFIG)
        except OSError as error:
            messagebox.showerror("无法保存设置", str(error), parent=self.root)

    def open_codex(self, thread_id: str):
        uri = "codex://threads/" + (quote(thread_id, safe="") if thread_id else "new")
        try:
            os.startfile(uri)
        except OSError:
            messagebox.showerror("无法打开 Codex", "未找到 Codex 链接处理程序，请确认已安装 Codex 桌面应用。", parent=self.root)

    def watch(self):
        monitor = CodexMonitor(Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
        previous = ()
        while not self.stopped.is_set():
            try:
                tasks, status = monitor.poll()
                if (tasks, status) != previous:
                    self.events.put(lambda tasks=tasks, status=status: self.update_tasks(tasks, status))
                    previous = tasks, status
                self.stopped.wait(3 if any(task.state in ("running", "waiting") for task in tasks) else 8)
            except (OSError, ValueError) as error:
                previous = ()
                self.events.put(lambda text=str(error): self.monitor_error(text))
                self.stopped.wait(8)

    def monitor_error(self, text: str):
        self.monitor_ok = False
        self.tasks = []
        self.ui.set_tasks([], "读取任务失败：" + text)
        self.refresh_pet()

    def update_tasks(self, tasks: list[Task], status: str):
        self.tasks = tasks
        self.monitor_ok = not status.startswith("未连接")
        self.ui.set_tasks(tasks, status)
        terminal = [task for task in tasks if task.state in ("completed", "failed", "interrupted", "waiting")]
        new_events = [task for task in terminal if (task.id, task.turn_id, task.state) not in self.seen]
        self.seen.update((task.id, task.turn_id, task.state) for task in terminal)
        self.refresh_pet()
        if self.initialized and new_events and not self.settings.quiet:
            task = new_events[0]
            self.ui.notify(f"{task.title[:26]} · {STATE_LABELS[task.state]}", task.state)
        self.initialized = True

    def refresh_pet(self):
        if self.replying:
            self.ui.set_pet_state("thinking")
            return
        for state in ("waiting", "running"):
            if any(task.state == state for task in self.tasks):
                self.ui.set_pet_state(state)
                return
        self.ui.set_pet_state("idle" if self.monitor_ok else "offline")

    def send(self, text: str, include_tasks: bool):
        if not self.settings.api_key or not self.settings.model.strip():
            self.ui.show_panel("settings")
            self.ui.notify("先填写 API Key 和模型名称，就能聊天了。", "idle")
            return
        self.replying = True
        self.ui.start_reply(text)
        self.refresh_pet()
        task_context = json.dumps([
            {"title": task.title, "state": STATE_LABELS[task.state],
             "detail": task.detail, "updated_at": task.updated_at}
            for task in self.tasks
        ], ensure_ascii=False) if include_tasks else ""
        messages = self.history[-12:] + [("user", text)]
        threading.Thread(
            target=self.reply,
            args=(self.settings.api_key, self.settings.model.strip(), messages, task_context),
            daemon=True, name="ai-reply",
        ).start()

    def reply(self, api_key: str, model: str, messages: list[tuple[str, str]], context: str):
        pieces = []
        try:
            for piece in stream_reply(api_key, model, messages, context, self.stopped):
                pieces.append(piece)
                self.events.put(lambda piece=piece: self.ui.append_reply(piece))
            self.events.put(lambda: self.reply_done(messages + [("assistant", "".join(pieces))]))
        except AiError as error:
            self.events.put(lambda text=str(error): self.reply_failed(text))

    def reply_done(self, history: list[tuple[str, str]]):
        self.history = history[-12:]
        self.replying = False
        self.ui.finish_reply()
        self.refresh_pet()

    def reply_failed(self, text: str):
        self.replying = False
        self.ui.finish_reply(text)
        self.refresh_pet()

    def drain_events(self):
        if self.instance.consume_wake():
            self.ui.show_panel("chat")
        for _ in range(100):
            try:
                callback = self.events.get_nowait()
            except queue.Empty:
                break
            callback()
            if self.stopped.is_set():
                return
        self.root.after(30 if self.replying else 100, self.drain_events)

    def quit(self):
        self.stopped.set()
        self.save()
        self.tray.stop()
        self.root.destroy()


if __name__ == "__main__":
    instance = SingleInstance()
    if not instance.primary:
        instance.wake()
        instance.close()
        raise SystemExit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        root = tk.Tk()
        root.withdraw()
        try:
            companion = Companion(root, load_settings(), instance)
        except (OSError, ValueError) as error:
            messagebox.showerror("Orbit 启动失败", str(error), parent=root)
            root.destroy()
            raise SystemExit(1)
        root.deiconify()
        if not CONFIG.exists():
            companion.ui.show_panel("settings")
        root.mainloop()
    finally:
        instance.close()
