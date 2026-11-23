import io
import json
import logging
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from desk_settings import get_setting
from desk_settings import set_setting
from telegram_inbox import OFFSET_KEY
from telegram_inbox import TelegramPollError
from telegram_inbox import apply_updates
from telegram_inbox import fetch_updates
from telegram_inbox import prime_offset
from telegram_inbox import reset_for_tests
from telegram_inbox import send_reply
from telegram_inbox import start_if_configured
from telegram_inbox import truncate_reply


class TelegramInboxTests(unittest.TestCase):
    def setUp(self):
        reset_for_tests()

    def tearDown(self):
        reset_for_tests()

    def test_missing_config_does_not_start_a_thread(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False):
            with patch("telegram_inbox.threading.Thread") as thread:
                self.assertFalse(start_if_configured())
        thread.assert_not_called()

    def test_configured_poll_starts_one_daemon_thread(self):
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "42"},
            clear=False,
        ):
            with patch("telegram_inbox.threading.Thread") as thread:
                self.assertTrue(start_if_configured())
                self.assertFalse(start_if_configured())
        kwargs = thread.call_args.kwargs
        self.assertEqual(kwargs.get("name"), "telegram-inbox")
        self.assertTrue(kwargs.get("daemon"))
        thread.return_value.start.assert_called_once()

    def test_only_the_configured_chat_is_answered_and_the_offset_advances(self):
        replies = []
        sent = []
        updates = [
            {"update_id": 7, "message": {"chat": {"id": 99}, "text": "ignore me"}},
            {"update_id": 8, "message": {"chat": {"id": 42}, "photo": [{}]}},
            {"update_id": 9, "message": {"chat": {"id": "42"}, "text": "  hello "}},
        ]
        nxt = apply_updates(
            updates,
            chat_id="42",
            reply=lambda text: replies.append(text) or "noted",
            send=sent.append,
        )
        self.assertEqual(replies, ["hello"])
        self.assertEqual(sent, ["noted"])
        self.assertEqual(nxt, 10)

    def test_a_failed_answer_still_advances_and_does_not_raise(self):
        sent = []

        def blow_up(_text):
            raise RuntimeError("boom")

        nxt = apply_updates(
            [{"update_id": 3, "message": {"chat": {"id": 42}, "text": "hi"}}],
            chat_id="42",
            reply=blow_up,
            send=sent.append,
        )
        self.assertEqual(nxt, 4)
        self.assertEqual(sent, ["That could not be answered. Nothing was sent or posted."])

    def test_replies_are_truncated_and_the_token_is_not_logged(self):
        self.assertEqual(len(truncate_reply("x" * 5000)), 3500)
        self.assertTrue(truncate_reply("x" * 5000).endswith("…"))
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logger = logging.getLogger("telegram_inbox")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        captured = {}

        def capture(request, timeout=20, context=None):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["url"] = request.full_url

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def read(self):
                    return b"{}"

            return _Resp()

        try:
            with patch("telegram_inbox.urllib.request.urlopen", capture):
                send_reply("y" * 5000, "test-token", "42")
        finally:
            logger.removeHandler(handler)
        self.assertEqual(captured["body"]["chat_id"], "42")
        self.assertEqual(len(captured["body"]["text"]), 3500)
        self.assertTrue(captured["url"].endswith("/sendMessage"))
        self.assertNotIn("test-token", logs.getvalue())

    def test_poll_errors_do_not_include_the_token(self):
        def fail(request, timeout=20, context=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", None, io.BytesIO(b"{}"))

        with patch("telegram_inbox.urllib.request.urlopen", fail):
            with self.assertRaises(TelegramPollError) as caught:
                fetch_updates("test-token", 4, 0)
        self.assertEqual(str(caught.exception), "Telegram poll failed: HTTP 401")
        self.assertNotIn("test-token", str(caught.exception))

    def test_first_start_confirms_waiting_updates_without_answering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            calls = []
            batches = [
                [{"update_id": 1}, {"update_id": 2}],
                [{"update_id": 3, "message": {"chat": {"id": 42}, "text": "old"}}],
                [],
            ]

            def fake(_token, offset, timeout):
                calls.append((offset, timeout))
                return batches.pop(0)

            with patch("telegram_inbox.fetch_updates", fake):
                self.assertEqual(prime_offset(db_path, "test-token"), 4)
            self.assertEqual(calls, [(None, 0), (3, 0), (4, 0)])
            self.assertEqual(get_setting(db_path, OFFSET_KEY), "4")
            with patch("telegram_inbox.fetch_updates") as fetch:
                self.assertEqual(prime_offset(db_path, "test-token"), 4)
            fetch.assert_not_called()

    def test_a_saved_zero_offset_is_not_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            set_setting(db_path, OFFSET_KEY, "0")
            with patch("telegram_inbox.fetch_updates") as fetch:
                self.assertEqual(prime_offset(db_path, "test-token"), 0)
            fetch.assert_not_called()

    def test_route_text_uses_the_ask_enaam_path(self):
        from manager import Manager
        from telegram_inbox import route_text

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            agent = object()
            try:
                with patch("hey_eman_app._answer", return_value="noted") as answer:
                    self.assertEqual(route_text("hello", manager, agent), "noted")
                answer.assert_called_once_with("hello", manager, agent)
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
