import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from skills.mail_scan import choose_mailboxes
from skills.mail_scan import format_scan_report
from skills.mail_scan import local_screen
from skills.mail_scan import parse_mailbox_name
from skills.mail_scan import queue_mail_notice
from skills.sifter import MailAccount
from skills.sifter import SifterSkill


class MailScanTests(unittest.TestCase):
    def test_bill_folders_are_kept_and_spam_is_not(self):
        names = [
            parse_mailbox_name('(\\HasNoChildren) "/" "INBOX"'),
            parse_mailbox_name('(\\HasNoChildren) "/" "[Gmail]/All Mail"'),
            parse_mailbox_name('(\\HasNoChildren) "/" "[Gmail]/Receipts"'),
            parse_mailbox_name('(\\HasNoChildren) "/" "Archive"'),
            parse_mailbox_name('(\\HasNoChildren) "/" "[Gmail]/Spam"'),
            parse_mailbox_name('(\\HasNoChildren) "/" "Sent"'),
        ]
        self.assertEqual(
            choose_mailboxes(names),
            ["INBOX", "[Gmail]/All Mail", "[Gmail]/Receipts", "Archive"],
        )

    def test_the_better_scan_subjects_land_in_the_right_buckets(self):
        cases = [
            ("You made some changes to your wireless account", "upcoming_bill"),
            ("[Action Required] Your Jira subscription will be deactivated soon", "renewal"),
            ("Your October account statement is available.", "statement"),
            ("Your Insurance Documents for policy ending in 3906.", "statement"),
            ("You've got 8 credits!", "subscription"),
            ("My Credit monthly monitoring summary", None),
            ("Please Accept It ASAP", None),
            ("Updated Terms of Use", None),
            ("Pre-selected for an Indigo Mastercard", None),
        ]
        for subject, bucket in cases:
            with self.subTest(subject=subject):
                self.assertEqual(local_screen(subject), bucket)

    def test_report_names_the_bill_and_the_renewal(self):
        report = format_scan_report(
            {
                "accounts": [{"name": "yahoo", "mailboxes": ["INBOX", "Archive"]}],
                "envelopes": 10,
                "unique": 8,
                "opened": 2,
                "unavailable": 0,
            },
            [
                {"bucket": "upcoming_bill", "line": "Nov 15 — AT&T (yahoo): bill estimate $418.13"},
                {"bucket": "renewal", "line": "Nov 15 — Atlassian (techvizpro): deactivates 2026-11-29"},
            ],
            ["My Credit monthly monitoring summary"],
        )
        self.assertIn("10 envelopes reviewed, 8 unique, 2 opened, 0 unavailable", report)
        self.assertIn("Upcoming bill / payment due", report)
        self.assertIn("AT&T", report)
        self.assertIn("Renewal / expiration notice", report)
        self.assertIn("Bottom line:", report)
        self.assertIn("Ignored / not billing", report)


class _FakeImap:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def login(self, *_args):
        return "OK", []

    def list(self):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren) "/" "Archive"',
            b'(\\HasNoChildren) "/" "Bulk"',
        ]

    def select(self, mailbox, readonly=True):
        self.mailbox = mailbox
        return "OK", [b"2"]

    def search(self, *_args):
        if self.mailbox == "INBOX":
            return "OK", [b"1 2"]
        return "OK", [b"5"]

    def fetch(self, query, what):
        if "HEADER.FIELDS" in what:
            rows = {
                b"1": (b"1 (BODY[HEADER.FIELDS] {1}", _header("1", "Weekly deals", "news@example.com")),
                b"2": (
                    b"2 (BODY[HEADER.FIELDS] {1}",
                    _header("2", "You made some changes to your wireless account", "AT&T <bill@att.com>", "<bill-1>"),
                ),
                b"5": (
                    b"5 (BODY[HEADER.FIELDS] {1}",
                    _header("5", "You made some changes to your wireless account", "AT&T <bill@att.com>", "<bill-1>"),
                ),
            }
            return "OK", [rows[token] for token in query.split(b",") if token in rows]
        return "OK", [(b"2 (RFC822 {1}", _full("Upcoming bill estimate $418.13 due 2026-12-10"))]


def _header(uid: str, subject: str, sender: str, message_id: str = "") -> bytes:
    lines = [
        f"Subject: {subject}",
        f"From: {sender}",
        "Date: Sat, 15 Nov 2026 12:00:00 +0000",
    ]
    if message_id:
        lines.append(f"Message-ID: {message_id}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def _full(body: str) -> bytes:
    message = EmailMessage()
    message["Subject"] = "You made some changes to your wireless account"
    message["From"] = "AT&T <bill@att.com>"
    message["Date"] = "Sat, 15 Nov 2026 12:00:00 +0000"
    message["Message-ID"] = "<bill-1>"
    message.set_content(body)
    return message.as_bytes()


class NoticeQueueTests(unittest.TestCase):
    def test_a_statement_can_be_closed_and_does_not_come_back(self):
        from manager import Manager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            first = queue_mail_notice(
                db_path,
                bucket="statement",
                account="yahoo2",
                subject="Your Insurance Documents for policy ending with 3906",
                sender="GEICO <geico@example.com>",
                line="Nov 15 — GEICO (yahoo2): documents",
            )
            second = queue_mail_notice(
                db_path,
                bucket="statement",
                account="yahoo2",
                subject="Your Insurance Documents for policy ending with 3906",
            )
            self.assertEqual(first, second)
            self.assertIsNone(
                queue_mail_notice(
                    db_path,
                    bucket="upcoming_bill",
                    account="yahoo2",
                    subject="AT&T",
                )
            )
            import sqlite3

            status = sqlite3.connect(db_path).execute(
                "SELECT action_type, status FROM pending_actions WHERE action_id = ?",
                (first,),
            ).fetchone()
            self.assertEqual(status, ("mail_notice", "pending"))


class SifterScanTests(unittest.TestCase):
    @patch("priority_inbox.emit_priority_action", return_value="action-1")
    @patch("skills.sifter.imaplib.IMAP4_SSL")
    def test_archive_copy_is_not_opened_twice_and_a_newsletter_stays_closed(self, ssl, _emit):
        ssl.return_value = _FakeImap()
        skill = SifterSkill(accounts=[MailAccount("yahoo", "imap.example", "me@example.com", "secret")])
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            result = skill.run({"payload": {"max_messages": 10, "lookback_days": 7}})
        self.assertIn("AT&T", result["scan_report"])
        self.assertNotIn("Weekly deals", result["scan_report"])
        self.assertEqual(result["scan"]["coverage"]["opened"], 1)
        self.assertEqual(result["scan"]["coverage"]["unique"], 2)
        self.assertEqual(result["scan"]["coverage"]["envelopes"], 3)
        self.assertIn("Archive", result["scan"]["coverage"]["accounts"][0]["mailboxes"])
        self.assertNotIn("Bulk", result["scan"]["coverage"]["accounts"][0]["mailboxes"])
