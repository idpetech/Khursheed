import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from bill_feedback import is_bill_suppressed
from bill_feedback import reject_not_a_bill
from billers import add_biller
from billers import domain_matches
from billers import find_biller
from billers import registrable_domain
from billers import remove_biller
from billers import watched_candidate_kind
from database_migrations import DatabaseMigrations
from runtime import resolve_db_path
from skills.sifter import SifterSkill


def _insert_bill(db_path: Path, action_id: str, sender: str, subject: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO pending_actions (
            action_id, action_type, title, description, payload_json,
            priority, status, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action_id,
            "new_bill",
            "bill",
            subject,
            json.dumps({"from": sender, "subject": subject}),
            1,
            "pending",
            datetime.now(UTC).isoformat(),
            "test",
        ),
    )
    conn.commit()
    conn.close()


class BillerTests(unittest.TestCase):
    def test_subdomain_matches_registered_domain(self):
        self.assertTrue(domain_matches("mail2.jea.com", "jea.com"))
        self.assertTrue(domain_matches("info6.citi.com", "citi.com"))
        self.assertFalse(domain_matches("notjea.com", "jea.com"))
        self.assertEqual(registrable_domain("ebill@mail2.jea.com".split("@")[1]), "jea.com")

    def test_seeded_cursor_mail_is_watched_without_keywords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            DatabaseMigrations(str(db_path)).run_all_migrations(verbose=False)
            kind = watched_candidate_kind(db_path, "Cursor <receipts@mail.cursor.com>")
            self.assertEqual(kind, "trial_ending")
            row = find_biller(db_path, "JEA <ebill@mail2.jea.com>")
            self.assertEqual(row["domain"], "jea.com")
            self.assertEqual(watched_candidate_kind(db_path, "news@example.com"), None)

    def test_add_and_remove_biller(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            added = add_biller(db_path, "billing@news.paypal.com", "PayPal", "bill")
            self.assertEqual(added["domain"], "paypal.com")
            again = add_biller(db_path, "paypal.com", "PayPal", "bill")
            self.assertFalse(again["inserted"])
            self.assertEqual(remove_biller(db_path, "paypal.com")["status"], "ok")
            self.assertIsNone(find_biller(db_path, "a@paypal.com"))

    def test_not_a_bill_on_watched_domain_keeps_other_mail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            DatabaseMigrations(str(db_path)).run_all_migrations(verbose=False)
            _insert_bill(
                db_path,
                "act-pp",
                "PayPal <service@paypal.com>",
                "You sent a payment",
            )
            result = reject_not_a_bill(db_path, "act-pp")
            self.assertEqual(result["status"], "success")
            self.assertIn("still read other mail", result["message"])
            self.assertTrue(
                is_bill_suppressed(db_path, "PayPal <service@paypal.com>", "You sent a payment")
            )
            self.assertFalse(
                is_bill_suppressed(db_path, "PayPal <service@paypal.com>", "Your invoice is ready")
            )
            self.assertFalse(
                is_bill_suppressed(db_path, "PayPal <news@paypal.com>", "You sent a payment")
            )

    def test_candidate_kind_uses_biller_list_before_keywords(self):
        skill = SifterSkill(accounts=[])
        with patch("billers.watched_candidate_kind", return_value="trial_ending"):
            kind = skill._candidate_kind(
                "Thanks for using Cursor",
                "Cursor <hi@cursor.com>",
                "No payment phrase in this body.",
            )
        self.assertEqual(kind, "trial_ending")
        with patch("billers.watched_candidate_kind", return_value=None):
            kind = skill._candidate_kind("Hello", "a@example.com", "just saying hi")
        self.assertIsNone(kind)

    def test_db_path_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = str(Path(tmpdir) / "desk.db")
            with patch.dict(os.environ, {"KHURSHEED_DB_PATH": target}):
                self.assertEqual(resolve_db_path("khursheed.db"), Path(target))
            nested = str(Path(tmpdir) / "volume" / "khursheed.db")
            with patch.dict(os.environ, {"KHURSHEED_DB_PATH": nested}):
                from runtime import brief_path

                resolved = resolve_db_path("khursheed.db")
                self.assertTrue(resolved.parent.is_dir())
                self.assertEqual(brief_path(), resolved.parent / "executive_summary.md")
            self.assertTrue(str(resolve_db_path("other.db")).endswith("other.db"))


if __name__ == "__main__":
    unittest.main()
