import json
import sys
import unittest
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_client import AiError, read_stream


def events(*records):
    return ("".join("data: " + json.dumps(record, ensure_ascii=False) + "\n\n"
                    for record in records)).encode().splitlines(keepends=True)


class ResponseStreamTests(unittest.TestCase):
    def test_unicode_stream_and_completion(self):
        stream = events(
            {"type": "response.created"},
            {"type": "response.output_text.delta", "delta": "你好"},
            {"type": "response.output_text.delta", "delta": "，Orbit。"},
            {"type": "response.completed"},
        )
        self.assertEqual("".join(read_stream(stream, Event())), "你好，Orbit。")

    def test_truncated_reply_is_not_success(self):
        with self.assertRaisesRegex(AiError, "不完整"):
            list(read_stream(events({"type": "response.output_text.delta", "delta": "半句"}), Event()))

    def test_failure_event(self):
        with self.assertRaisesRegex(AiError, "unavailable"):
            list(read_stream(events({"type": "response.failed", "response": {
                "error": {"message": "unavailable"}}}), Event()))

    def test_incomplete_event(self):
        with self.assertRaisesRegex(AiError, "max_output_tokens"):
            list(read_stream(events({"type": "response.incomplete", "response": {
                "incomplete_details": {"reason": "max_output_tokens"}}}), Event()))

    def test_refusal_is_displayed(self):
        self.assertEqual(list(read_stream(events(
            {"type": "response.refusal.delta", "delta": "无法帮助"},
            {"type": "response.completed"}), Event())), ["无法帮助"])

    def test_shutdown_cancels_stream(self):
        cancelled = Event()
        cancelled.set()
        with self.assertRaisesRegex(AiError, "停止"):
            list(read_stream(events({"type": "response.completed"}), cancelled))

    def test_sse_comments_and_multiline_data(self):
        stream = b': ping\r\nevent: response.output_text.delta\r\ndata: {"type": "response.output_text.delta",\r\ndata: "delta": "ok"}\r\n\r\ndata: {"type": "response.completed"}\r\n\r\n'
        self.assertEqual(list(read_stream(stream.splitlines(keepends=True), Event())), ["ok"])


if __name__ == "__main__":
    unittest.main()
