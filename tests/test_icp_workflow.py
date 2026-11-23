"""One company can be qualified, drafted, and approved without being contacted."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from icp_workflow import advance_icp
from icp_workflow import decide_icp_draft
from icp_workflow import get_workflow
from manager import Manager
from schedule_sync import run_morning_skills
from skills.base import Skill
from skills.icp_prospector import IcpProspectorSkill
from skills.icp_prospector import _ranking_prompt
from skills.icp_prospector import _states_acquired
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

    def test_a_failed_ranking_writes_no_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk(
                {
                    "db_path": str(Path(tmpdir) / "t.db"),
                    "error": "The model returned no ranking.",
                    "top_companies": [],
                    "rejected": [],
                }
            )
            result = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(result["status"], "error")
            self.assertIn("no ranking", result["message"])
            self.assertEqual(prospector.calls, 1)
            self.assertEqual(_notes(db_path), [])
            self.assertEqual(get_workflow(db_path, "Northwind")["step"], "qualify")

    def test_a_checklist_score_is_not_a_fit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, _prospector = _desk(
                {
                    "db_path": str(Path(tmpdir) / "t.db"),
                    "top_companies": [
                        {
                            "name": "Northwind",
                            "rationale": "llm_unavailable - scored using heuristic",
                            "score": 0,
                        }
                    ],
                    "rejected": [],
                }
            )
            result = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(result["status"], "error")
            self.assertIn("no note", result["message"])
            self.assertEqual(_notes(db_path), [])
            self.assertEqual(get_workflow(db_path, "Northwind")["step"], "qualify")

    def test_an_empty_model_reply_is_retried_and_then_reported(self):
        skill = IcpProspectorSkill()
        bodies = iter(["", "   ", "not json"])

        class _Message:
            def __init__(self, content: str) -> None:
                self.content = content

        class _Choice:
            def __init__(self, content: str) -> None:
                self.message = _Message(content)

        class _Response:
            def __init__(self, content: str) -> None:
                self.choices = [_Choice(content)]

        class _Completions:
            def create(self, **_kwargs):
                return _Response(next(bodies))

        class _Chat:
            completions = _Completions()

        class _Client:
            def __init__(self, api_key: str | None = None) -> None:
                self.chat = _Chat()

        company = {
            "company_name": "FieldFactors",
            "industry": "climate",
            "employee_count": 0,
            "funding_stage": "seed",
            "has_cto": "likely",
            "acquired": "likely",
            "is_hiring_ai": "unknown",
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            with patch("openai.OpenAI", _Client):
                result = skill._rank_companies([company], 1)
        self.assertEqual(result["top_companies"], [])
        self.assertIn("no ranking", result["error"])

    def test_an_acquisition_word_is_not_proof_the_company_was_bought(self):
        funding = "OneKiraana raises a seed round. Customer acquisition is the hard part."
        bought = "OneKiraana was acquired by Meesho in a 2026 deal."
        self.assertFalse(_states_acquired("OneKiraana", funding))
        self.assertTrue(_states_acquired("OneKiraana", bought))

    def test_a_named_purpose_is_what_gets_qualified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk(
                {"db_path": str(Path(tmpdir) / "t.db"), **_fit()}
            )
            result = advance_icp(db_path, COMPANY, manager, purpose="a distribution partner")
            self.assertIn("Qualified as a distribution partner", result["message"])
            body = json.loads(_notes(db_path)[0]["payload_json"])["body"]
            self.assertIn("distribution partner", body)
            self.assertNotIn("fractional CTO", body)
            self.assertEqual(prospector.calls, 1)
            prompt = _ranking_prompt([{"name": "OneKiraana"}], 1, "a distribution partner")
            self.assertIn("a distribution partner", prompt)
            self.assertNotIn("FRACTIONAL CTO", prompt)
            cto_prompt = _ranking_prompt([{"name": "OneKiraana"}], 1, "CTO opportunity")
            self.assertIn("FRACTIONAL CTO", cto_prompt)

    def test_a_new_purpose_qualifies_a_rejected_company_again(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk(
                {"db_path": str(Path(tmpdir) / "t.db"), **_reject()}
            )
            first = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(first["step"], "not_a_fit")
            prospector.result = _fit()
            second = advance_icp(db_path, COMPANY, manager, purpose="a distribution partner")
            self.assertEqual(prospector.calls, 2)
            self.assertEqual(second["step"], "awaiting_approval")
            self.assertIn("distribution partner", second["message"])

    def test_a_rejected_company_stops_before_a_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_reject()})
            result = advance_icp(db_path, COMPANY, manager)
            again = advance_icp(db_path, COMPANY, manager)
            self.assertEqual(result["step"], "not_a_fit")
            self.assertIn("Already has a CTO", result["message"])
            self.assertIn("not a fit for CTO opportunity", result["message"])
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

    def test_search_again_asks_for_new_companies(self):
        from icp_workflow import refresh_icp_search

        class Finder(Skill):
            name = "icp_finder"

            def __init__(self) -> None:
                self.calls = 0

            def run(self, task: dict) -> dict:
                self.calls += 1
                self.last = task.get("payload")
                return {"candidates": [{"company_name": "New Co"}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            finder = Finder()
            manager.register(finder)
            found = refresh_icp_search(db_path, manager)
            empty_finder = Finder()
            empty_finder.run = lambda task: {"candidates": []}
            manager.register(empty_finder)
            # The first registration wins. Call the function with a fresh manager.
            again = Manager(db_path=db_path)
            again.register(empty_finder)
            missed = refresh_icp_search(db_path, again)
            failed_manager = Manager(db_path=db_path)

            class Failed(Skill):
                name = "icp_finder"

                def run(self, task: dict) -> dict:
                    return {"candidates": [], "error": "No search results."}

            failed_manager.register(Failed())
            failed = refresh_icp_search(db_path, failed_manager)
            self.assertEqual(found["found"], 1)
            self.assertIn("1 new company", found["message"])
            self.assertEqual(finder.calls, 1)
            self.assertIn("No new companies", missed["message"])
            self.assertIn("No search results", failed["message"])

    def test_an_approved_note_stays_readable_and_can_be_tracked_once(self):
        from desk_work import list_commitments
        from icp_workflow import list_company_notes
        from icp_workflow import track_company_note

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, manager, _prospector = _desk({"db_path": str(Path(tmpdir) / "t.db"), **_fit()})
            advance_icp(db_path, COMPANY, manager)
            action_id = get_workflow(db_path, "Northwind")["action_id"]
            decide_icp_draft(db_path, action_id, approve=True)
            notes = list_company_notes(db_path)
            self.assertEqual([note["company_name"] for note in notes], ["Northwind"])
            self.assertEqual(notes[0]["step"], "approved")
            self.assertTrue(notes[0]["draft"])
            first = track_company_note(db_path, "Northwind")
            second = track_company_note(db_path, "Northwind")
            self.assertFalse(first["sent"])
            self.assertIn("Commitments", first["message"])
            self.assertTrue(second.get("duplicate"))
            self.assertEqual(len(list_commitments(db_path)), 1)

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
        skill._rank_companies = lambda companies, top_n, purpose="CTO opportunity": {
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
            field = next(item for item in app.text_input if item.label == "Qualify for")
            self.assertEqual(field.value, "CTO opportunity")
            qualify = next(button for button in app.button if button.label == "Qualify")
            qualify.click().run()
            text = "\n".join(item.value for item in app.markdown)
            self.assertIn("has not been sent", text)
            approve = next(button for button in app.button if button.label == "Approve")
            self.assertIsNotNone(approve)
            later = next(button for button in app.button if button.label == "Not now")
            later.click().run()
            self.assertEqual(get_workflow(db_path, "Northwind")["step"], "declined")

    def test_companies_page_shows_search_and_the_kept_note(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            root = str(Path(__file__).resolve().parents[1])
            script = f"""
import sys
sys.path.insert(0, {root!r})
import sqlite3
from manager import Manager
from hey_eman_app import _render_companies
from icp_workflow import company_key, ensure_workflow

db = {db_path!r}
ensure_workflow(db)
conn = sqlite3.connect(db)
conn.execute(
    '''
    INSERT OR REPLACE INTO workflow_runs (
        company_key, company_name, website, step, findings_json, draft, updated_at
    ) VALUES (?, 'Northwind', 'https://northwind.example', 'approved', '', ?, '2026-11-21T00:00:00+00:00')
    ''',
    (company_key('Northwind'), 'Hello from the approved note.'),
)
conn.commit()
conn.close()
_render_companies(Manager(db_path=db))
"""
            app = AppTest.from_string(script, default_timeout=20)
            app.run()
            self.assertEqual(app.exception, [])
            labels = [button.label for button in app.button]
            self.assertIn("Search again", labels)
            self.assertIn("Track follow-up", labels)
            titles = [item.label for item in app.expander]
            self.assertTrue(any("Approved. Not sent." in title for title in titles))
            text = "\n".join(item.value for item in app.markdown)
            next(button for button in app.button if button.label == "Track follow-up").click().run()
            from desk_work import list_commitments

            titles = [row["title"] for row in list_commitments(db_path)]
            self.assertEqual(titles, ["Follow up on the approved note for Northwind"])

    def test_a_role_note_still_requires_a_kept_role(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            result = OutreachDraftSkill().run({"payload": {}, "db_path": db_path})
            self.assertIn("error", result)
            self.assertEqual(result["draft"], "")

    def test_chat_qualify_uses_the_stored_company_and_names_no_others(self):
        from hey_eman_app import _answer
        from llm_agent import HeyEmanAgent
        from priority_inbox import emit_priority_action

        class Recording(_Prospector):
            def __init__(self, result: dict) -> None:
                super().__init__(result)
                self.payloads: list[dict] = []

            def run(self, task: dict) -> dict:
                self.payloads.append(task.get("payload") or {})
                return super().run(task)

        class Agent:
            def __init__(self) -> None:
                self.queries: list[tuple[str, str]] = []

            def respond(self, query: str, session_id: str = "hey-eman") -> str:
                self.queries.append((query, session_id))
                return "model reply"

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            prospector = Recording(_reject())
            manager.register(prospector)
            manager.register(OutreachDraftSkill())
            note = "Stored FieldFactors note."
            _insert(
                db_path,
                "FieldFactors",
                "declined",
                json.dumps({"purpose": "CTO opportunity", "top_companies": [{"name": "FieldFactors"}]}),
                note,
            )
            before = get_workflow(db_path, "FieldFactors")
            agent = Agent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                stored = _answer("Can you qualify FieldFactors", manager, agent)
                typo = _answer("Qualify FeildFactors", manager, agent)
                emit_priority_action(
                    kind="icp_candidate",
                    title="Northwind",
                    description="Suggested for review.",
                    payload={
                        "company_name": "Northwind",
                        "website": "https://northwind.example",
                        "industry": "saas",
                        "employee_count": 30,
                        "funding_stage": "seed",
                    },
                    priority=1,
                    source_key="icp-candidate:northwind",
                    db_path=db_path,
                )
                reviewed = _answer("qualify Northwind", manager, agent)
                unknown = _answer("qualify Nobody Inc", manager, agent)
                search = _answer("Search new companies as ICP", manager, agent)
            expected = "Left the note for FieldFactors. Nothing was sent.\n\n" + note
            self.assertEqual(agent.queries, [
                ("Search new companies as ICP", "hey-eman"),
            ])
            self.assertEqual(stored, expected)
            self.assertEqual(typo, expected)
            self.assertNotIn("FeildFactors", typo)
            self.assertIsNone(get_workflow(db_path, "FeildFactors"))
            for blocked in ("Fintechly", "Acme", "EduSpark", "Industry Not Specified", "Relevant Prospects"):
                self.assertNotIn(blocked, stored)
                self.assertNotIn(blocked, typo)
                self.assertNotIn(blocked, reviewed)
                self.assertNotIn(blocked, unknown)
            after = get_workflow(db_path, "FieldFactors")
            self.assertEqual(after["step"], "declined")
            self.assertEqual(after["updated_at"], before["updated_at"])
            self.assertEqual(after["findings_json"], before["findings_json"])
            self.assertEqual(after["draft"], before["draft"])
            self.assertEqual(prospector.calls, 1)
            self.assertEqual(prospector.payloads[0]["company"]["company_name"], "Northwind")
            self.assertNotIn("seed_path", prospector.payloads[0])
            self.assertIn("Northwind", reviewed)
            self.assertNotIn("FieldFactors", reviewed)
            self.assertNotIn("The note text is not stored", reviewed)
            self.assertEqual(unknown, "No single company on the desk matches. Nothing was sent.")
            self.assertEqual(search, "model reply")
            prompt = HeyEmanAgent(manager)._system_prompt()
            self.assertIn(
                "name only companies that result lists and do not add a company the tool did not return",
                prompt,
            )

    def test_qualify_reads_a_saved_note_and_does_not_guess(self):
        from hey_eman_app import _answer
        from icp_workflow import qualify_known_company

        class Agent:
            def respond(self, query: str, session_id: str = "hey-eman") -> str:
                raise AssertionError(query)

        class Boom(Skill):
            name = "icp_prospector"

            def run(self, task: dict) -> dict:
                raise AssertionError("prospector ran")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(Boom())
            _insert(db_path, "Plain Co", "declined", "{}")
            _insert(
                db_path,
                "Kept Co",
                "approved",
                json.dumps({"purpose": "CTO opportunity"}),
                "Kept note text.",
            )
            _insert(
                db_path,
                "Open Co",
                "awaiting_approval",
                json.dumps({"purpose": "CTO opportunity"}),
                "Open note text.",
            )
            _insert(
                db_path,
                "Skip Co",
                "not_a_fit",
                json.dumps(
                    {
                        "purpose": "CTO opportunity",
                        "rejected": [{"name": "Skip Co", "reason": "No strong fit."}],
                    }
                ),
            )
            _insert(db_path, "Longname Alpha", "declined", "{}", "alpha note")
            _insert(db_path, "Longname Alphas", "declined", "{}", "alphas note")
            before = {
                name: get_workflow(db_path, name)["updated_at"]
                for name in ("Plain Co", "Kept Co", "Open Co", "Skip Co", "Longname Alpha", "Longname Alphas")
            }
            agent = Agent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                empty = _answer("qualify Plain Co", manager, agent)
                kept = qualify_known_company(db_path, "qualify Kept Co", manager)
                waiting = qualify_known_company(db_path, "qualify Open Co", manager)
                skipped = qualify_known_company(db_path, "qualify Skip Co", manager)
                ambiguous = _answer("qualify Longname Alphaz", manager, agent)
            self.assertEqual(
                empty,
                "Left the note for Plain Co. Nothing was sent.\n\nThe note text is not stored.",
            )
            self.assertEqual(
                kept,
                "Approved the note for Kept Co. It was not sent. "
                "It stays on Companies under Kept notes.\n\nKept note text.",
            )
            self.assertEqual(
                waiting,
                "A note for Open Co is in Companies. Qualified as CTO opportunity. "
                "It has not been sent.\n\nOpen note text.",
            )
            self.assertEqual(skipped, "Skip Co is not a fit for CTO opportunity. No strong fit.")
            self.assertNotIn("The note text is not stored", skipped)
            self.assertEqual(ambiguous, "No single company on the desk matches. Nothing was sent.")
            for blocked in ("Fintechly", "Acme", "EduSpark", "Longname", "alpha note", "alphas note"):
                self.assertNotIn(blocked, ambiguous)
            for name, updated_at in before.items():
                self.assertEqual(get_workflow(db_path, name)["updated_at"], updated_at)

    def test_a_different_purpose_does_not_replay_the_declined_note(self):
        from desk_work import outreach_body
        from hey_eman_app import _answer
        from priority_inbox import emit_priority_action

        class Agent:
            def __init__(self) -> None:
                self.queries: list[tuple[str, str]] = []

            def respond(self, query: str, session_id: str = "hey-eman") -> str:
                self.queries.append((query, session_id))
                return "model reply"

        class Boom(Skill):
            name = "icp_prospector"

            def run(self, task: dict) -> dict:
                raise AssertionError("prospector ran")

        class DraftBoom(Skill):
            name = "outreach_draft"

            def run(self, task: dict) -> dict:
                raise AssertionError("draft ran")

        note = outreach_body("FieldFactors", "fieldfactors.com")
        findings = json.dumps(
            {
                "purpose": "CTO opportunity",
                "top_companies": [{"name": "FieldFactors", "rationale": "No CTO and hiring"}],
                "rejected": [],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(Boom())
            manager.register(DraftBoom())
            _insert(db_path, "FieldFactors", "declined", findings, note)
            action_id = emit_priority_action(
                kind="outreach_draft",
                title="Note for FieldFactors",
                description="Draft only. Approving it does not send the note.",
                payload={"title": "FieldFactors", "body": note, "send": False, "company": True},
                priority=1,
                source_key="icp-outreach:fieldfactors",
                db_path=db_path,
            )
            before = get_workflow(db_path, "FieldFactors")
            actions_before = _action_rows(db_path)
            agent = Agent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                repeat = _answer("Qualify FieldFactors", manager, agent)
                same = _answer("Qualify FieldFactors for CTO opportunity", manager, agent)
                cased = _answer("Qualify FieldFactors for  cto   opportunity", manager, agent)
                fractional = _answer("Qualify FieldFactors for fractional CTO", manager, agent)
                hyphen = _answer("Qualify FieldFactors for Fractional-CTO", manager, agent)
                audit = _answer("Qualify FieldFactors for AI audit", manager, agent)
            stored = "Left the note for FieldFactors. Nothing was sent.\n\n" + note
            self.assertEqual(repeat, stored)
            self.assertEqual(same, stored)
            self.assertEqual(cased, stored)
            self.assertEqual(fractional, stored)
            self.assertEqual(hyphen, stored)
            self.assertEqual(
                audit,
                "FieldFactors already has a note for CTO opportunity. "
                "Qualify it for AI audit? Reply yes to run that. "
                "The saved note stays. Nothing will be sent.",
            )
            self.assertNotIn(note, audit)
            self.assertNotIn("fractional CTO", audit)
            self.assertNotIn("fieldfactors.com", audit)
            for blocked in ("Fintechly", "Acme", "EduSpark", "model reply"):
                self.assertNotIn(blocked, audit)
                self.assertNotIn(blocked, repeat)
            self.assertEqual(agent.queries, [])
            after = get_workflow(db_path, "FieldFactors")
            self.assertEqual(after["step"], "declined")
            self.assertEqual(after["draft"], before["draft"])
            self.assertEqual(after["findings_json"], before["findings_json"])
            self.assertEqual(after["updated_at"], before["updated_at"])
            self.assertEqual(after["action_id"], before["action_id"])
            self.assertEqual(_action_rows(db_path), actions_before)
            self.assertEqual(actions_before[0]["action_id"], action_id)
            self.assertEqual(actions_before[0]["status"], "pending")


ASK = (
    "FieldFactors already has a note for CTO opportunity. "
    "Qualify it for AI audit? Reply yes to run that. "
    "The saved note stays. Nothing will be sent."
)
OLD_NOTE = "CTO note that must stay recoverable."
BLOCKED = ("Fintechly", "Acme Labs", "EduSpark")


class _FakeManager:
    """Records skill calls and returns a ranking for that one company."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self.calls: list[dict] = []

    def run_skill(self, skill_name: str, task_id: str, payload: dict) -> dict:
        self.calls.append(
            {"skill": skill_name, "task_id": task_id, "payload": dict(payload)}
        )
        if skill_name == "icp_prospector":
            name = str((payload.get("company") or {}).get("company_name") or "")
            return {
                "top_companies": [{"name": name, "rationale": "Fits an AI audit"}],
                "rejected": [],
            }
        if skill_name == "outreach_draft":
            name = str(payload.get("company_name") or "the company")
            return {
                "draft": f"AI audit note for {name}.",
                "action_id": "audit-action",
                "sent": False,
            }
        raise AssertionError(skill_name)


class _QuietAgent:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    def respond(self, query: str, session_id: str = "hey-eman") -> str:
        self.queries.append((query, session_id))
        return "model reply"


def _prepare_fieldfactors(db_path: str) -> None:
    Manager(db_path=db_path).close()
    _insert(
        db_path,
        "FieldFactors",
        "declined",
        json.dumps(
            {
                "purpose": "CTO opportunity",
                "top_companies": [{"name": "FieldFactors", "rationale": "No CTO and hiring"}],
                "rejected": [],
            }
        ),
        OLD_NOTE,
    )


class QualifyConfirmationTests(unittest.TestCase):
    def test_yes_no_and_other_words_are_exact(self):
        from icp_workflow import _confirmation_choice

        for word in ("yes", "yes please", "y", "Yes.", "YES", "yes, please"):
            self.assertEqual(_confirmation_choice(word), "yes", word)
        self.assertEqual(_confirmation_choice("no"), "no")
        self.assertEqual(_confirmation_choice("No."), "no")
        self.assertIsNone(_confirmation_choice("yes now"))
        self.assertIsNone(_confirmation_choice("yesterday"))
        self.assertIsNone(_confirmation_choice("no thanks"))

    def test_a_different_purpose_asks_before_it_qualifies(self):
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _prepare_fieldfactors(db_path)
            before = get_workflow(db_path, "FieldFactors")
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                reply = _answer("Qualify FieldFactors for AI audit", manager, agent)
            self.assertEqual(reply, ASK)
            self.assertNotIn(OLD_NOTE, reply)
            for blocked in BLOCKED:
                self.assertNotIn(blocked, reply)
            self.assertEqual(manager.calls, [])
            self.assertEqual(agent.queries, [])
            after = get_workflow(db_path, "FieldFactors")
            self.assertEqual(after["step"], "declined")
            self.assertEqual(after["draft"], before["draft"])
            self.assertEqual(after["findings_json"], before["findings_json"])
            self.assertEqual(after["updated_at"], before["updated_at"])
            pending = pending_qualification(db_path)
            self.assertEqual(
                pending,
                {
                    "company_name": "FieldFactors",
                    "purpose": "AI audit",
                    "previous_purpose": "CTO opportunity",
                },
            )

    def test_yes_runs_the_skill_once_and_keeps_the_old_note(self):
        for word in ("yes", "yes please", "y"):
            with self.subTest(word=word):
                self._yes_qualifies(word)

    def test_no_does_not_run_the_skill(self):
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification
        from icp_workflow import preserved_company_notes

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _prepare_fieldfactors(db_path)
            before = get_workflow(db_path, "FieldFactors")
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                asked = _answer("Qualify FieldFactors for AI audit", manager, agent)
                reply = _answer("no", manager, agent)
            self.assertEqual(asked, ASK)
            self.assertEqual(reply, "Nothing was changed. Nothing was sent.")
            self.assertEqual(manager.calls, [])
            self.assertEqual(agent.queries, [])
            self.assertIsNone(pending_qualification(db_path))
            self.assertEqual(preserved_company_notes(db_path, "FieldFactors"), [])
            after = get_workflow(db_path, "FieldFactors")
            self.assertEqual(after["step"], before["step"])
            self.assertEqual(after["draft"], before["draft"])
            self.assertEqual(after["findings_json"], before["findings_json"])
            self.assertEqual(after["updated_at"], before["updated_at"])

    def test_a_later_yes_after_another_message_does_not_qualify(self):
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _prepare_fieldfactors(db_path)
            before = get_workflow(db_path, "FieldFactors")
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                bare = _answer("yes", manager, agent)
                asked = _answer("Qualify FieldFactors for AI audit", manager, agent)
                other = _answer("yes now", manager, agent)
                cleared = pending_qualification(db_path)
                later = _answer("yes", manager, agent)
            self.assertEqual(bare, "model reply")
            self.assertEqual(asked, ASK)
            self.assertEqual(other, "model reply")
            self.assertIsNone(cleared)
            self.assertEqual(later, "model reply")
            self.assertEqual(manager.calls, [])
            self.assertEqual(
                agent.queries,
                [("yes", "hey-eman"), ("yes now", "hey-eman"), ("yes", "hey-eman")],
            )
            after = get_workflow(db_path, "FieldFactors")
            self.assertEqual(after["draft"], before["draft"])
            self.assertEqual(after["step"], before["step"])
            self.assertEqual(after["updated_at"], before["updated_at"])

    def test_the_same_purpose_does_not_ask(self):
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _prepare_fieldfactors(db_path)
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                plain = _answer("Qualify FieldFactors", manager, agent)
                named = _answer("Qualify FieldFactors for CTO opportunity", manager, agent)
            stored = "Left the note for FieldFactors. Nothing was sent.\n\n" + OLD_NOTE
            self.assertEqual(plain, stored)
            self.assertEqual(named, stored)
            self.assertNotIn("Reply yes", plain)
            self.assertNotIn("Reply yes", named)
            self.assertEqual(manager.calls, [])
            self.assertEqual(agent.queries, [])
            self.assertIsNone(pending_qualification(db_path))

    def test_a_company_without_a_saved_decision_qualifies_immediately(self):
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification
        from priority_inbox import emit_priority_action

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path).close()
            emit_priority_action(
                kind="icp_candidate",
                title="Northwind",
                description="Suggested for review.",
                payload={
                    "company_name": "Northwind",
                    "website": "https://northwind.example",
                    "industry": "saas",
                    "employee_count": 30,
                    "funding_stage": "seed",
                },
                priority=1,
                source_key="icp-candidate:northwind",
                db_path=db_path,
            )
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                reply = _answer("Qualify Northwind for AI audit", manager, agent)
            self.assertNotIn("Reply yes", reply)
            self.assertIn("Qualified as AI audit", reply)
            self.assertIn("has not been sent", reply)
            self.assertIn("AI audit note for Northwind.", reply)
            for blocked in BLOCKED:
                self.assertNotIn(blocked, reply)
            self.assertEqual([call["skill"] for call in manager.calls], ["icp_prospector", "outreach_draft"])
            self.assertEqual(manager.calls[0]["payload"]["company"]["company_name"], "Northwind")
            self.assertEqual(manager.calls[0]["payload"]["purpose"], "AI audit")
            self.assertNotIn("seed_path", manager.calls[0]["payload"])
            self.assertIsNone(pending_qualification(db_path))
            self.assertEqual(agent.queries, [])

    def test_the_real_draft_skill_writes_the_new_purpose_and_keeps_the_old_note(self):
        from hey_eman_app import _answer
        from icp_workflow import company_key
        from icp_workflow import preserved_company_notes
        from priority_inbox import emit_priority_action
        from skills.outreach_draft import OutreachDraftSkill

        class Fit(Skill):
            name = "icp_prospector"

            def __init__(self) -> None:
                self.payloads: list[dict] = []

            def run(self, task: dict) -> dict:
                payload = task.get("payload") or {}
                self.payloads.append(payload)
                name = str((payload.get("company") or {}).get("company_name") or "")
                return {
                    "top_companies": [{"name": name, "rationale": "Fits an AI audit"}],
                    "rejected": [],
                }

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            fit = Fit()
            manager.register(fit)
            manager.register(OutreachDraftSkill())
            _insert(
                db_path,
                "FieldFactors",
                "declined",
                json.dumps(
                    {
                        "purpose": "CTO opportunity",
                        "top_companies": [{"name": "FieldFactors", "rationale": "No CTO and hiring"}],
                        "rejected": [],
                    }
                ),
                OLD_NOTE,
            )
            action_id = emit_priority_action(
                kind="outreach_draft",
                title="Note for FieldFactors",
                description="Draft only. Approving it does not send the note.",
                payload={
                    "title": "FieldFactors",
                    "body": OLD_NOTE,
                    "send": False,
                    "company": True,
                },
                priority=1,
                source_key="icp-outreach:fieldfactors",
                db_path=db_path,
            )
            conn = sqlite3.connect(db_path)
            conn.execute(
                "UPDATE workflow_runs SET action_id = ? WHERE company_key = ?",
                (action_id, company_key("FieldFactors")),
            )
            conn.commit()
            conn.close()
            agent = _QuietAgent()
            with patch.dict(os.environ, {"TAVILY_API_KEY": "", "OPENAI_API_KEY": ""}, clear=False):
                with patch("skills.outreach_draft.tavily_search", return_value={"results": []}) as search:
                    asked = _answer("Qualify FieldFactors for AI audit", manager, agent)
                    reply = _answer("yes", manager, agent)
            self.assertEqual(asked, ASK)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(len(fit.payloads), 1)
            self.assertEqual(fit.payloads[0]["company"]["company_name"], "FieldFactors")
            self.assertEqual(fit.payloads[0]["purpose"], "AI audit")
            self.assertNotIn("seed_path", fit.payloads[0])
            self.assertIn("AI audit", reply)
            self.assertIn("has not been sent", reply)
            self.assertNotIn(OLD_NOTE, reply)
            for blocked in BLOCKED:
                self.assertNotIn(blocked, reply)
            self.assertEqual(agent.queries, [])
            kept = preserved_company_notes(db_path, "FieldFactors")
            self.assertEqual(kept[0]["draft"], OLD_NOTE)
            self.assertEqual(kept[0]["purpose"], "CTO opportunity")
            self.assertEqual(kept[0]["step"], "declined")
            self.assertEqual(kept[0]["action_id"], action_id)
            current = get_workflow(db_path, "FieldFactors")
            self.assertEqual(current["step"], "awaiting_approval")
            self.assertIn("AI audit", current["draft"])
            self.assertNotIn(OLD_NOTE, current["draft"])
            self.assertEqual(_workflow_count(db_path), 1)
            bodies = [
                json.loads(row["payload_json"]).get("body")
                for row in _action_rows(db_path)
            ]
            self.assertIn(OLD_NOTE, bodies)
            self.assertTrue(
                any(
                    isinstance(body, str) and "AI audit" in body and OLD_NOTE not in body
                    for body in bodies
                )
            )
            manager.close()

    def _yes_qualifies(self, word: str) -> None:
        from hey_eman_app import _answer
        from icp_workflow import pending_qualification
        from icp_workflow import preserved_company_notes

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            _prepare_fieldfactors(db_path)
            manager = _FakeManager(db_path)
            agent = _QuietAgent()
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}, clear=False):
                asked = _answer("Qualify FieldFactors for AI audit", manager, agent)
                reply = _answer(word, manager, agent)
                again = _answer("yes", manager, agent)
            self.assertEqual(asked, ASK)
            self.assertIn("Qualified as AI audit", reply)
            self.assertIn("has not been sent", reply)
            self.assertIn("AI audit note for FieldFactors.", reply)
            self.assertNotIn(OLD_NOTE, reply)
            for blocked in BLOCKED:
                self.assertNotIn(blocked, reply)
            self.assertEqual(
                [call["skill"] for call in manager.calls],
                ["icp_prospector", "outreach_draft"],
            )
            prospect = manager.calls[0]["payload"]
            self.assertEqual(prospect["company"]["company_name"], "FieldFactors")
            self.assertEqual(prospect["purpose"], "AI audit")
            self.assertNotIn("seed_path", prospect)
            self.assertEqual(manager.calls[1]["payload"]["company_name"], "FieldFactors")
            self.assertEqual(manager.calls[1]["payload"]["purpose"], "AI audit")
            self.assertEqual(again, "model reply")
            self.assertEqual(agent.queries, [("yes", "hey-eman")])
            self.assertIsNone(pending_qualification(db_path))
            kept = preserved_company_notes(db_path, "FieldFactors")
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["draft"], OLD_NOTE)
            self.assertEqual(kept[0]["purpose"], "CTO opportunity")
            self.assertEqual(kept[0]["step"], "declined")
            current = get_workflow(db_path, "FieldFactors")
            self.assertEqual(current["draft"], "AI audit note for FieldFactors.")
            self.assertEqual(current["step"], "awaiting_approval")
            self.assertIn('"purpose": "AI audit"', current["findings_json"])
            self.assertEqual(_workflow_count(db_path), 1)


def _workflow_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()
    finally:
        conn.close()
    return int(row[0])


def _notes(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM pending_actions WHERE action_type = 'outreach_draft'"
        ).fetchall()
    finally:
        conn.close()


def _action_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(
            "SELECT action_id, status, payload_json FROM pending_actions ORDER BY action_id"
        ))
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


def _insert(db_path: str, name: str, step: str, findings: str, draft: str = "") -> None:
    from icp_workflow import company_key
    from icp_workflow import ensure_workflow

    ensure_workflow(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workflow_runs (
                company_key, company_name, website, step, findings_json, draft, updated_at
            ) VALUES (?, ?, '', ?, ?, ?, '2026-11-20T00:00:00+00:00')
            """,
            (company_key(name), name, step, findings, draft),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
