import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from storage import Storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data/orbit.sqlite"
        self.store = Storage(self.path)
        self.addCleanup(lambda: self.store.close())

    def test_conversations_are_isolated_and_persisted(self):
        first = self.store.create_conversation("第一段")
        second = self.store.create_conversation("第二段")
        self.store.add_message(first, "user", "hello")
        reply = self.store.add_message(first, "assistant", "", "streaming")
        self.store.add_message(second, "user", "另一段消息")
        self.store.update_message(reply, "# 回答\n```py\nprint(1)\n```", "completed")
        self.store.rename_conversation(first, "改名")
        self.assertEqual(self.store.conversations()[0].title, "改名")
        self.assertEqual([message.role for message in self.store.messages(first)], ["user", "assistant"])
        self.assertEqual(self.store.messages(second)[0].content, "另一段消息")
        self.store.close()
        self.store = Storage(self.path)
        self.assertEqual(self.store.messages(first)[1].status, "completed")
        self.assertIn("print(1)", self.store.messages(first)[1].content)

    def test_crashed_stream_recovers_as_interrupted(self):
        conversation = self.store.create_conversation()
        self.store.add_message(conversation, "assistant", "未完成的内容", "streaming")
        failed = self.store.add_message(conversation, "assistant", "请求失败", "error")
        self.store.close()
        self.store = Storage(self.path)
        self.assertEqual(self.store.messages(conversation)[0].status, "interrupted")
        self.assertEqual(self.store.messages(conversation)[1].id, failed)
        self.assertEqual(self.store.messages(conversation)[1].status, "error")

    def test_delete_cascades_only_selected_conversation(self):
        first = self.store.create_conversation()
        second = self.store.create_conversation()
        self.store.add_message(first, "user", "删除这条")
        self.store.add_message(second, "user", "保留这条")
        self.store.delete_conversation(first)
        self.assertEqual(self.store.messages(first), [])
        self.assertEqual(self.store.messages(second)[0].content, "保留这条")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.add_message(first, "user", "不存在的会话")

    def test_activity_dedup_survives_restart(self):
        self.assertTrue(self.store.add_activity("本轮完成", "completed", "thread/turn/completed"))
        self.store.close()
        self.store = Storage(self.path)
        self.assertFalse(self.store.add_activity("本轮完成", "completed", "thread/turn/completed"))
        self.assertTrue(self.store.add_activity("休息结束", "focus"))
        self.assertTrue(self.store.add_activity("休息结束", "focus"))
        self.assertEqual(len(self.store.activities()), 3)
        self.assertEqual(len(self.store.activities(1)), 1)

    def test_unread_upgrade_and_reopen_preserve_original_history_and_keys(self):
        old_key = "task:first:old-turn:completed"
        with self.store.db:
            self.store.db.execute("DROP TABLE unread_task_notices")
            self.store.db.execute("INSERT INTO activities VALUES (?,?,?,?,?)",
                                  ("legacy", "旧记录", "task", "2026-11-20", old_key))
        self.store.close()
        self.store = Storage(self.path)
        self.assertEqual(self.store.unread_count(), 0)
        self.assertEqual(self.store.activities(task_filter="all")[0].thread_id, "first")
        for i in range(22):
            self.store.add_activity("同一聊天的新一轮", "task", f"task:first:t{i}:completed", unread=True)
        self.store.close()
        self.store = Storage(self.path)
        self.assertEqual(len(self.store.activities(-1, task_filter="unread")), 22)
        key = "task:first:t12:completed"
        self.store.mark_tasks_read(key)
        self.assertFalse(self.store.add_activity("重复", "task", key, unread=True))
        self.assertEqual(self.store.unread_count(), 21)
        self.store.mark_tasks_read()
        self.assertEqual(self.store.unread_count(), 0)
        self.assertEqual(len(self.store.activities(-1, task_filter="all")), 23)

    def test_focus_history_and_snapshot(self):
        self.store.add_focus_session(1500)
        self.store.add_focus_session(900)
        with self.store.db:
            self.store.db.execute("INSERT INTO focus_sessions VALUES (500, '2000-01-01T12:00:00+08:00')")
        self.assertEqual(self.store.focus_stats(), (2, 2400))
        self.assertEqual(self.store.get_focus(), {})
        self.store.set_focus({"phase": "focus", "state": "paused", "remaining": 1234.5})
        self.store.close()
        self.store = Storage(self.path)
        self.assertEqual(self.store.get_focus()["remaining"], 1234.5)


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = "1.5"
        from PySide6.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data/settings.json"
        self.path.parent.mkdir()
        self.original_key = os.environ.get("OPENAI_API_KEY")
        self.original_model = os.environ.get("OPENAI_MODEL")
        os.environ["OPENAI_API_KEY"] = "test-do-not-persist"
        os.environ["OPENAI_MODEL"] = "model-from-environment"

    def tearDown(self):
        for key, value in (("OPENAI_API_KEY", self.original_key), ("OPENAI_MODEL", self.original_model)):
            if value is None:
                os.environ.pop(key, None)
                continue
            os.environ[key] = value

    def test_defaults_roundtrip_and_secret_omission(self):
        from configuration import load_settings, save_settings
        settings = load_settings(self.path, self.application.screens())
        self.assertEqual(settings.api_key, "test-do-not-persist")
        self.assertEqual(settings.model, "model-from-environment")
        settings.pet_visible = False
        settings.main_geometry = "abc123"
        save_settings(self.path, settings)
        self.assertNotIn("api_key", json.loads(self.path.read_text("utf-8")))
        reloaded = load_settings(self.path, self.application.screens())
        self.assertFalse(reloaded.pet_visible)
        self.assertEqual(reloaded.main_geometry, "abc123")

    def test_legacy_backup_and_dpi_migration_happen_once(self):
        from configuration import load_settings
        screen = self.application.primaryScreen()
        original = json.dumps({"model": "old-model", "pet_size": 240, "topmost": False,
                               "quiet": True, "x": 310, "y": 420, "monitor": screen.name(),
                               "monitor_left": 10, "monitor_top": 20})
        self.path.write_text(original, "utf-8")
        migrated = load_settings(self.path, self.application.screens())
        self.assertEqual(migrated.version, 2)
        self.assertEqual(migrated.pet_x, round(300 / screen.devicePixelRatio()))
        self.assertEqual(migrated.pet_y, round(400 / screen.devicePixelRatio()))
        self.assertEqual(self.path.with_name("settings.v1.bak.json").read_text("utf-8"), original)
        self.assertEqual(json.loads(self.path.read_text("utf-8"))["version"], 2)
        loaded = load_settings(self.path, self.application.screens())
        self.assertEqual(loaded.pet_x, migrated.pet_x)
        self.assertEqual(loaded.pet_y, migrated.pet_y)

    def test_removed_screen_uses_default_position(self):
        from configuration import load_settings
        self.path.write_text(json.dumps({"monitor": "disconnected-screen", "x": -1000, "y": 200}), "utf-8")
        settings = load_settings(self.path, self.application.screens())
        self.assertEqual((settings.monitor, settings.pet_x, settings.pet_y), ("", -1, -1))

    def test_bad_boundary_values_are_rejected(self):
        from configuration import load_settings
        for value in ([], {"version": 3}, {"version": 2, "quiet": "false"},
                      {"version": 2, "focus_minutes": 0}, {"version": 2, "api_key": "secret"}):
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value), "utf-8")
                with self.assertRaises(ValueError):
                    load_settings(self.path, self.application.screens())


if __name__ == "__main__":
    unittest.main()
