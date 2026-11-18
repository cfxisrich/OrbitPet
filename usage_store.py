import sqlite3
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
        """)

    def add(self, record: UsageRecord) -> bool:
        return self.add_many([record]) == 1

    def add_many(self, records: list[UsageRecord]) -> int:
        with self.db:
            cursor = self.db.executemany(
                "INSERT INTO token_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, event_key) DO NOTHING", (astuple(record) for record in records))
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
        return UsageReport(start, end, period, source, totals, buckets)

    def close(self):
        self.db.close()
