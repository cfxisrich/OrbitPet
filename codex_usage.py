import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from usage_store import UsageRecord, UsageStore


COUNTERS = ('input_tokens', 'output_tokens', 'total_tokens',
            'cached_input_tokens', 'reasoning_output_tokens')


@dataclass
class Checkpoint:
    offset: int = 0
    ordinal: int = 0
    boundary: int = 0
    model: str = ''
    totals: list[int] = field(default_factory=list)
    warnings: int = 0
    chat_id: str = ''


class CodexUsageImporter:
    def __init__(self, home: Path, store: UsageStore):
        self.home = home
        self.store = store
        # Older cursors lack chat IDs, so each existing log must be attributed once.
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS codex_chat_cursors (
            path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
            offset INTEGER NOT NULL, ordinal INTEGER NOT NULL, boundary INTEGER NOT NULL,
            model TEXT NOT NULL, totals TEXT NOT NULL, warnings INTEGER NOT NULL, chat_id TEXT NOT NULL
        )''')
        self.store.db.commit()

    def scan(self) -> str:
        roots = [self.home / name for name in ('sessions', 'archived_sessions')]
        if not any(root.is_dir() for root in roots):
            return 'Codex 日志未找到；已保存用量仍可查看。'
        try:
            files = sorted({path for root in roots for path in root.rglob('*.jsonl')})
        except OSError:
            return '无法列出 Codex 日志；已保存用量仍可查看。'
        if not files:
            return 'Codex 日志中没有可读取的会话文件；已保存用量仍可查看。'
        failed = 0
        imported = 0
        warnings = 0
        for path in files:
            try:
                imported += self._scan_file(path)
                warnings += self.store.db.execute('SELECT warnings FROM codex_chat_cursors WHERE path = ?',
                                                  (str(path),)).fetchone()[0]
            except (OSError, ValueError):
                failed += 1
        count = self.store.db.execute("SELECT COUNT(*) FROM token_usage WHERE source = 'codex'").fetchone()[0]
        status = f'Codex：{len(files)} 个本机日志，{count} 条可还原用量（含子代理）；本次新增 {imported} 条。'
        if failed or warnings:
            status += f' {failed} 个文件读取失败，{warnings} 条记录缺失或异常；统计可能不完整。'
        return status + ' 仅统计本机日志可还原记录。'

    def _scan_file(self, path: Path) -> int:
        stat = path.stat()
        previous = self.store.db.execute('SELECT * FROM codex_chat_cursors WHERE path = ?',
                                         (str(path),)).fetchone()
        if previous is not None and previous['size'] == stat.st_size and previous['mtime_ns'] == stat.st_mtime_ns:
            return 0
        checkpoint = Checkpoint()
        if previous is not None and stat.st_size > previous['size']:
            checkpoint = Checkpoint(previous['offset'], previous['ordinal'], previous['boundary'],
                                    previous['model'], json.loads(previous['totals']), previous['warnings'], previous['chat_id'])
        records = []
        imported = 0
        with path.open('rb') as stream:
            stream.seek(checkpoint.offset)
            while raw := stream.readline():
                if not raw.endswith(b'\n'):
                    break
                ordinal = checkpoint.ordinal
                checkpoint.ordinal += 1
                checkpoint.offset = stream.tell()
                if not any(marker in raw for marker in (b'"session_meta"', b'"turn_context"', b'"token_count"')):
                    continue
                try:
                    record = json.loads(raw)
                    if not isinstance(record, dict):
                        raise ValueError('Unexpected log record')
                    payload = record['payload']
                    if ordinal == 0 and record['type'] == 'session_meta':
                        identity = payload.get('id', '')
                        if not isinstance(identity, str):
                            raise ValueError('Invalid session ID')
                        checkpoint.chat_id = identity
                        boundary = payload.get('subagent_history_start_ordinal', 0)
                        if type(boundary) is not int or boundary < 0:
                            raise ValueError('Invalid inherited-history boundary')
                        checkpoint.boundary = boundary
                        continue
                    if ordinal < checkpoint.boundary:
                        continue
                    if record['type'] == 'turn_context':
                        model = payload.get('model', '')
                        if not isinstance(model, str):
                            raise ValueError('Invalid model')
                        checkpoint.model = model
                        continue
                    if record['type'] != 'event_msg' or payload.get('type') != 'token_count':
                        continue
                    info = payload.get('info')
                    if info is None:
                        continue
                    totals = [info['total_token_usage'][name] if index < 3 else info['total_token_usage'].get(name, 0)
                              for index, name in enumerate(COUNTERS)]
                    if any(type(value) is not int or value < 0 for value in totals):
                        raise ValueError('Invalid cumulative usage')
                    if totals == checkpoint.totals:
                        continue
                    last = [info['last_token_usage'][name] if index < 3 else info['last_token_usage'].get(name, 0)
                            for index, name in enumerate(COUNTERS)]
                    if any(type(value) is not int or value < 0 for value in last):
                        raise ValueError('Invalid last usage')
                    values = [current - old for current, old in zip(totals, checkpoint.totals)] if checkpoint.totals else last
                    # Resumed/reset counters provide only this last request, not a dated historical baseline.
                    if values != last:
                        values = last
                        checkpoint.warnings += 1
                    checkpoint.totals = totals
                    if values[2] != values[0] + values[1] or values[3] > values[0] or values[4] > values[1]:
                        raise ValueError('Inconsistent token usage')
                    if values[2] == 0:
                        continue
                    timestamp = datetime.fromisoformat(record['timestamp'])
                    if timestamp.tzinfo is None:
                        raise ValueError('Missing timestamp timezone')
                    identity = json.dumps([record['timestamp'], totals, last], separators=(',', ':'))
                    records.append(UsageRecord(hashlib.sha256(identity.encode()).hexdigest(), 'codex',
                                               int(timestamp.timestamp()), values[0], values[1], values[2],
                                               values[3], values[4], checkpoint.model, checkpoint.chat_id))
                    if len(records) == 200:
                        imported += self.store.add_many(records)
                        records.clear()
                except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError) as error:
                    if ordinal == 0:
                        raise ValueError('Codex 会话元数据无法读取。') from error
                    checkpoint.warnings += 1
        imported += self.store.add_many(records)
        with self.store.db:
            self.store.db.execute('''INSERT INTO codex_chat_cursors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns,
                offset=excluded.offset, ordinal=excluded.ordinal, boundary=excluded.boundary,
                model=excluded.model, totals=excluded.totals, warnings=excluded.warnings, chat_id=excluded.chat_id''',
                (str(path), stat.st_size, stat.st_mtime_ns, checkpoint.offset, checkpoint.ordinal,
                 checkpoint.boundary, checkpoint.model, json.dumps(checkpoint.totals), checkpoint.warnings, checkpoint.chat_id))
        return imported
