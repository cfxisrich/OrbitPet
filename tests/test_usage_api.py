import json
from pathlib import Path
import sys
from threading import Event
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_client import AiError, read_stream


def stream(*events):
    return ("".join("data: " + json.dumps(event) + "\n\n" for event in events)).encode().splitlines(keepends=True)


def terminal(kind="completed", usage=None):
    return {"type": "response." + kind, "response": {
        "id": "resp-test", "model": "test-model", "created_at": 1780416000,
        "completed_at": 1780416005, "usage": usage,
        "error": {"message": "failed after some work"},
        "incomplete_details": {"reason": "max_output_tokens"},
    }}


class UsageApiTests(unittest.TestCase):
    def test_completed_stream_keeps_text_and_records_exact_usage(self):
        captured = []
        events = stream({"type": "response.output_text.delta", "delta": "你好"},
                        terminal(usage={"input_tokens": 120, "output_tokens": 40, "total_tokens": 160,
                                        "input_tokens_details": {"cached_tokens": 80},
                                        "output_tokens_details": {"reasoning_tokens": 30}}))
        self.assertEqual("".join(read_stream(events, Event(), captured.append)), "你好")
        self.assertEqual(len(captured), 1)
        record = captured[0]
        self.assertEqual((record.event_key, record.source, record.occurred_at, record.model),
                         ("resp-test", "orbit", 1780416005, "test-model"))
        self.assertEqual((record.input_tokens, record.output_tokens, record.total_tokens,
                          record.cached_tokens, record.reasoning_tokens), (120, 40, 160, 80, 30))

    def test_incomplete_and_failed_usage_arrives_before_error(self):
        for kind in ("failed", "incomplete"):
            with self.subTest(kind=kind):
                captured = []
                with self.assertRaises(AiError):
                    list(read_stream(stream(terminal(kind, {"input_tokens": 8, "output_tokens": 5,
                                                            "total_tokens": 13})), Event(), captured.append))
                self.assertEqual(captured[0].total_tokens, 13)

    def test_missing_usage_is_not_a_zero_usage_record(self):
        captured = []
        for event in (terminal(), terminal(usage=None)):
            event["response"].pop("usage", None)
            list(read_stream(stream(event), Event(), captured.append))
        list(read_stream(stream(terminal()), Event(), captured.append))
        self.assertEqual(captured, [])

    def test_optional_details_and_completion_time(self):
        captured = []
        event = terminal(usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
                                "input_tokens_details": None, "output_tokens_details": {}})
        event["response"]["completed_at"] = None
        list(read_stream(stream(event), Event(), captured.append))
        self.assertEqual(captured[0].occurred_at, event["response"]["created_at"])
        self.assertEqual((captured[0].cached_tokens, captured[0].reasoning_tokens), (0, 0))

    def test_invalid_usage_is_rejected_once_at_response_boundary(self):
        for changes in ({"input_tokens": -1}, {"input_tokens": True}, {"input_tokens": "3"},
                        {"total_tokens": 9}, {"input_tokens_details": {"cached_tokens": 4}},
                        {"output_tokens_details": {"reasoning_tokens": 3}},
                        {"input_tokens_details": []}):
            with self.subTest(changes=changes):
                captured = []
                usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, **changes}
                with self.assertRaises(ValueError):
                    list(read_stream(stream(terminal(usage=usage)), Event(), captured.append))
                self.assertEqual(captured, [])

    def test_cancelled_stream_does_not_invent_usage(self):
        captured = []
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(AiError):
            list(read_stream(stream(terminal(usage={"input_tokens": 3, "output_tokens": 2,
                                                     "total_tokens": 5})), cancelled, captured.append))
        self.assertEqual(captured, [])


if __name__ == "__main__":
    unittest.main()
