import ctypes
import sqlite3
import time
from contextlib import closing
from ctypes import wintypes
from datetime import datetime, timezone, timedelta
from pathlib import Path

from models import Task


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def codex_process_running() -> bool | None:
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() == "codex.exe":
                return True
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False if ctypes.get_last_error() == 18 else None
    finally:
        kernel32.CloseHandle(snapshot)


def classify_turn(status: str, last_activity: float, process_running: bool | None) -> tuple[str, str]:
    if status == "completed":
        return "completed", "Codex 已记录本轮完成；具体结果请打开聊天查看。"
    if status == "failed":
        return "failed", "Codex 已记录本轮失败；打开聊天查看原因。"
    if status == "interrupted":
        return "interrupted", "Codex 已记录本轮中断。"
    if status != "inProgress":
        return "unknown", "当前轮没有可识别的结束状态。"
    if process_running is None:
        return "unknown", "本轮尚未记录结束；当前无法确认 Codex 进程。"
    if not process_running:
        return "unknown", "本轮尚未记录结束，但未检测到 Codex 进程。"
    if time.time() - last_activity > 120:
        return "unknown", "本轮尚未记录结束，已超过两分钟没有新活动；可能正在等待。"
    return "running", "Codex 进程存在，本轮最近两分钟有活动；审批等待无法单独识别。"


class CodexMonitor:
    def __init__(self, home: Path):
        self.home = home
        self.process_checked = float("-inf")
        self.process_running: bool | None = None

    def poll(self) -> tuple[list[Task], str]:
        state_path = self.home / "state_5.sqlite"
        history_path = self.home / "thread_history_1.sqlite"
        if not state_path.is_file() or not history_path.is_file():
            return [], "未连接：未找到当前版本的本地 Codex 会话数据库。"

        tasks = []
        try:
            with closing(sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as state_db, closing(
                sqlite3.connect(history_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as history_db:
                state_db.row_factory = sqlite3.Row
                history_db.row_factory = sqlite3.Row
                threads = state_db.execute(
                    "SELECT id, COALESCE(name, title) AS title, updated_at "
                    "FROM threads WHERE archived = 0 AND source NOT LIKE '%subagent%' "
                    "ORDER BY updated_at DESC LIMIT 20"
                ).fetchall()
                for thread in threads:
                    if not isinstance(thread["id"], str) or not isinstance(thread["title"], str) or not isinstance(thread["updated_at"], int):
                        raise ValueError("Codex 会话索引字段格式不受支持。")
                if not threads:
                    return [], "本地只读监测 · 最近 20 个聊天 · 审批等待无法单独识别"
                turns = {row["thread_id"]: row for row in history_db.execute(
                    "WITH wanted(thread_id) AS (VALUES " + ",".join("(?)" for _ in threads) + ") "
                    "SELECT wanted.thread_id, t.turn_id, t.status, t.started_at, t.completed_at, "
                    "(SELECT MAX(i.created_at_ms) FROM thread_items i "
                    "WHERE i.thread_id = t.thread_id AND i.turn_id = t.turn_id) AS last_item "
                    "FROM wanted LEFT JOIN thread_turns t ON t.thread_id = wanted.thread_id "
                    "AND t.turn_id = (SELECT latest.turn_id FROM thread_turns latest "
                    "WHERE latest.thread_id = wanted.thread_id ORDER BY latest.rollout_ordinal DESC LIMIT 1)",
                    [thread["id"] for thread in threads],
                )}
                now = time.monotonic()
                if any(turn["status"] == "inProgress" for turn in turns.values()) and now - self.process_checked >= 10:
                    self.process_running = codex_process_running()
                    self.process_checked = now
                for thread in threads:
                    turn = turns[thread["id"]]
                    if turn["turn_id"] is None:
                        tasks.append(Task(thread["id"], thread["title"], "unknown", "尚未找到本轮状态记录。", datetime.fromtimestamp(thread["updated_at"], timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S UTC+8")))
                        continue
                    if not isinstance(turn["turn_id"], str) or not isinstance(turn["status"], str):
                        raise ValueError("Codex 轮次状态字段格式不受支持。")
                    if turn["last_item"] is not None and not isinstance(turn["last_item"], int):
                        raise ValueError("Codex 活动时间字段格式不受支持。")
                    timestamps = [value for value in (turn["started_at"], turn["completed_at"], turn["last_item"] / 1000 if turn["last_item"] is not None else None) if value is not None]
                    if any(not isinstance(value, (int, float)) for value in timestamps):
                        raise ValueError("Codex 轮次时间字段格式不受支持。")
                    last_activity = max(timestamps, default=0)
                    status, detail = classify_turn(turn["status"], last_activity, self.process_running)
                    tasks.append(Task(
                        thread["id"],
                        thread["title"],
                        status,
                        detail,
                        datetime.fromtimestamp(last_activity or thread["updated_at"], timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S UTC+8"),
                        turn["turn_id"],
                    ))
        except sqlite3.Error as error:
            raise ValueError("无法读取 Codex 会话数据库：" + str(error)) from error

        return tasks, "本地只读监测 · 最近 20 个聊天 · 审批等待无法单独识别"
