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
from skills.ceo_advisor import _has_decision
from skills.ceo_advisor import is_ceo_request
from skills.ceo_advisor import question_from
from skills.ceo_advisor import track_latest_advice


ASSESSMENT = """The open commitment is the only commercial item on the desk.

Decision: CONDITIONAL GO
Strategic rationale: The commitment is already chosen.
Commercial rationale: A proposal is the path to revenue.
Evidence: The desk lists one open commercial commitment.
Unknowns: Whether the other party will pay.
Resource commitment: The time to make the call.
Opportunity cost: Other outreach waits.
Next action: Call the prospect this week.
Confidence: Medium, because the desk does not show a price.
"""


class CeoAdvisorTests(unittest.TestCase):
    def test_an_assessment_reaches_a_decision_and_does_not_act(self):
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
            self.assertTrue(_has_decision(result["assessment"]))
            self.assertIn("Decision: CONDITIONAL GO", result["assessment"])
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
            self.assertIn("Omitted. This question is not about running the desk.", seen["context"])
            self.assertIn("No external subject.", seen["context"])

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
        self.assertTrue(is_ceo_request("As a CEO evaluate 1Kiraana"))
        self.assertFalse(is_ceo_request("What's urgent?"))
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


    def test_an_external_subject_is_looked_up_without_the_desk_chores(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = str(root / "t.db")
            profile = root / "principal.json"
            profile.write_text(
                json.dumps(
                    {
                        "goals": [
                            "Win one fractional CTO retainer this quarter",
                            "Publish one plainspoken LinkedIn post a week",
                        ],
                        "icp": "Seed to series B software companies that need a CTO.",
                    }
                ),
                encoding="utf-8",
            )
            Manager(db_path=db_path)
            add_commitment(db_path, "Clear the inbox")
            add_commitment(db_path, "Send the proposal")
            seen = {}

            def search(query, max_results=4, api_key=None):
                seen.setdefault("queries", []).append(query)
                return {
                    "results": [
                        {
                            "title": "Story Protocol",
                            "url": "https://www.story.foundation/",
                            "content": "Programmable IP layer. Not a buyer of fractional CTO services.",
                        }
                    ]
                }

            def capture(question, context):
                seen["context"] = context
                return ASSESSMENT.replace("CONDITIONAL GO", "NO-GO")

            question = "Assess whether Story Protocol is a customer, partner, or commercial opportunity for IDPETECH."
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": "test"}):
                with patch("skills.ceo_advisor.tavily_search", search):
                    with patch("skills.ceo_advisor._complete", capture):
                        CeoAdvisorSkill().run(
                            {
                                "db_path": db_path,
                                "profile_path": str(profile),
                                "payload": {"question": question},
                            }
                        )
            self.assertTrue(any("Story Protocol" in query for query in seen["queries"]))
            self.assertNotIn("fractional CTO", " ".join(seen["queries"]))
            context = seen["context"]
            self.assertIn("Programmable IP layer", context)
            self.assertIn("This describes IDPETECH, not the subject.", context)
            self.assertIn("Send the proposal", context)
            self.assertNotIn("Clear the inbox", context)
            self.assertNotIn("LinkedIn", context)
            self.assertNotIn("Seed to series B", context)
            self.assertIn("Not the definition of a fit", context)

    def test_a_missing_search_is_disclosed_and_not_invented(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            seen = {}

            def capture(question, context):
                seen["context"] = context
                return ASSESSMENT

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": ""}):
                with patch("skills.ceo_advisor.tavily_search") as search:
                    with patch("skills.ceo_advisor._complete", capture):
                        result = CeoAdvisorSkill().run(
                            {
                                "db_path": db_path,
                                "payload": {"question": "Assess FieldFactors as a customer for IDPETECH."},
                            }
                        )
            search.assert_not_called()
            self.assertIn("Research was not performed.", seen["context"])
            self.assertTrue(result["assessment"].startswith("Research was not performed."))
            self.assertFalse(result["researched"])


if __name__ == "__main__":
    unittest.main()
