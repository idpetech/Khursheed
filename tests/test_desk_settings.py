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
from executive_summary import mobile_update
from schedule_sync import skill_is_due
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

    def test_icp_switch_saves_from_the_save_button(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            script = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})
import streamlit as st
from desk_settings import icp_enabled
from hey_eman_app import _ensure_research_state, _persist_research

db = {db_path!r}
_ensure_research_state(db)
if st.button("Save", key="save-research"):
    _persist_research(db)
with st.container(key="config-scroll"):
    st.checkbox("Include ICP companies in the morning run", key="desk_icp_enabled")
"""
            app = AppTest.from_string(script, default_timeout=10)
            app.run()
            self.assertFalse(icp_enabled(db_path))
            app.checkbox[0].set_value(True).run()
            self.assertFalse(icp_enabled(db_path))
            app.button[0].click().run()
            self.assertTrue(icp_enabled(db_path))
            self.assertTrue(app.checkbox[0].value)

    def test_mobile_update_is_short_and_hides_the_raw_network_error(self):
        report = "\n".join(
            [
                "# Executive Summary - 2026-11-15",
                "",
                "## Priority Alerts",
                "_No open priority alerts._",
                "",
                "## Tasks Completed",
                "- `sifter` for `task` at whenever",
                "",
                "## Pending Bills",
                "- AT&T - 418.13 USD due 2026-12-10",
                "",
                "## Top Leads",
                "_No leads found in the last 7 days._",
                "",
                "Last search failed: <urlopen error Tunnel connection failed: 403 Forbidden>",
                "",
                "## Fractional CTO Opportunities",
                "_No fractional CTO opportunities found in the last 7 days._",
                "",
                "## Top ICP Companies",
                "_ICP is off. Turn it on in Config._",
                "",
                "## Open Loops",
                "- Now Hiring: 500 Fractional Chief Technology Officer Jobs",
                "",
                "## Recommended Actions",
                "1. No further recommendation.",
                "2. Follow up: Interim CTO at Intellicheck",
                "",
            ]
        )
        text = mobile_update(report)
        self.assertIn("Enaam · 2026-11-15", text)
        self.assertIn("AT&T - 418.13 USD due 2026-12-10", text)
        self.assertNotIn("Handle priority action", text)
        self.assertIn("Search failed", text)
        self.assertNotIn("urlopen", text)
        self.assertNotIn("Now Hiring", text)
        self.assertNotIn("sifter", text)
        self.assertIn("Off. Turn it on in Config.", text)
        self.assertIn("Next: Follow up: Interim CTO at Intellicheck", text)
        morning = datetime(2026, 11, 15, 7, 0, tzinfo=datetime.now().astimezone().tzinfo)
        self.assertTrue(
            skill_is_due(
                "2026-11-14T16:44:07+00:00",
                "failed",
                '{"error": "tunnel"}',
                "lead_scout",
                3,
                morning,
            )
        )
        self.assertFalse(
            skill_is_due(
                "2026-11-15T12:00:00+00:00",
                "completed",
                '{"queries": [{"leads": [{"title": "A"}]}]}',
                "lead_scout",
                3,
                morning,
            )
        )

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
            self.assertFalse(any("icp_finder" in task["skills"] for task in tasks))
            set_setting(db_path, "icp_enabled", "1")
            set_setting(db_path, "icp_notes", "US, no CTO")
            set_setting(db_path, "lead_queries", "warehouse robots\nflorida cto")
            tasks = prepare_desk_tasks(
                [{"id": "task-003", "skills": ["lead_scout"], "interval_days": 3, "payload": {}}],
                db_path,
            )
            lead = next(task for task in tasks if "lead_scout" in task["skills"])
            self.assertEqual(lead["payload"]["queries"], ["warehouse robots", "florida cto"])
            self.assertTrue(any("icp_prospector" in task["skills"] for task in tasks))
            finder = next(task for task in tasks if "icp_finder" in task["skills"])
            self.assertEqual(finder["payload"]["notes"], "US, no CTO")

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

    def test_waiting_items_land_on_the_page_that_owns_them(self):
        from hey_eman_app import _page_of

        self.assertEqual(_page_of({"action_type": "icp_candidate", "priority": 1}), "companies")
        self.assertEqual(_page_of({"action_type": "mail_notice", "priority": 1}), "mail")
        self.assertEqual(_page_of({"action_type": "new_bill", "priority": 1}), "mail")
        self.assertEqual(_page_of({"action_type": "renewal_notice", "priority": 2}), "now")
        self.assertEqual(_page_of({"action_type": "role_candidate", "priority": 1}), "now")
        self.assertEqual(_page_of({"action_type": "linkedin_post_draft", "priority": 1}), "content")
        self.assertEqual(
            _page_of(
                {
                    "action_type": "outreach_draft",
                    "priority": 1,
                    "payload_json": '{"company": true}',
                }
            ),
            "companies",
        )

    def test_a_status_chip_opens_the_tab_that_holds_the_action(self):
        from streamlit.testing.v1 import AppTest

        root = str(Path(__file__).resolve().parents[1])
        script = f"""
import sys
sys.path.insert(0, {root!r})
import streamlit as st
from hey_eman_app import _open_from_chip

if st.button("1 need you", key="chip-decisions"):
    _open_from_chip("decisions")
    st.rerun()
if st.button("9 companies", key="chip-companies"):
    _open_from_chip("companies")
    st.rerun()
tabs = st.tabs(
    ["Ask Enaam", "Now", "Companies", "Mail", "Content", "Task log"],
    key="desk_tab",
    default="Ask Enaam",
    on_change="rerun",
)
st.write("tab:" + str(st.session_state.get("desk_tab")))
st.write("scroll:" + str(st.session_state.get("desk_scroll")))
st.write("now-open:" + str(bool(tabs[1].open)))
st.write("companies-open:" + str(bool(tabs[2].open)))
"""
        app = AppTest.from_string(script, default_timeout=20)
        app.run()
        need = next(button for button in app.button if button.label == "1 need you")
        need.click().run()
        text = "\n".join(item.value for item in app.markdown)
        self.assertIn("tab:Now", text)
        self.assertIn("scroll:decisions", text)
        self.assertIn("now-open:True", text)
        companies = next(button for button in app.button if button.label == "9 companies")
        companies.click().run()
        text = "\n".join(item.value for item in app.markdown)
        self.assertIn("tab:Companies", text)
        self.assertIn("scroll:companies", text)
        self.assertIn("companies-open:True", text)


if __name__ == "__main__":
    unittest.main()
