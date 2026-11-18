import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_usage import CodexUsageImporter
from usage_store import UsageStore


def usage(input_tokens, output_tokens, cached=0, reasoning=0):
    return {'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
            'cached_input_tokens': cached, 'reasoning_output_tokens': reasoning}


def meta(boundary=0):
    return {'type': 'session_meta', 'timestamp': '2026-11-01T01:00:00Z',
            'payload': {'id': 'child', 'subagent_history_start_ordinal': boundary}}


def token(total, last, timestamp='2026-11-01T01:00:01Z'):
    return {'type': 'event_msg', 'timestamp': timestamp,
            'payload': {'type': 'token_count', 'info': {'total_token_usage': total, 'last_token_usage': last}}}


def write(path, records, mode='w'):
    with path.open(mode, encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record) + '\n')


class CodexUsageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        (self.home / 'sessions').mkdir()
        (self.home / 'archived_sessions').mkdir()
        self.path = self.home / 'sessions/session.jsonl'
        self.store = UsageStore(self.home / 'usage.sqlite')
        self.addCleanup(self.store.close)
        self.importer = CodexUsageImporter(self.home, self.store)

    def rows(self):
        return list(self.store.db.execute("SELECT * FROM token_usage WHERE source='codex' ORDER BY occurred_at"))

    def test_initial_baseline_repeats_and_increment(self):
        first = token(usage(10000, 1000, 5000, 100), usage(100, 10, 50, 1))
        duplicate = token(usage(10000, 1000, 5000, 100), usage(0, 0), '2026-11-01T01:00:02Z')
        duplicate['payload']['info']['last_token_usage']['total_tokens'] = 12500
        second = token(usage(10200, 1020, 5100, 102), usage(200, 20, 100, 2), '2026-11-01T01:00:03Z')
        write(self.path, [meta(), {'type':'turn_context','payload':{'model':'example-model'}}, first, duplicate, second])
        self.importer.scan()
        self.assertEqual([row['total_tokens'] for row in self.rows()], [110, 220])
        self.assertEqual(self.rows()[0]['model'], 'example-model')
        self.assertIn('本次新增 0 条', self.importer.scan())

    def test_archived_copy_and_rescan_are_deduplicated(self):
        write(self.path, [meta(), token(usage(100, 10), usage(100, 10))])
        self.importer.scan()
        shutil.copyfile(self.path, self.home / 'archived_sessions/moved.jsonl')
        self.importer.scan()
        self.assertEqual(len(self.rows()), 1)
        self.path.unlink()
        self.assertIn('本次新增 0 条', self.importer.scan())

    def test_partial_line_is_processed_only_when_finished(self):
        write(self.path, [meta()])
        raw = json.dumps(token(usage(100, 10), usage(100, 10)))
        with self.path.open('a',encoding='utf-8') as stream:
            stream.write(raw[:40])
        self.importer.scan()
        self.assertEqual(len(self.rows()), 0)
        with self.path.open('a',encoding='utf-8') as stream:
            stream.write(raw[40:] + '\n')
        self.importer.scan()
        self.assertEqual(len(self.rows()), 1)

    def test_fork_inherited_prefix_is_not_counted(self):
        inherited = token(usage(1000, 100), usage(1000, 100))
        child = token(usage(20, 2), usage(20, 2), '2026-11-01T02:00:00Z')
        write(self.path, [meta(4), meta(), inherited, {'type':'response_item','payload':{}},
                         {'type':'event_msg','payload':{'type':'thread_settings_applied'}}, child])
        self.importer.scan()
        self.assertEqual([row['total_tokens'] for row in self.rows()], [22])

    def test_counter_reset_and_missing_gap_use_only_last_request(self):
        write(self.path, [meta(), token(usage(100, 10), usage(100, 10)),
                         token(usage(20, 2), usage(20, 2), '2026-11-01T02:00:00Z'),
                         token(usage(1000, 100), usage(30, 3), '2026-11-01T03:00:00Z')])
        status = self.importer.scan()
        self.assertEqual([row['total_tokens'] for row in self.rows()], [110, 22, 33])
        self.assertIn('统计可能不完整', status)

    def test_bad_token_record_reports_gap_instead_of_zero(self):
        write(self.path, [meta(), token({}, {})])
        self.assertIn('1 条记录缺失或异常', self.importer.scan())
        self.assertFalse(self.rows())
        self.assertIn('1 条记录缺失或异常', self.importer.scan())

    def test_truncation_is_rescanned_without_counting_old_rows_twice(self):
        write(self.path, [meta(), token(usage(100, 10), usage(100, 10)),
                         token(usage(200, 20), usage(100, 10), '2026-11-01T02:00:00Z')])
        self.importer.scan()
        write(self.path, [meta(), token(usage(50, 5), usage(50, 5), '2026-11-01T03:00:00Z')])
        self.importer.scan()
        self.assertEqual(len(self.rows()), 3)

    def test_same_size_rewrite_is_rescanned(self):
        write(self.path, [meta(), token(usage(100, 10), usage(100, 10))])
        self.importer.scan()
        original = self.path.stat()
        write(self.path, [meta(), token(usage(200, 20), usage(200, 20), '2026-11-01T02:00:00Z')])
        self.assertEqual(self.path.stat().st_size, original.st_size)
        os.utime(self.path, ns=(original.st_atime_ns, original.st_mtime_ns + 1000000))
        self.importer.scan()
        self.assertEqual([row['total_tokens'] for row in self.rows()], [110, 220])
        self.assertIn('本次新增 0 条', self.importer.scan())

    def test_rate_limit_only_event_is_not_usage(self):
        write(self.path, [meta(), {'type':'event_msg','payload':{'type':'token_count','info':None}}])
        status=self.importer.scan()
        self.assertNotIn('异常', status)
        self.assertFalse(self.rows())


if __name__ == '__main__':
    unittest.main()
