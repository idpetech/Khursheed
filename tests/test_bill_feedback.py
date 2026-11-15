import json
import tempfile
import unittest
from pathlib import Path

from bill_feedback import is_bill_suppressed
from bill_feedback import normalize_sender
from bill_feedback import record_not_a_bill
from bill_feedback import reject_not_a_bill
from database_migrations import DatabaseMigrations
from skills.sifter import SifterSkill


class BillFeedbackTests(unittest.TestCase):
    def test_normalize_sender(self):
        email, domain = normalize_sender("AI Secret <newsletter@aisecret.us>")
        self.assertEqual(email, "newsletter@aisecret.us")
        self.assertEqual(domain, "aisecret.us")

    def test_seeded_domain_is_suppressed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            DatabaseMigrations(str(db_path)).run_all_migrations(verbose=False)
            self.assertTrue(
                is_bill_suppressed(
                    db_path,
                    "AI Secret <newsletter@aisecret.us>",
                    "Europe Taxes the Future",
                )
            )

    def test_reject_not_a_bill_closes_and_suppresses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            DatabaseMigrations(str(db_path)).run_all_migrations(verbose=False)
            import sqlite3
            from datetime import UTC, datetime

            conn = sqlite3.connect(db_path)
            payload = {
                "from": "Billing News <alerts@example-news.com>",
                "subject": "Tax update for Europe",
                "kind": "new_bill",
            }
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    priority, status, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "act-1",
                    "new_bill",
                    "new_bill: Fake - 10 EUR",
                    "Tax update for Europe",
                    json.dumps(payload),
                    1,
                    "pending",
                    datetime.now(UTC).isoformat(),
                    "test",
                ),
            )
            conn.commit()
            conn.close()

            result = reject_not_a_bill(db_path, "act-1", reviewed_by="desk")
            self.assertEqual(result["status"], "success")
            self.assertTrue(
                is_bill_suppressed(
                    db_path,
                    "Billing News <alerts@example-news.com>",
                    "Tax update for Europe",
                )
            )

            conn = sqlite3.connect(db_path)
            status = conn.execute(
                "SELECT status FROM pending_actions WHERE action_id = ?",
                ("act-1",),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "rejected")

    def test_aisecret_newsletter_prefilter_skips(self):
        skill = SifterSkill(accounts=[])
        kind = skill._financial_keyword_prefilter(
            "Europe Taxes the Future",
            "AI Secret <newsletter@aisecret.us>",
            "France may charge 10 EUR for digital services. Read more in this newsletter.",
        )
        self.assertIsNone(kind)

    def test_real_invoice_still_matches(self):
        skill = SifterSkill(accounts=[])
        kind = skill._financial_keyword_prefilter(
            "Your invoice is ready",
            "billing@aws.com",
            "Invoice body amount due",
        )
        self.assertEqual(kind, "new_bill")

    def test_record_not_a_bill_subject_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            record_not_a_bill(
                db_path,
                sender="x@y.com",
                subject="Weird charge notice",
                action_id="a1",
            )
            self.assertTrue(is_bill_suppressed(db_path, "other@z.com", "Weird charge notice"))


if __name__ == "__main__":
    unittest.main()
