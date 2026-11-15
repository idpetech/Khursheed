import tempfile
import unittest
from datetime import UTC
from datetime import datetime
from pathlib import Path

from desk_settings import calendar_enabled
from desk_settings import prepare_desk_tasks
from desk_settings import set_setting
from desk_work import add_commitment
from desk_work import approved_skill_briefings
from desk_work import choose_role
from desk_work import complete_commitment
from desk_work import decide_skill_request
from desk_work import is_single_role
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import queue_single_roles
from desk_work import submit_skill_request
from executive_summary import _extra_sections
from manager import Manager
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
