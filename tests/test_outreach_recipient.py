"""A new company note names a recipient only when a page does."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from icp_workflow import advance_icp
from icp_workflow import company_key
from icp_workflow import decide_icp_draft
from icp_workflow import ensure_workflow
from icp_workflow import get_workflow
from icp_workflow import list_company_notes
from manager import Manager
from skills.base import Skill
from skills.outreach_draft import OutreachDraftSkill


OWN_SITE = "https://analyticalengines.com"
DIRECTORY = "https://100xfounder.com/startups/early-stage-startups"
PAGE = "https://analytical.example/about"


def _ceo_page() -> dict:
    return {
        "results": [
            {
                "title": "About Analytical Engines",
                "url": PAGE,
                "content": "Ada Lovelace, CEO of Analytical Engines. Write to ada@example.com.",
            }
        ]
    }


class RecipientLookupTests(unittest.TestCase):
    def test_a_snippet_that_names_a_ceo_and_an_email_is_kept(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with patch("skills.outreach_draft.tavily_search", return_value=_ceo_page()) as search:
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {
                            "company_name": "Analytical Engines",
                            "website": OWN_SITE,
                            "purpose": "CTO opportunity",
                            "rationale": "No CTO listed.",
                        },
                    }
                )
            self.assertEqual(search.call_count, 1)
            self.assertEqual(
                search.call_args.args[0],
                f"Analytical Engines founder or CEO {OWN_SITE}",
            )
            self.assertFalse(result["sent"])
            lines = result["draft"].splitlines()
            self.assertEqual(lines[0], "To: Ada Lovelace, CEO")
            self.assertEqual(lines[1], "Email: ada@example.com")
            self.assertEqual(lines[2], f"Source: {PAGE}")
            self.assertEqual(lines[4], "Hello Ada,")
            self.assertIn("fractional CTO", result["draft"])
            payload = _payload(db_path)
            self.assertFalse(payload["send"])
            self.assertEqual(payload["body"], result["draft"])

    def test_a_snippet_with_no_person_says_no_recipient_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            page = {
                "results": [
                    {
                        "title": "Secoda",
                        "url": DIRECTORY,
                        "content": "Secoda builds data tools. Contact hello@example.com.",
                    }
                ]
            }
            with patch("skills.outreach_draft.tavily_search", return_value=page) as search:
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {
                            "company_name": "Secoda",
                            "website": DIRECTORY,
                            "purpose": "CTO opportunity",
                        },
                    }
                )
            self.assertEqual(search.call_count, 1)
            self.assertEqual(search.call_args.args[0], "Secoda founder or CEO")
            self.assertNotIn("100xfounder", search.call_args.args[0])
            lines = result["draft"].splitlines()
            self.assertEqual(lines[0], "No recipient found.")
            self.assertEqual(lines[2], "Hello,")
            self.assertFalse(any(line.startswith("To:") for line in lines))
            self.assertFalse(any(line.startswith("Source:") for line in lines))
            self.assertNotIn("hello@example.com", result["draft"])
            self.assertNotIn("first@company.com", result["draft"])
            self.assertFalse(result["sent"])
            self.assertFalse(_payload(db_path)["send"])

    def test_an_email_outside_the_snippet_is_dropped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            page = {
                "results": [
                    {
                        "title": "Press",
                        "url": "https://analytical.example/press",
                        "content": "Media contact other@example.com.",
                    },
                    {
                        "title": "Leadership",
                        "url": "https://analytical.example/team",
                        "content": "Ada Lovelace is the CEO.",
                        "email": "ada@example.com",
                    },
                ]
            }
            with patch("skills.outreach_draft.tavily_search", return_value=page):
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {
                            "company_name": "Analytical Engines",
                            "website": OWN_SITE,
                            "purpose": "CTO opportunity",
                        },
                    }
                )
            lines = result["draft"].splitlines()
            self.assertEqual(lines[0], "To: Ada Lovelace, CEO")
            self.assertEqual(lines[1], "Email: none on the source page.")
            self.assertEqual(lines[2], "Source: https://analytical.example/team")
            self.assertEqual(lines[4], "Hello Ada,")
            self.assertNotIn("ada@example.com", result["draft"])
            self.assertNotIn("other@example.com", result["draft"])
            self.assertNotIn("first@company.com", result["draft"])
            self.assertFalse(result["sent"])

    def test_a_saved_note_is_not_searched_or_rewritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            ensure_workflow(db_path)
            saved = "Hello from the saved note."
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    company_key, company_name, website, step, findings_json, draft, updated_at
                ) VALUES (?, 'Axiom Math AI', '', 'approved', '', ?, '2026-11-21T00:00:00+00:00')
                """,
                (company_key("Axiom Math AI"), saved),
            )
            conn.commit()
            conn.close()
            with patch("skills.outreach_draft.tavily_search") as search:
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {
                            "company_name": "Axiom Math AI",
                            "website": "https://axiom.example",
                            "purpose": "CTO opportunity",
                        },
                    }
                )
                again = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {"company_name": "Axiom Math AI", "website": "https://axiom.example"},
                    }
                )
            search.assert_not_called()
            self.assertEqual(result["draft"], saved)
            self.assertEqual(again["draft"], saved)
            self.assertEqual(get_workflow(db_path, "Axiom Math AI")["draft"], saved)
            self.assertFalse(result["sent"])

    def test_reading_a_new_note_again_does_not_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(_Fit())
            manager.register(OutreachDraftSkill())
            company = {"company_name": "Northwind", "website": "https://northwind.example"}
            with patch("skills.outreach_draft.tavily_search", return_value=_ceo_page()) as search:
                first = advance_icp(db_path, company, manager)
                stored = get_workflow(db_path, "Northwind")["draft"]
                second = advance_icp(db_path, company, manager)
                action_id = get_workflow(db_path, "Northwind")["action_id"]
                approved = decide_icp_draft(db_path, action_id, approve=True)
                notes = list_company_notes(db_path)
            self.assertEqual(search.call_count, 1)
            self.assertEqual(
                search.call_args.args[0],
                "Northwind founder or CEO https://northwind.example",
            )
            self.assertEqual(stored.splitlines()[0], "To: Ada Lovelace, CEO")
            self.assertEqual(stored.splitlines()[1], "Email: ada@example.com")
            self.assertEqual(stored.splitlines()[2], f"Source: {PAGE}")
            self.assertEqual(get_workflow(db_path, "Northwind")["draft"], stored)
            self.assertEqual(second["step"], "awaiting_approval")
            self.assertFalse(first["sent"])
            self.assertFalse(approved["sent"])
            self.assertEqual(notes[0]["draft"], stored)

    def test_a_role_note_does_not_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with patch("skills.outreach_draft.tavily_search") as search:
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {"title": "Empirical LLC", "url": "https://empirical.example"},
                    }
                )
            search.assert_not_called()
            self.assertTrue(result["draft"].startswith("Hello,"))
            self.assertNotIn("No recipient found.", result["draft"])
            self.assertFalse(result["sent"])

    def test_a_failed_search_still_leaves_the_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with patch("skills.outreach_draft.tavily_search", side_effect=OSError("tunnel failed")):
                result = OutreachDraftSkill().run(
                    {
                        "db_path": db_path,
                        "payload": {
                            "company_name": "Northwind",
                            "website": "https://northwind.example",
                            "purpose": "a distribution partner",
                        },
                    }
                )
            self.assertEqual(result["draft"].splitlines()[0], "No recipient found.")
            self.assertIn("distribution partner", result["draft"])
            self.assertNotIn("fractional CTO", result["draft"])
            self.assertFalse(result["sent"])
            self.assertFalse(_payload(db_path)["send"])


class _Fit(Skill):
    name = "icp_prospector"

    def run(self, task: dict) -> dict:
        return {"top_companies": [{"name": "Northwind", "rationale": "No CTO"}], "rejected": []}


def _payload(db_path: str) -> dict:
    raw = sqlite3.connect(db_path).execute(
        "SELECT payload_json FROM pending_actions WHERE action_type = 'outreach_draft'"
    ).fetchone()[0]
    return json.loads(raw)


if __name__ == "__main__":
    unittest.main()
