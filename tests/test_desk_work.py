import json
import sqlite3
import tempfile
import unittest
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

from desk_settings import calendar_enabled
from desk_settings import prepare_desk_tasks
from desk_settings import set_setting
from desk_work import add_commitment
from desk_work import approved_skill_briefings
from desk_work import block_commitment
from desk_work import cancel_commitment
from desk_work import choose_role
from desk_work import complete_commitment
from desk_work import decide_skill_request
from desk_work import is_single_role
from desk_work import ensure_desk_work
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import morning_focus
from desk_work import queue_single_roles
from desk_work import set_pursuit_date
from desk_work import submit_skill_request
from executive_summary import _extra_sections
from executive_summary import generate_executive_summary
from executive_summary import mobile_update
from manager import Manager
from schedule_sync import run_morning_skills
from skills.calendar_prep import CalendarPrepSkill
from skills.calendar_prep import upcoming_meetings
from skills.outreach_draft import OutreachDraftSkill


EMPIRICAL = {
    "title": "Fractional CTO (Remote - US or LATAM) - Empirical LLC",
    "url": "https://www.builtinla.com/job/empirical-fractional-cto/1",
    "snippet": "One company is hiring.",
}
INDEED = {
    "title": "Now Hiring: 500 Fractional Chief Technology Officer Jobs",
    "url": "https://www.indeed.com/q-fractional-chief-technology-officer-jobs.html",
    "snippet": "A board.",
}


class DeskWorkTests(unittest.TestCase):
    def test_single_employer_is_kept_and_a_job_board_is_not(self):
        self.assertTrue(is_single_role(EMPIRICAL["title"], EMPIRICAL["url"]))
        self.assertFalse(is_single_role(INDEED["title"], INDEED["url"]))
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            self.assertEqual(queue_single_roles([EMPIRICAL, INDEED], db_path), 1)
            import sqlite3

            titles = [
                row[0]
                for row in sqlite3.connect(db_path).execute(
                    "SELECT title FROM pending_actions WHERE action_type = 'role_candidate'"
                )
            ]
            self.assertEqual(titles, [EMPIRICAL["title"]])
            action_id = sqlite3.connect(db_path).execute(
                "SELECT action_id FROM pending_actions WHERE action_type = 'role_candidate'"
            ).fetchone()[0]
            self.assertEqual(choose_role(db_path, action_id, keep=True)["status"], "ok")
            self.assertEqual(list_pursuits(db_path)[0]["title"], EMPIRICAL["title"])

    def test_commitment_leaves_the_open_list_when_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            saved = add_commitment(db_path, "Send the proposal", "2026-11-20")
            self.assertEqual([row["title"] for row in list_commitments(db_path)], ["Send the proposal"])
            self.assertEqual(complete_commitment(db_path, saved["commitment_id"])["status"], "ok")
            self.assertEqual(list_commitments(db_path), [])

    def test_blocked_and_cancelled_stay_on_the_status_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            open_row = add_commitment(db_path, "Send the proposal", "2026-11-20")
            held = add_commitment(db_path, "Call the bank", "2026-11-19")
            dropped = add_commitment(db_path, "Skip the intro", "2026-11-18")
            self.assertEqual(
                sqlite3.connect(db_path).execute(
                    "SELECT status FROM commitments WHERE commitment_id = ?",
                    (open_row["commitment_id"],),
                ).fetchone()[0],
                "open",
            )
            columns = [
                row[1]
                for row in sqlite3.connect(db_path).execute("PRAGMA table_info(commitments)")
            ]
            self.assertEqual(
                columns,
                [
                    "commitment_id",
                    "title",
                    "due_on",
                    "status",
                    "created_at",
                    "updated_at",
                    "decision_id",
                ],
            )
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO commitments (
                        commitment_id, title, due_on, status, created_at, updated_at, decision_id
                    ) VALUES ('old-done', 'Old promise', '2026-11-01', 'done', 't', 't', '')
                    """
                )
            self.assertEqual(block_commitment(db_path, held["commitment_id"])["message"], "Marked blocked.")
            self.assertEqual(cancel_commitment(db_path, dropped["commitment_id"])["message"], "Marked cancelled.")
            self.assertEqual([row["title"] for row in list_commitments(db_path)], ["Send the proposal"])
            self.assertEqual(
                [(row["title"], row["status"]) for row in list_commitments(db_path, ("open", "blocked"))],
                [("Send the proposal", "open"), ("Call the bank", "blocked")],
            )
            self.assertEqual(
                sqlite3.connect(db_path).execute(
                    "SELECT status FROM commitments WHERE commitment_id = 'old-done'"
                ).fetchone()[0],
                "done",
            )
            self.assertEqual(
                block_commitment(db_path, "missing")["message"],
                "That commitment is not on the list.",
            )
            self.assertEqual(
                block_commitment(db_path, "old-done")["message"],
                "That commitment is already done.",
            )
            self.assertEqual(complete_commitment(db_path, held["commitment_id"])["message"], "Marked done.")
            self.assertEqual(
                cancel_commitment(db_path, dropped["commitment_id"])["message"],
                "That commitment is already cancelled.",
            )
            self.assertEqual(
                [(row["title"], row["status"]) for row in list_commitments(db_path, ("open", "blocked"))],
                [("Send the proposal", "open")],
            )
            stored = {
                row[0]: row[1]
                for row in sqlite3.connect(db_path).execute("SELECT title, status FROM commitments")
            }
            self.assertEqual(
                stored,
                {
                    "Send the proposal": "open",
                    "Call the bank": "done",
                    "Skip the intro": "cancelled",
                    "Old promise": "done",
                },
            )

    def test_now_marks_a_commitment_blocked_or_cancelled(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            root = str(Path(__file__).resolve().parents[1])
            first = add_commitment(db_path, "Send the proposal", "2026-11-19")
            second = add_commitment(db_path, "Call the bank", "2026-11-18")
            script = f"""
import sys
sys.path.insert(0, {root!r})
from desk_work import list_commitments
from hey_eman_app import _render_commitments

_render_commitments({db_path!r}, list_commitments({db_path!r}, ("open", "blocked")))
"""
            app = AppTest.from_string(script, default_timeout=20)
            app.run()
            self.assertEqual(app.exception, [])
            labels = [button.label for button in app.button]
            self.assertIn("Done", labels)
            self.assertIn("Blocked", labels)
            self.assertIn("Cancelled", labels)
            app.button(key=f"commit-blocked-{first['commitment_id']}").click().run()
            app.run()
            self.assertEqual(app.exception, [])
            text = "\n".join(item.value for item in app.markdown)
            self.assertIn("Send the proposal", text)
            self.assertIn("· blocked", text)
            self.assertEqual(
                sqlite3.connect(db_path).execute(
                    "SELECT status FROM commitments WHERE commitment_id = ?",
                    (first["commitment_id"],),
                ).fetchone()[0],
                "blocked",
            )
            app.button(key=f"commit-cancelled-{second['commitment_id']}").click().run()
            app.run()
            self.assertEqual(app.exception, [])
            text = "\n".join(item.value for item in app.markdown)
            self.assertNotIn("Call the bank", text)
            self.assertIn("· blocked", text)
            self.assertEqual(
                [button.label for button in app.button if button.label in {"Done", "Blocked", "Cancelled"}],
                ["Done", "Blocked", "Cancelled"],
            )
            self.assertEqual(
                sqlite3.connect(db_path).execute(
                    "SELECT status FROM commitments WHERE commitment_id = ?",
                    (second["commitment_id"],),
                ).fetchone()[0],
                "cancelled",
            )
            app.button(key=f"commit-done-{first['commitment_id']}").click().run()
            app.run()
            self.assertEqual(app.exception, [])
            text = "\n".join(item.value for item in app.markdown)
            self.assertNotIn("Send the proposal", text)
            self.assertEqual(
                sqlite3.connect(db_path).execute(
                    "SELECT status FROM commitments WHERE commitment_id = ?",
                    (first["commitment_id"],),
                ).fetchone()[0],
                "done",
            )

    def test_skill_request_shows_workflow_and_briefing_before_it_is_approved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            result = submit_skill_request(db_path, "new skill to remind me who I owe a reply")
            self.assertIn("### Workflow", result["message"])
            self.assertIn("### Briefing", result["message"])
            self.assertIn("does not send", result["message"])
            self.assertEqual(approved_skill_briefings(db_path), [])
            import sqlite3

            action_id = sqlite3.connect(db_path).execute(
                "SELECT action_id FROM pending_actions WHERE action_type = 'skill_request'"
            ).fetchone()[0]
            self.assertEqual(decide_skill_request(db_path, action_id, approve=True)["status"], "ok")
            self.assertEqual(len(approved_skill_briefings(db_path)), 1)

    def test_outreach_draft_is_not_sent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            result = OutreachDraftSkill().run(
                {"db_path": db_path, "payload": {"title": "Empirical LLC", "url": "https://empirical.example"}}
            )
            self.assertFalse(result["sent"])
            self.assertIn("Empirical LLC", result["draft"])
            import sqlite3

            payload = sqlite3.connect(db_path).execute(
                "SELECT payload_json FROM pending_actions WHERE action_type = 'outreach_draft'"
            ).fetchone()[0]
            self.assertIn('"send": false', payload)

    def test_calendar_stays_off_and_a_missing_feed_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            tasks = prepare_desk_tasks([{"id": "task-003", "skills": ["lead_scout"], "payload": {}}], db_path)
            self.assertFalse(calendar_enabled(db_path))
            self.assertFalse(any("calendar_prep" in task["skills"] for task in tasks))
            set_setting(db_path, "calendar_enabled", "1")
            tasks = prepare_desk_tasks([{"id": "task-003", "skills": ["lead_scout"], "payload": {}}], db_path)
            self.assertTrue(any("calendar_prep" in task["skills"] for task in tasks))
        result = CalendarPrepSkill().run({"payload": {}})
        self.assertEqual(result["meetings"], [])
        self.assertIn("error", result)
        ics = """
BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261120T150000Z
SUMMARY:Call with Northwind
END:VEVENT
BEGIN:VEVENT
DTSTART:20200101T150000Z
SUMMARY:Old call
END:VEVENT
END:VCALENDAR
"""
        meetings = upcoming_meetings(ics, now=datetime(2026, 11, 15, tzinfo=UTC))
        self.assertEqual([item["summary"] for item in meetings], ["Call with Northwind"])

    def test_brief_asks_for_a_linkedin_draft_when_the_week_has_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            text = "\n".join(_extra_sections(db_path, []))
            self.assertIn("No LinkedIn draft yet this week", text)


TODAY = date(2026, 11, 19)


class MorningFocusTests(unittest.TestCase):
    def _keep(self, db_path: str) -> str:
        Manager(db_path=db_path)
        queue_single_roles([EMPIRICAL], db_path)
        action_id = sqlite3.connect(db_path).execute(
            "SELECT action_id FROM pending_actions WHERE action_type = 'role_candidate'"
        ).fetchone()[0]
        choose_role(db_path, action_id, keep=True)
        return list_pursuits(db_path)[0]["pursuit_id"]

    def _bill(self, db_path: str, action_id: str, kind: str, title: str, due: str) -> None:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    created_at, created_by, status, priority
                ) VALUES (?, ?, ?, '', ?, ?, 'test', 'pending', 3)
                """,
                (
                    action_id,
                    kind,
                    title,
                    json.dumps({"vendor": title, "due_date": due}),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def test_an_old_pursuit_table_gains_a_date_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE pursuits (
                        pursuit_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        url TEXT NOT NULL DEFAULT '',
                        stage TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "INSERT INTO pursuits VALUES ('p1', 'Empirical', 'https://empirical.example', 'kept', 't', 't')"
                )
            ensure_desk_work(db_path)
            self.assertEqual(list_pursuits(db_path)[0]["next_on"], "")
            self.assertEqual(set_pursuit_date(db_path, "p1", "2026-11-19")["status"], "ok")
            self.assertEqual(set_pursuit_date(db_path, "p1", "Thursday")["status"], "error")

    def test_an_undated_role_pauses_research_and_a_date_names_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            pursuit_id = self._keep(db_path)
            waiting = morning_focus(db_path, TODAY)
            self.assertTrue(waiting["pause_research"])
            self.assertEqual(waiting["lines"], ["Set a date on a kept role."])
            set_pursuit_date(db_path, pursuit_id, "2026-11-19")
            due = morning_focus(db_path, TODAY)
            self.assertFalse(due["pause_research"])
            self.assertEqual(due["lines"], ["Follow up: Fractional CTO (Remote - US or LATAM) - Empirical LLC, due 2026-11-19."])
            set_pursuit_date(db_path, pursuit_id, "2026-11-25")
            later = morning_focus(db_path, TODAY)
            self.assertIn("Next follow-up:", later["lines"][0])
            self.assertIn("2026-11-25", later["lines"][0])

    def test_one_undated_role_pauses_even_when_another_is_dated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            ensure_desk_work(db_path)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO pursuits (
                        pursuit_id, title, url, stage, next_on, created_at, updated_at
                    ) VALUES
                        ('dated', 'Dated Co', 'https://dated.example', 'kept', '2026-11-19', 't', 't'),
                        ('open', 'Open Co', 'https://open.example', 'kept', '', 't', 't')
                    """
                )
            focus = morning_focus(db_path, TODAY)
            self.assertTrue(focus["pause_research"])
            self.assertEqual(focus["role_line"], "Set a date on a kept role.")

    def test_an_urgent_bill_leads_and_a_distant_bill_does_not(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            pursuit_id = self._keep(db_path)
            set_pursuit_date(db_path, pursuit_id, "2026-11-25")
            self._bill(db_path, "far", "new_bill", "Far Bill", "2026-12-10")
            quiet = morning_focus(db_path, TODAY)
            self.assertEqual(len(quiet["lines"]), 1)
            self.assertIn("Next follow-up:", quiet["lines"][0])
            self._bill(db_path, "due", "new_bill", "AT&T", "2026-11-19")
            self._bill(db_path, "late", "overdue_payment", "Insurance", "")
            loud = morning_focus(db_path, TODAY)
            self.assertTrue(loud["lines"][0].startswith("Pay or close:"))
            self.assertIn("1 other bill", loud["lines"][0])
            self.assertIn("Next follow-up:", loud["lines"][1])

    def test_a_waiting_role_pauses_and_an_empty_desk_still_searches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            self.assertFalse(morning_focus(db_path, TODAY)["pause_research"])
            self.assertEqual(morning_focus(db_path, TODAY)["role_line"], "No kept role yet.")
            queue_single_roles([EMPIRICAL], db_path)
            waiting = morning_focus(db_path, TODAY)
            self.assertTrue(waiting["pause_research"])
            self.assertEqual(waiting["role_line"], "Keep or skip the role waiting.")

    def test_the_brief_and_telegram_lead_with_today_and_hide_new_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            self._keep(db_path)
            report = generate_executive_summary(manager, _Silent(), now=datetime(2026, 11, 19, 8, 0))
            self.assertTrue(report.splitlines()[2].startswith("## Today"))
            self.assertIn("Set a date on a kept role.", report)
            self.assertIn("Research is waiting", report)
            self.assertNotIn("## Top Leads", report)
            phone = mobile_update(report)
            self.assertTrue(phone.splitlines()[2].startswith("Today"))
            self.assertIn("Set a date on a kept role.", phone)
            self.assertNotIn("Leads", phone)

    def test_morning_run_skips_search_until_the_role_has_a_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            pursuit_id = self._keep(db_path)
            manager.run_skill = lambda skill, task_id, payload: {"status": "ok"}
            tasks = [
                {"id": "mail", "skills": ["sifter"], "interval_days": 1, "payload": {}},
                {"id": "search", "skills": ["lead_scout", "cto_radar"], "interval_days": 1, "payload": {}},
                {"id": "companies", "skills": ["icp_finder", "icp_prospector"], "interval_days": 1, "payload": {}},
                {"id": "post", "skills": ["blogger"], "interval_days": 1, "payload": {}},
            ]
            moment = datetime(2026, 11, 19, 8, 0)
            paused = run_morning_skills(manager, tasks, now=moment)
            self.assertEqual(paused, ["mail:sifter", "post:blogger"])
            set_pursuit_date(db_path, pursuit_id, "2026-11-19")
            manager.run_skill = lambda skill, task_id, payload: {"status": "ok"}
            opened = run_morning_skills(manager, tasks, now=moment)
            self.assertIn("search:lead_scout", opened)
            self.assertIn("companies:icp_prospector", opened)

    def test_the_kept_role_form_saves_a_date(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            root = str(Path(__file__).resolve().parents[1])
            script = f"""
import sys
sys.path.insert(0, {root!r})
import sqlite3
from manager import Manager
from desk_work import choose_role, list_pursuits, queue_single_roles
from hey_eman_app import _render_pursuits

db = {db_path!r}
manager = Manager(db_path=db)
queue_single_roles([
    {{
        "title": "Fractional CTO - Empirical LLC",
        "url": "https://empirical.example/job",
        "snippet": "One company is hiring.",
    }}
], db)
action_id = sqlite3.connect(db).execute(
    "SELECT action_id FROM pending_actions WHERE action_type = 'role_candidate'"
).fetchone()[0]
choose_role(db, action_id, keep=True)
_render_pursuits(manager, list_pursuits(db))
"""
            app = AppTest.from_string(script, default_timeout=20)
            app.run()
            self.assertEqual(app.text_input[0].value, "")
            app.text_input[0].set_value("2026-11-19")
            save = next(button for button in app.button if button.label == "Save date")
            save.click().run()
            self.assertEqual(list_pursuits(db_path)[0]["next_on"], "2026-11-19")
            self.assertFalse(morning_focus(db_path, TODAY)["pause_research"])

    def test_a_due_commitment_and_a_still_conditional_decision_join_the_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            add_commitment(db_path, "Call them later", "2026-11-25")
            add_commitment(db_path, "Send the note", "")
            quiet = morning_focus(db_path, TODAY)
            self.assertEqual(quiet["lines"], ["No kept role yet."])
            add_commitment(db_path, "Send the note", "2026-11-18")
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE strategic_decisions (
                        decision_id TEXT PRIMARY KEY,
                        subject TEXT NOT NULL,
                        subject_key TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO strategic_decisions
                        (decision_id, subject, subject_key, decision, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        ("old", "Northwind", "northwind", "CONDITIONAL GO", "2026-11-01"),
                        ("new", "Northwind", "northwind", "NO-GO", "2026-11-02"),
                        ("open", "Story Protocol", "story", "CONDITIONAL GO", "2026-11-03"),
                    ],
                )
            focus = morning_focus(db_path, TODAY)
            self.assertIn("Commitment overdue: Send the note, due 2026-11-18.", focus["lines"])
            self.assertIn("Conditional decision: Story Protocol.", focus["lines"])
            self.assertNotIn("Northwind", " ".join(focus["lines"]))
            self.assertNotIn("Call them later", " ".join(focus["lines"]))

    def test_a_blocked_due_commitment_is_named_on_the_morning_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            bank = add_commitment(db_path, "Call the bank", "2026-11-19")
            later = add_commitment(db_path, "File the form", "2026-11-25")
            blank = add_commitment(db_path, "Think about it", "")
            self.assertEqual(block_commitment(db_path, bank["commitment_id"])["status"], "ok")
            self.assertEqual(block_commitment(db_path, later["commitment_id"])["status"], "ok")
            self.assertEqual(block_commitment(db_path, blank["commitment_id"])["status"], "ok")
            alone = morning_focus(db_path, TODAY)
            self.assertEqual(
                alone["lines"],
                [
                    "No kept role yet.",
                    "Blocked commitment due: Call the bank, due 2026-11-19.",
                ],
            )
            send = add_commitment(db_path, "Send the note", "2026-11-18")
            memo = add_commitment(db_path, "Write the memo", "2026-11-19")
            chase = add_commitment(db_path, "Chase the invoice", "2026-11-18")
            self.assertEqual(block_commitment(db_path, chase["commitment_id"])["status"], "ok")
            both = morning_focus(db_path, TODAY)
            self.assertEqual(
                both["lines"],
                [
                    "No kept role yet.",
                    "Commitment overdue: Send the note, due 2026-11-18. 1 other commitment is also due.",
                    "Blocked commitment overdue: Chase the invoice, due 2026-11-18. "
                    "1 other blocked commitment is also due.",
                ],
            )
            self.assertNotIn("File the form", " ".join(both["lines"]))
            self.assertNotIn("Think about it", " ".join(both["lines"]))
            self.assertEqual(cancel_commitment(db_path, bank["commitment_id"])["status"], "ok")
            self.assertEqual(cancel_commitment(db_path, chase["commitment_id"])["status"], "ok")
            cleared = morning_focus(db_path, TODAY)
            self.assertEqual(
                cleared["lines"],
                [
                    "No kept role yet.",
                    "Commitment overdue: Send the note, due 2026-11-18. 1 other commitment is also due.",
                ],
            )
            self.assertEqual(complete_commitment(db_path, send["commitment_id"])["status"], "ok")
            self.assertEqual(complete_commitment(db_path, memo["commitment_id"])["status"], "ok")
            self.assertEqual(morning_focus(db_path, TODAY)["lines"], ["No kept role yet."])


class _Silent:
    def send(self, content: str) -> str:
        return "ok"
