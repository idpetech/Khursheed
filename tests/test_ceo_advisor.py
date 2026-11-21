import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desk_settings import prepare_desk_tasks
from desk_work import add_commitment
from desk_work import list_commitments
from manager import Manager
from skills.ceo_advisor import CeoAdvisorSkill
from skills.ceo_advisor import SECTIONS
from skills.ceo_advisor import is_ceo_request
from skills.ceo_advisor import question_from
from skills.ceo_advisor import track_latest_advice


ASSESSMENT = """## Executive assessment
One retainer is the commercial goal. This is advice.

## Relevant facts and assumptions
Fact: a commitment is open. No revenue figure is on the desk.

## Opportunities
Win the one retainer.

## Risks and constraints
A role is still waiting.

## Available options
Pursue the open commitment, or stop and reset the goal.

## Recommended decision
Keep the retainer as the only commercial goal.

## Immediate next steps
Next step: Call the prospect this week.
"""


class CeoAdvisorTests(unittest.TestCase):
    def test_an_assessment_has_the_seven_sections_and_does_not_act(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            add_commitment(db_path, "Send the proposal")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", return_value=ASSESSMENT) as complete:
                    result = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Challenge my current priorities."}}
                    )
            complete.assert_called_once()
            self.assertFalse(result["executed"])
            self.assertTrue(result["advisory"])
            for section in SECTIONS:
                self.assertIn(f"## {section}", result["assessment"])
            self.assertEqual([row["title"] for row in list_commitments(db_path)], ["Send the proposal"])
            pending = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
            self.assertEqual(pending, 0)

    def test_the_prompt_includes_a_goal_and_a_commitment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = str(root / "t.db")
            profile = root / "principal.json"
            profile.write_text(json.dumps({"goals": ["Win one retainer"]}), encoding="utf-8")
            Manager(db_path=db_path)
            add_commitment(db_path, "Send the proposal")
            seen = {}

            def capture(question, context):
                seen["question"] = question
                seen["context"] = context
                return ASSESSMENT

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", capture):
                    CeoAdvisorSkill().run(
                        {
                            "db_path": db_path,
                            "profile_path": str(profile),
                            "payload": {"question": "Review the quarter."},
                        }
                    )
            self.assertEqual(seen["question"], "Review the quarter.")
            self.assertIn("Win one retainer", seen["context"])
            self.assertIn("Send the proposal", seen["context"])
            self.assertIn("Earlier recommendations", seen["context"])

    def test_a_missing_model_returns_an_error(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with patch("skills.ceo_advisor._complete") as complete:
                result = CeoAdvisorSkill().run(
                    {"db_path": ":memory:", "payload": {"question": "Review the quarter."}}
                )
        complete.assert_not_called()
        self.assertFalse(result["executed"])
        self.assertIn("needs the model", result["error"])

    def test_track_this_saves_the_next_step_without_another_model_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", return_value=ASSESSMENT) as complete:
                    manager.run_skill(
                        "ceo_advisor",
                        "ceo-1",
                        {"question": "Give me a CEO assessment."},
                    )
                    calls = complete.call_count
                    saved = track_latest_advice(db_path)
                    self.assertEqual(complete.call_count, calls)
            self.assertEqual(saved["status"], "ok")
            self.assertEqual(
                [row["title"] for row in list_commitments(db_path)],
                ["Call the prospect this week."],
            )

    def test_the_morning_run_does_not_include_the_advisor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            tasks = json.loads((Path(__file__).resolve().parents[1] / "tasks.json").read_text())
            prepared = prepare_desk_tasks(tasks["tasks"], db_path)
        names = [skill for task in prepared for skill in task["skills"]]
        self.assertNotIn("ceo_advisor", names)
        self.assertTrue(is_ceo_request("Give me a CEO assessment of IDPETECH."))
        self.assertEqual(question_from("Ask CEO Advisor"), "Give me a CEO assessment of the business as it stands.")

    def test_an_explicit_ask_without_a_model_does_not_run_a_skill(self):
        from hey_eman_app import _ask_ceo

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                with patch("skills.ceo_advisor._complete") as complete:
                    text = _ask_ceo("Ask CEO Advisor", manager)
            complete.assert_not_called()
            self.assertIn("needs the model", text)
            runs = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM skill_runs").fetchone()[0]
            self.assertEqual(runs, 0)


if __name__ == "__main__":
    unittest.main()
