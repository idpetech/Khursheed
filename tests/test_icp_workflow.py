"""One company can be qualified, drafted, and approved without being contacted."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from icp_workflow import advance_icp
from icp_workflow import decide_icp_draft
from icp_workflow import get_workflow
from manager import Manager
from schedule_sync import run_morning_skills
from skills.base import Skill
from skills.icp_prospector import IcpProspectorSkill
from skills.outreach_draft import OutreachDraftSkill


COMPANY = {
    "company_name": "Northwind",
    "website": "https://northwind.example",
    "industry": "saas",
    "employee_count": 30,
    "funding_stage": "seed",
    "has_cto": "unknown",
    "acquired": "no",
}


class _Prospector(Skill):
    name = "icp_prospector"

    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls = 0

    def run(self, task: dict) -> dict:
        self.calls += 1
        return self.result


def _fit() -> dict:
    return {
        "top_companies": [{"name": "Northwind", "rationale": "No CTO and hiring"}],
        "rejected": [],
    }


def _reject() -> dict:
    return {
        "top_companies": [],
        "rejected": [{"name": "Northwind", "reason": "Already has a CTO"}],
    }


def _desk(result: dict) -> tuple[str, Manager, _Prospector]:
    manager = Manager(db_path=result.pop("db_path"))
    prospector = _Prospector(result)
    manager.register(prospector)
    manager.register(OutreachDraftSkill())
    return str(manager._db_path), manager, prospector


class IcpWorkflowTests(unittest.TestCase):
    def test_a_fit_is_drafted_once_and_then_waits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_fit()})
            first = advance_icp(db_path, COMPANY, manager)
            second = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(first["step"], "awaiting_approval")
            self.assertFalse(first["sent"])
            self.assertIn("has not been sent", first["message"])
            self.assertEqual(second["step"], "awaiting_approval")
            self.assertEqual(prospector.calls, 1)
            notes = _notes(db_path)
            self.assertEqual(len(notes), 1)
            payload = json.loads(notes[0]["payload_json"])
            self.assertTrue(payload["company"])
            self.assertFalse(payload["send"])
            self.assertIn("Northwind", payload["body"])

    def test_a_rejected_company_stops_before_a_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_reject()})
            result = advance_icp(db_path, COMPANY, manager)
            again = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(result["step"], "not_a_fit")
            self.assertIn("Already has a CTO", result["message"])
            self.assertFalse(result["sent"])
            self.assertEqual(again["step"], "not_a_fit")
            self.assertEqual(prospector.calls, 1)
            self.assertEqual(_notes(db_path), [])

    def test_approval_records_consent_and_does_not_send(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, _prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_fit()})
            advance_icp(db_path, COMPANY, manager)
            action_id = get_workflow(db_path, "Northwind")["action_id"]
            approved = decide_icp_draft(db_path, action_id, approve=True)
            self.assertEqual(approved["step"], "approved")
            self.assertFalse(approved["sent"])
            self.assertIn("not sent", approved["message"])
            self.assertEqual(_action_status(db_path, action_id), "acknowledged")
            self.assertNotIn("executed", _action_status(db_path, action_id))

    def test_not_now_leaves_the_note_unsent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, _prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_fit()})
            advance_icp(db_path, COMPANY, manager)
            action_id = get_workflow(db_path, "Northwind")["action_id"]
            declined = decide_icp_draft(db_path, action_id, approve=False)
            self.assertEqual(declined["step"], "declined")
            self.assertFalse(declined["sent"])
            self.assertEqual(_action_status(db_path, action_id), "rejected")

    def test_morning_finishes_a_draft_and_skips_research_and_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            prospector = _Prospector(_fit())
            manager.register(prospector)
            manager.register(OutreachDraftSkill())
            _insert(
                db_path,
                "Northwind",
                "draft",
                json.dumps(_fit()),
            )
            _insert(db_path, "Waiting Co", "qualify", "")
            _insert(db_path, "Held Co", "awaiting_approval", json.dumps(_fit()))
            run_morning_skills(manager, [], now=datetime(2026, 11, 20, 8, 0))
            self.assertEqual(prospector.calls, 0)
            self.assertEqual(get_workflow(db_path, "Northwind")["step"], "awaiting_approval")
            self.assertEqual(get_workflow(db_path, "Waiting Co")["step"], "qualify")
            self.assertEqual(get_workflow(db_path, "Held Co")["step"], "awaiting_approval")
            self.assertEqual(len(_notes(db_path)), 1)

    def test_one_company_does_not_scan_the_seed(self):
        skill = IcpProspectorSkill()

        def seed(_db):
            raise AssertionError("seed scanned")

        skill._seed_rows = seed
        skill._enrich_companies = lambda companies: [{**companies[0], "has_cto": "no"}]
        skill._rank_companies = lambda companies, top_n: {
            "top_companies": companies[:top_n],
            "rejected": [],
        }
        result = skill.run({"payload": {"company": COMPANY}, "db_path": "unused"})
        self.assertEqual(result["top_companies"][0]["company_name"], "Northwind")
        self.assertEqual(result["top_companies"][0]["has_cto"], "no")

    def test_the_batch_run_still_reads_the_seed(self):
        skill = IcpProspectorSkill()
        seen = {"seed": False}

        def seed(_db):
            seen["seed"] = True
            return [
                {
                    "company_name": "Other",
                    "website": "",
                    "industry": "nope",
                    "employee_count": "1",
                    "funding_stage": "pre",
                    "has_cto": "yes",
                    "acquired": "yes",
                    "hiring_signals_url": "",
                }
            ]

        skill._seed_rows = seed
        result = skill.run({"payload": {}, "db_path": "unused"})
        self.assertTrue(seen["seed"])
        self.assertEqual(result["top_companies"], [])

    def test_the_qualify_button_starts_the_company(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            root = str(Path(__file__).resolve().parents[1])
            script = f"""
import sys
sys.path.insert(0, {root!r})
import sqlite3
import streamlit as st
from manager import Manager
from hey_eman_app import _render_company_draft, _render_icp_candidate
from icp_workflow import advance_icp, get_workflow
from priority_inbox import emit_priority_action
from skills.base import Skill
from skills.outreach_draft import OutreachDraftSkill

class Prospector(Skill):
    name = "icp_prospector"
    def run(self, task):
        return {{"top_companies": [{{"name": "Northwind", "rationale": "No CTO"}}], "rejected": []}}

db = {db_path!r}
manager = Manager(db_path=db)
manager.register(Prospector())
manager.register(OutreachDraftSkill())
action_id = emit_priority_action(
    kind="icp_candidate",
    title="Northwind",
    description="Matches the ICP.",
    payload={{"company_name": "Northwind", "website": "https://northwind.example", "industry": "saas"}},
    priority=1,
    source_key="icp-candidate:northwind",
    db_path=db,
)
action = sqlite3.connect(db).execute(
    "SELECT action_id, action_type, title, description, payload_json, priority FROM pending_actions WHERE action_id = ?",
    (action_id,),
).fetchone()
action = {{
    "action_id": action[0],
    "action_type": action[1],
    "title": action[2],
    "description": action[3],
    "payload_json": action[4],
    "priority": action[5],
}}
_render_icp_candidate(manager, action)
if st.session_state.get("last_ack"):
    st.write(st.session_state.last_ack)
row = get_workflow(db, "Northwind")
if row and row["action_id"]:
    draft = sqlite3.connect(db).execute(
        "SELECT action_id, title, description, payload_json FROM pending_actions WHERE action_id = ?",
        (row["action_id"],),
    ).fetchone()
    _render_company_draft(db, {{
        "action_id": draft[0],
        "title": draft[1],
        "description": draft[2],
        "payload_json": draft[3],
    }}, __import__("json").loads(draft[3]))
"""
            app = AppTest.from_string(script, default_timeout=20)
            app.run()
            qualify = next(button for button in app.button if button.label == "Qualify")
            qualify.click().run()
            text = "\n".join(item.value for item in app.markdown)
            self.assertIn("has not been sent", text)
            approve = next(button for button in app.button if button.label == "Approve")
            self.assertIsNotNone(approve)
            later = next(button for button in app.button if button.label == "Not now")
            later.click().run()
            self.assertEqual(get_workflow(db_path, "Northwind")["step"], "declined")

    def test_a_role_note_still_requires_a_kept_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            result = OutreachDraftSkill().run({"payload": {}, "db_path": db_path})
            self.assertIn("error", result)
            self.assertEqual(result["draft"], "")


def _notes(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM pending_actions WHERE action_type = 'outreach_draft'"
        ).fetchall()
    finally:
        conn.close()


def _action_status(db_path: str, action_id: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM pending_actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0]


def _insert(db_path: str, name: str, step: str, findings: str) -> None:
    from icp_workflow import company_key
    from icp_workflow import ensure_workflow

    ensure_workflow(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workflow_runs (
                company_key, company_name, website, step, findings_json, updated_at
            ) VALUES (?, ?, '', ?, ?, '2026-11-20T00:00:00+00:00')
            """,
            (company_key(name), name, step, findings),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
