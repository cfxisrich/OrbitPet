import sqlite3
from contextlib import closing
from dataclasses import astuple, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


LOCAL_TIME = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class UsageRecord:
    event_key: str
    source: str
    occurred_at: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    model: str = ""
    chat_id: str = ""


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    records: int = 0


@dataclass(frozen=True)
class UsageBucket:
    label: str
    totals: UsageTotals


@dataclass(frozen=True)
class UsageReport:
    start: date
    end: date
    period: str
    source: str
    totals: UsageTotals
    buckets: list[UsageBucket]
    chats: list[tuple[str, str, int]]
    models: list[tuple[str, int]]
    unlinked_tokens: int


class UsageStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA busy_timeout = 5000;
            CREATE TABLE IF NOT EXISTS token_usage (
                event_key TEXT NOT NULL,
                source TEXT NOT NULL CHECK(source IN ('codex', 'orbit')),
                occurred_at INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                cached_tokens INTEGER NOT NULL,
                reasoning_tokens INTEGER NOT NULL,
                model TEXT NOT NULL,
                PRIMARY KEY(source, event_key)
            );
            CREATE INDEX IF NOT EXISTS token_usage_time ON token_usage(occurred_at);
            CREATE TABLE IF NOT EXISTS token_chat (
                source TEXT NOT NULL, event_key TEXT NOT NULL, chat_id TEXT NOT NULL,
                PRIMARY KEY(source, event_key)
            ) WITHOUT ROWID;
        """)

    def add(self, record: UsageRecord) -> bool:
        return self.add_many([record]) == 1

    def add_many(self, records: list[UsageRecord]) -> int:
        with self.db:
            cursor = self.db.executemany(
                "INSERT INTO token_usage (event_key,source,occurred_at,input_tokens,output_tokens,"
                "total_tokens,cached_tokens,reasoning_tokens,model) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source, event_key) DO NOTHING", (astuple(record)[:-1] for record in records))
            self.db.executemany("INSERT INTO token_chat(source,event_key,chat_id) VALUES (?,?,?) "
                                "ON CONFLICT(source,event_key) DO NOTHING",
                                ((r.source, r.event_key, r.chat_id) for r in records if r.chat_id))
        return cursor.rowcount

    def report(self, period: str, source: str, anchor: date) -> UsageReport:
        if period not in ("day", "week", "month") or source not in ("all", "codex", "orbit"):
            raise ValueError("用量统计周期或来源不受支持。")
        start = anchor
        end = anchor + timedelta(days=1)
        bucket_seconds = 3600
        if period == "week":
            start = anchor - timedelta(days=anchor.weekday())
            end = start + timedelta(days=7)
            bucket_seconds = 86400
        if period == "month":
            start = anchor.replace(day=1)
            end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
            bucket_seconds = 86400
        with self.db:
            self.db.execute("BEGIN")
            return self._aggregate(start, end, period, source, bucket_seconds)

    def _aggregate(self, start, end, period, source, bucket_seconds):
        start_time = int(datetime.combine(start, time(), LOCAL_TIME).timestamp())
        end_time = int(datetime.combine(end, time(), LOCAL_TIME).timestamp())
        rows = self.db.execute(
            "SELECT (occurred_at - ?) / ? AS bucket, "
            "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            "SUM(total_tokens) AS total_tokens, SUM(cached_tokens) AS cached_tokens, "
            "SUM(reasoning_tokens) AS reasoning_tokens, COUNT(*) AS records "
            "FROM token_usage WHERE occurred_at >= ? AND occurred_at < ? "
            "AND (? = 'all' OR source = ?) GROUP BY bucket",
            (start_time, bucket_seconds, start_time, end_time, source, source),
        ).fetchall()
        grouped = {row["bucket"]: UsageTotals(row["input_tokens"], row["output_tokens"],
                   row["total_tokens"], row["cached_tokens"], row["reasoning_tokens"], row["records"])
                   for row in rows}
        buckets = [UsageBucket(f"{index:02}:00" if period == "day" else
                               (start + timedelta(days=index)).isoformat(),
                               grouped.get(index, UsageTotals()))
                   for index in range((end_time - start_time) // bucket_seconds)]
        totals = UsageTotals(
            sum(bucket.totals.input_tokens for bucket in buckets),
            sum(bucket.totals.output_tokens for bucket in buckets),
            sum(bucket.totals.total_tokens for bucket in buckets),
            sum(bucket.totals.cached_tokens for bucket in buckets),
            sum(bucket.totals.reasoning_tokens for bucket in buckets),
            sum(bucket.totals.records for bucket in buckets),
        )
        bounds = (start_time, end_time, source, source)
        scope = " WHERE occurred_at>=? AND occurred_at<? AND (?='all' OR source=?) "
        linked = " FROM token_usage LEFT JOIN token_chat USING(source,event_key)"
        chats = [tuple(row) for row in self.db.execute(
            "SELECT source,chat_id,SUM(total_tokens) AS n" + linked + scope
            + "AND chat_id IS NOT NULL GROUP BY source,chat_id ORDER BY n DESC,source,chat_id LIMIT 5", bounds)]
        models = [tuple(row) for row in self.db.execute(
            "SELECT model,SUM(total_tokens) AS n FROM token_usage" + scope + "GROUP BY model ORDER BY n DESC,model LIMIT 5", bounds)]
        unlinked = self.db.execute("SELECT COALESCE(SUM(total_tokens),0)" + linked + scope + "AND chat_id IS NULL", bounds).fetchone()[0]
        return UsageReport(start, end, period, source, totals, buckets, chats, models, unlinked)

    def today_total(self, today: date) -> int:
        start = int(datetime.combine(today, time(), LOCAL_TIME).timestamp())
        return self.db.execute("SELECT COALESCE(SUM(total_tokens),0) FROM token_usage WHERE occurred_at>=? AND occurred_at<?",
                               (start, start + 86400)).fetchone()[0]

    def chat_titles(self, chats, codex_index: Path) -> dict[tuple[str, str], str]:
        titles = {}
        for source in ('orbit', 'codex'):
            ids = [identity for kind, identity, _ in chats if kind == source]
            if not ids:
                continue
            slots = ','.join('?' for _ in ids)
            if source == 'orbit':
                rows = self.db.execute(f"SELECT id,title FROM conversations WHERE id IN ({slots})", ids)
                titles.update({(source, identity): title for identity, title in rows})
                continue
            if codex_index.is_file():
                try:
                    with closing(sqlite3.connect(codex_index.resolve().as_uri() + '?mode=ro', uri=True, timeout=.15)) as index:
                        rows = index.execute(f"SELECT id,COALESCE(name,title) FROM threads WHERE id IN ({slots})", ids)
                        titles.update({(source, identity): title for identity, title in rows})
                except sqlite3.Error:
                    # The index may be unavailable while Codex updates it; usage still has its own local copy.
                    continue
        return titles

    def close(self):
        self.db.close()
