import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from models import Activity, Conversation, Message


LOCAL_TIME = timezone(timedelta(hours=8))


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('streaming', 'completed', 'error', 'interrupted')),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id);
            CREATE TABLE IF NOT EXISTS activities (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                event_key TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS focus_sessions (
                seconds INTEGER NOT NULL CHECK(seconds > 0),
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        with self.db:
            self.db.execute("UPDATE messages SET status = 'interrupted' WHERE status = 'streaming'")

    def create_conversation(self, title="新对话") -> str:
        identity = uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO conversations VALUES (?, ?, ?)",
                            (identity, title, datetime.now(LOCAL_TIME).isoformat()))
        return identity

    def conversations(self) -> list[Conversation]:
        return [Conversation(**row) for row in self.db.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC")]

    def rename_conversation(self, identity: str, title: str):
        with self.db:
            self.db.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                            (title, datetime.now(LOCAL_TIME).isoformat(), identity))

    def delete_conversation(self, identity: str):
        with self.db:
            self.db.execute("DELETE FROM conversations WHERE id = ?", (identity,))

    def messages(self, conversation_id: str) -> list[Message]:
        return [Message(**row) for row in self.db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid", (conversation_id,))]

    def add_message(self, conversation_id: str, role: str, content: str, status="completed") -> str:
        identity = uuid4().hex
        now = datetime.now(LOCAL_TIME).isoformat()
        with self.db:
            self.db.execute("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                            (identity, conversation_id, role, content, status, now))
            self.db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return identity

    def update_message(self, identity: str, content: str, status: str):
        with self.db:
            self.db.execute("UPDATE messages SET content = ?, status = ? WHERE id = ?", (content, status, identity))
            self.db.execute("UPDATE conversations SET updated_at = ? WHERE id = "
                            "(SELECT conversation_id FROM messages WHERE id = ?)",
                            (datetime.now(LOCAL_TIME).isoformat(), identity))

    def add_activity(self, text: str, kind: str, event_key="") -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?) ON CONFLICT(event_key) DO NOTHING",
                (uuid4().hex, text, kind, datetime.now(LOCAL_TIME).isoformat(), event_key or None))
        return cursor.rowcount == 1

    def activities(self, limit=20) -> list[Activity]:
        return [Activity(**row) for row in self.db.execute(
            "SELECT id, text, kind, created_at FROM activities ORDER BY rowid DESC LIMIT ?", (limit,))]

    def add_focus_session(self, seconds: int):
        with self.db:
            self.db.execute("INSERT INTO focus_sessions VALUES (?, ?)",
                            (seconds, datetime.now(LOCAL_TIME).isoformat()))

    def focus_stats(self) -> tuple[int, int]:
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(seconds), 0) FROM focus_sessions WHERE completed_at >= ?",
            (datetime.now(LOCAL_TIME).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),),
        ).fetchone()
        return row[0], row[1]

    def get_focus(self) -> dict[str, str | int | float]:
        row = self.db.execute("SELECT value FROM app_state WHERE key = 'focus'").fetchone()
        return json.loads(row[0]) if row is not None else {}

    def set_focus(self, snapshot: dict[str, str | int | float]):
        with self.db:
            self.db.execute("INSERT INTO app_state VALUES ('focus', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(snapshot),))

    def close(self):
        self.db.close()
