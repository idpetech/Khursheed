import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from datetime import datetime

from desk_settings import add_icp_company
from desk_settings import ensure_desk_settings
from desk_settings import icp_enabled
from desk_settings import list_icp_seed
from desk_settings import mail_lookback_days
from desk_settings import morning_run_is_due
from desk_settings import parse_morning_time
from desk_settings import prepare_desk_tasks
from desk_settings import remove_icp_company
from desk_settings import set_setting
from executive_summary import _format_leads
from notifications import TelegramNotifier
from notifications import _telegram_chunks
from skills.sifter import SifterSkill


class DeskSettingTests(unittest.TestCase):
    def test_mail_lookback_is_clamped_and_sifter_reads_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            set_setting(db_path, "mail_lookback_days", "99")
            self.assertEqual(mail_lookback_days(db_path), 30)
            skill = SifterSkill(accounts=[])
            self.assertEqual(skill._lookback_days({"payload": {"lookback_days": 14}}), 14)
            self.assertEqual(skill._lookback_days({"payload": {"lookback_days": 0}}), 1)

    def test_morning_run_is_due_once_inside_the_half_hour(self):
        seven = datetime(2026, 11, 14, 7, 0)
        self.assertTrue(morning_run_is_due(seven, "07:00", ""))
        self.assertTrue(morning_run_is_due(datetime(2026, 11, 14, 7, 29), "7:00", ""))
        self.assertFalse(morning_run_is_due(datetime(2026, 11, 14, 7, 30), "07:00", ""))
        self.assertFalse(morning_run_is_due(seven, "07:00", "2026-11-14"))
        self.assertFalse(morning_run_is_due(datetime(2026, 11, 14, 6, 59), "07:00", ""))
        self.assertIsNone(parse_morning_time("7pm"))
        self.assertEqual(parse_morning_time("7:05"), (7, 5))

    def test_icp_stays_off_until_enabled_and_a_removed_company_stays_gone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            ensure_desk_settings(db_path)
            self.assertFalse(icp_enabled(db_path))
            names = {row["company_name"] for row in list_icp_seed(db_path)}
            self.assertIn("Acme Labs", names)
            self.assertEqual(remove_icp_company(db_path, "Acme Labs")["status"], "ok")
            ensure_desk_settings(db_path)
            names = {row["company_name"] for row in list_icp_seed(db_path)}
            self.assertNotIn("Acme Labs", names)
            self.assertEqual(add_icp_company(db_path, "Northwind", industry="saas")["status"], "ok")
            tasks = prepare_desk_tasks(
                [{"id": "task-003", "skills": ["lead_scout"], "interval_days": 3, "payload": {}}],
                db_path,
            )
            self.assertFalse(any("icp_prospector" in task["skills"] for task in tasks))
            set_setting(db_path, "icp_enabled", "1")
            set_setting(db_path, "lead_queries", "warehouse robots\nflorida cto")
            tasks = prepare_desk_tasks(
                [{"id": "task-003", "skills": ["lead_scout"], "interval_days": 3, "payload": {}}],
                db_path,
            )
            lead = next(task for task in tasks if "lead_scout" in task["skills"])
            self.assertEqual(lead["payload"]["queries"], ["warehouse robots", "florida cto"])
            self.assertTrue(any("icp_prospector" in task["skills"] for task in tasks))

    def test_brief_names_a_failed_search(self):
        text = _format_leads([], "the last 7 days", "Tunnel connection failed: 403 Forbidden")
        self.assertIn("last 7 days", text)
        self.assertIn("403 Forbidden", text)

    def test_telegram_skips_when_unconfigured_and_splits_a_long_brief(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False):
            self.assertIn("skipped", TelegramNotifier().send("Morning brief"))
        chunks = _telegram_chunks("line\n" * 4000, limit=3500)
        self.assertGreater(len(chunks), 1)
        sent: list[str] = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"{}"

        def capture(request, timeout=20, context=None):
            sent.append(request.data.decode("utf-8"))
            return Response()

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "42"},
        ):
            with patch("urllib.request.urlopen", capture):
                message = TelegramNotifier().send("x" * 8000)
        self.assertIn("Telegram sent", message)
        self.assertGreater(len(sent), 1)
        self.assertNotIn("token", "".join(sent))


if __name__ == "__main__":
    unittest.main()
