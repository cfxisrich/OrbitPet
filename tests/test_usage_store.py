from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage import Storage
from usage_store import UsageRecord, UsageStore


def record(key, instant, source="codex"):
    return UsageRecord(key, source, int(datetime.fromisoformat(instant).timestamp()), 100, 20, 120, 70, 10, "model")


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "orbit.sqlite"
        self.store = UsageStore(self.path)
        self.addCleanup(self.store.close)

    def test_day_uses_beijing_half_open_boundaries_and_24_hours(self):
        self.store.add_many([
            record("before", "2026-11-16T15:59:59+00:00"),
            record("start", "2026-11-16T16:00:00+00:00"),
            record("last", "2026-11-17T15:59:59+00:00"),
            record("next", "2026-11-17T16:00:00+00:00"),
        ])
        report = self.store.report("day", "all", date(2026, 11, 17))
        self.assertEqual((report.start, report.end), (date(2026, 11, 17), date(2026, 11, 18)))
        self.assertEqual(len(report.buckets), 24)
        self.assertEqual(report.totals.records, 2)
        self.assertEqual(report.buckets[0].label, "00:00")
        self.assertEqual(report.buckets[0].totals.records, 1)
        self.assertEqual(report.buckets[-1].totals.records, 1)

    def test_week_starts_monday_across_year_boundary(self):
        self.store.add_many([record("sun", "2025-12-28T23:59:59+08:00"),
                             record("mon", "2025-12-29T00:00:00+08:00"),
                             record("next", "2026-01-05T00:00:00+08:00")])
        report = self.store.report("week", "all", date(2026, 1, 4))
        self.assertEqual((report.start, report.end), (date(2025, 12, 29), date(2026, 1, 5)))
        self.assertEqual(len(report.buckets), 7)
        self.assertEqual(report.totals.records, 1)

    def test_calendar_month_handles_leap_day_and_december_rollover(self):
        self.store.add_many([record("leap", "2024-02-29T23:59:59+08:00"),
                             record("march", "2024-03-01T00:00:00+08:00")])
        leap = self.store.report("month", "codex", date(2024, 2, 29))
        self.assertEqual(len(leap.buckets), 29)
        self.assertEqual(leap.totals.records, 1)
        self.assertEqual(leap.end, date(2024, 3, 1))
        december = self.store.report("month", "all", date(2026, 12, 3))
        self.assertEqual(december.end, date(2027, 1, 1))
        self.assertEqual(len(december.buckets), 31)

    def test_filters_dedup_and_subsets_do_not_inflate_total(self):
        first = record("same", "2026-11-17T10:00:00+08:00")
        self.assertTrue(self.store.add(first))
        self.assertFalse(self.store.add(first))
        self.assertEqual(self.store.add_many([first, record("same", "2026-11-17T10:00:00+08:00", "orbit")]), 1)
        combined = self.store.report("day", "all", date(2026, 11, 17)).totals
        self.assertEqual((combined.input_tokens, combined.output_tokens, combined.total_tokens,
                          combined.cached_tokens, combined.reasoning_tokens, combined.records),
                         (200, 40, 240, 140, 20, 2))
        self.assertEqual(self.store.report("day", "orbit", date(2026, 11, 17)).totals.total_tokens, 120)
        self.assertEqual(self.store.report("day", "codex", date(2026, 11, 17)).totals.total_tokens, 120)

    def test_usage_survives_chat_deletion_and_reopening(self):
        chats = Storage(self.path)
        identity = chats.create_conversation()
        chats.add_message(identity, "user", "hello")
        self.store.add(record("reply", "2026-11-17T10:00:00+08:00", "orbit"))
        chats.delete_conversation(identity)
        chats.close()
        reopened = UsageStore(self.path)
        try:
            self.assertEqual(reopened.report("day", "orbit", date(2026, 11, 17)).totals.total_tokens, 120)
            self.assertFalse(reopened.add(record("reply", "2026-11-17T10:00:00+08:00", "orbit")))
        finally:
            reopened.close()

    def test_independent_thread_connection_and_chat_connection_coexist(self):
        chats = Storage(self.path)
        identity = chats.create_conversation()

        def import_records():
            background = UsageStore(self.path)
            try:
                return background.add_many([record(str(index), "2026-11-17T10:00:00+08:00") for index in range(80)])
            finally:
                background.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            importing = executor.submit(import_records)
            chats.add_message(identity, "user", "concurrent write")
            self.store.add(record("reply", "2026-11-17T10:00:00+08:00", "orbit"))
            self.assertEqual(importing.result(), 80)
        chats.close()
        self.assertEqual(self.store.report("day", "all", date(2026, 11, 17)).totals.records, 81)

    def test_empty_month_has_zero_buckets_and_no_fake_records(self):
        report = self.store.report("month", "all", date(2026, 2, 8))
        self.assertEqual(len(report.buckets), 28)
        self.assertEqual(report.totals.records, 0)
        self.assertTrue(all(bucket.totals.total_tokens == 0 for bucket in report.buckets))


if __name__ == "__main__":
    unittest.main()
