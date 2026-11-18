import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_monitor import CodexMonitor, classify_turn


class MonitorTests(unittest.TestCase):
    def test_terminal_states_require_explicit_status(self):
        for status in ("completed", "failed", "interrupted"):
            self.assertEqual(classify_turn(status, 0, None)[0], status)
        self.assertEqual(classify_turn("final", time.time(), True)[0], "unknown")

    def test_running_requires_process_and_recent_activity(self):
        self.assertEqual(classify_turn("inProgress", time.time(), True)[0], "running")
        self.assertEqual(classify_turn("inProgress", time.time() - 121, True)[0], "unknown")
        self.assertEqual(classify_turn("inProgress", time.time(), False)[0], "unknown")
        self.assertEqual(classify_turn("inProgress", time.time(), None)[0], "unknown")

    def test_missing_database_is_disconnected(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks, message = CodexMonitor(Path(directory)).poll()
            self.assertEqual(tasks, [])
            self.assertTrue(message.startswith("未连接"))

    def test_real_sqlite_reading_filters_and_selects_latest_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with sqlite3.connect(home / "state_5.sqlite") as state_db:
                state_db.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, updated_at INTEGER, archived INTEGER, source TEXT)")
                state_db.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)", [
                    ("main", None, "测试主任务", 200, 0, "vscode"),
                    ("child", None, "子任务", 300, 0, '{"subagent":{}}'),
                    ("archived", None, "归档任务", 400, 1, "vscode"),
                    ("empty", "显式标题", "旧标题", 100, 0, "vscode"),
                ])
            state_db.close()
            with sqlite3.connect(home / "thread_history_1.sqlite") as history_db:
                history_db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT, started_at INTEGER, completed_at INTEGER, rollout_ordinal INTEGER)")
                history_db.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, created_at_ms INTEGER)")
                history_db.executemany("INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?)", [
                    ("main", "turn-old", "completed", 100, 110, 1),
                    ("main", "turn-new", "failed", 150, 200, 2),
                ])
            history_db.close()
            state_before = (home / "state_5.sqlite").read_bytes()
            history_before = (home / "thread_history_1.sqlite").read_bytes()
            tasks, message = CodexMonitor(home).poll()
            self.assertEqual([task.id for task in tasks], ["main", "empty"])
            self.assertEqual(tasks[0].state, "failed")
            self.assertEqual(tasks[0].turn_id, "turn-new")
            self.assertEqual(tasks[1].state, "unknown")
            self.assertEqual(tasks[1].title, "显式标题")
            self.assertIn("审批等待无法单独识别", message)
            self.assertEqual(state_before, (home / "state_5.sqlite").read_bytes())
            self.assertEqual(history_before, (home / "thread_history_1.sqlite").read_bytes())


if __name__ == "__main__":
    unittest.main()
