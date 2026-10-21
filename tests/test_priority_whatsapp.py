"""Urgent priority actions send one WhatsApp template and do not email."""

import json
import os
import sqlite3
import tempfile
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import patch

from datetime import datetime

from notifications import send_whatsapp_template
from priority_inbox import emit_priority_action
from priority_inbox import priority_for_bill
from priority_inbox import refresh_open_bill_priorities


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE pending_actions (
            action_id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL,
            expires_at TEXT,
            source_key TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX idx_pending_actions_source_key
        ON pending_actions(source_key) WHERE source_key IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE TABLE notification_log (
            log_id TEXT PRIMARY KEY,
            notification_type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            subject TEXT,
            content TEXT,
            status TEXT NOT NULL,
            sent_at TEXT,
            error_message TEXT,
            related_action_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )


def _logs(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT notification_type, status, content FROM notification_log"
        ).fetchall()
    finally:
        conn.close()


class WhatsAppTemplateTests(unittest.TestCase):
    def test_posts_approved_template(self):
        captured = {}

        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def _urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return _Response()

        env = {
            "WHATSAPP_ACCESS_TOKEN": "token",
            "WHATSAPP_PHONE_NUMBER_ID": "123",
            "WHATSAPP_TO": "+1 (555) 010-0000",
            "WHATSAPP_TEMPLATE_NAME": "enaam_urgent",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("notifications.urllib.request.urlopen", _urlopen):
                result = send_whatsapp_template("Bill\ndue", "  ")

        self.assertEqual(result, "WhatsApp sent to 15550100000")
        self.assertEqual(
            captured["url"], "https://graph.facebook.com/v21.0/123/messages"
        )
        self.assertEqual(captured["auth"], "Bearer token")
        self.assertEqual(captured["body"]["to"], "15550100000")
        self.assertEqual(captured["body"]["template"]["name"], "enaam_urgent")
        params = captured["body"]["template"]["components"][0]["parameters"]
        self.assertEqual(params[0]["text"], "Bill due")
        self.assertEqual(params[1]["text"], "—")

    def test_http_error_raises(self):
        env = {
            "WHATSAPP_ACCESS_TOKEN": "token",
            "WHATSAPP_PHONE_NUMBER_ID": "123",
            "WHATSAPP_TO": "15550100000",
            "WHATSAPP_TEMPLATE_NAME": "enaam_urgent",
        }

        def _urlopen(request, timeout=0):
            raise urllib.error.HTTPError(
                request.full_url, 400, "bad", hdrs=None, fp=BytesIO(b"nope")
            )

        with patch.dict(os.environ, env, clear=False):
            with patch("notifications.urllib.request.urlopen", _urlopen):
                with self.assertRaises(RuntimeError):
                    send_whatsapp_template("Title", "Detail")


class PriorityWhatsAppTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "inbox.db")
        conn = sqlite3.connect(self.db_path)
        try:
            _schema(conn)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _emit(self, priority: int, source_key: str = "bill-1") -> str:
        return emit_priority_action(
            kind="overdue_payment",
            title="overdue_payment: Acme - 50 USD due 2026-10-01",
            description="Invoice past due",
            payload={"vendor": "Acme", "amount": 50, "currency": "USD", "due_date": "2026-10-01"},
            priority=priority,
            source_key=source_key,
            db_path=self.db_path,
        )

    def test_priority_3_sends_once(self):
        with patch("priority_inbox.send_whatsapp_template", return_value="WhatsApp sent") as send:
            first = self._emit(3)
            second = self._emit(3)

        self.assertEqual(first, second)
        send.assert_called_once()
        title, detail = send.call_args.args
        self.assertIn("Acme", title)
        self.assertEqual(detail, "Acme · 50 USD · due 2026-10-01. Have you paid this?")
        self.assertEqual(_logs(self.db_path), [("whatsapp", "sent", detail)])

    def test_bill_arrival_asks_once(self):
        with patch("priority_inbox.send_whatsapp_template", return_value="WhatsApp sent") as send:
            action_id = self._emit(2, source_key="soon-1")
            self._emit(2, source_key="soon-1")

        send.assert_called_once()
        self.assertIn("Have you paid this?", send.call_args.args[1])
        self.assertEqual(len(_logs(self.db_path)), 1)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT action_id FROM pending_actions WHERE source_key = ?",
                ("soon-1",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], action_id)

    def test_api_failure_still_stores_action(self):
        with patch(
            "priority_inbox.send_whatsapp_template",
            side_effect=RuntimeError("WhatsApp API returned HTTP 400"),
        ):
            action_id = self._emit(3, source_key="fail-1")

        conn = sqlite3.connect(self.db_path)
        try:
            stored = conn.execute(
                "SELECT action_id FROM pending_actions WHERE source_key = ?",
                ("fail-1",),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(stored[0], action_id)
        logs = _logs(self.db_path)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0][0], "whatsapp")
        self.assertEqual(logs[0][1], "failed")

    def test_stored_bill_rises_without_a_new_email(self):
        action_id = self._emit(1, source_key="jea-1")
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE pending_actions
                    SET action_type = 'new_bill', priority = 1,
                        payload_json = ?
                    WHERE action_id = ?
                    """,
                    (
                        json.dumps({"vendor": "JEA", "amount": 1158, "currency": "USD", "due_date": "2020-01-01"}),
                        action_id,
                    ),
                )
        finally:
            conn.close()

        with patch("priority_inbox.send_whatsapp_template", return_value="WhatsApp sent") as send:
            updated = refresh_open_bill_priorities(self.db_path)
            refresh_open_bill_priorities(self.db_path)

        self.assertEqual(updated, [action_id])
        send.assert_called_once()
        conn = sqlite3.connect(self.db_path)
        try:
            priority = conn.execute(
                "SELECT priority FROM pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(priority, 3)

    def test_far_due_date_stays_low(self):
        priority, _expires = priority_for_bill("new_bill", "2027-11-05", now=datetime(2026, 10, 21))
        self.assertEqual(priority, 1)
        priority, _expires = priority_for_bill("new_bill", "2026-10-26", now=datetime(2026, 10, 21))
        self.assertEqual(priority, 2)
