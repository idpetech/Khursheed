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
from skills.ceo_advisor import classify_request
from skills.ceo_advisor import gather_research
from skills.ceo_advisor import is_ceo_request
from skills.ceo_advisor import question_from
from skills.ceo_advisor import track_latest_advice


ASSESSMENT = json.dumps(
    {
        "assessment": "The open commitment is the only commercial item on the desk.",
        "decision": "CONDITIONAL GO",
        "strategic_rationale": "The commitment is already chosen.",
        "commercial_rationale": "A proposal is the path to revenue.",
        "evidence": "The desk lists one open commercial commitment.",
        "unknowns": "Whether the other party will pay.",
        "assumptions": "The commitment is still open.",
        "conditions": "The other party agrees to pay.",
        "resource_commitment": "The time to make the call.",
        "opportunity_cost": "Other outreach waits.",
        "next_action": "Call the prospect this week.",
        "confidence": "Medium, because the desk does not show a price.",
    }
)


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
            self.assertEqual(result["decision"], "CONDITIONAL GO")
            self.assertIn("Decision: CONDITIONAL GO", result["display"])
            self.assertEqual(result["display"].count("Decision:"), 1)
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
            self.assertIn("not a rule for every opportunity", context)
            self.assertIn("Not the definition of a fit", context)
            self.assertIn("not full pages", context)

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
                    with patch("skills.ceo_advisor._complete") as complete:
                        result = CeoAdvisorSkill().run(
                            {
                                "db_path": db_path,
                                "payload": {"question": "Assess FieldFactors as a customer for IDPETECH."},
                            }
                        )
            search.assert_not_called()
            complete.assert_not_called()
            self.assertEqual(result["decision"], "DEFER")
            self.assertEqual(result["research_status"], "NOT_RUN")
            self.assertIn("Research was not performed.", result["display"])
            self.assertFalse(result["researched"])

    def test_natural_strategic_requests_route_to_the_advisor(self):
        from hey_eman_app import _answer

        self.assertEqual(classify_request("Should IDPETECH pursue Story Protocol?"), "strategic")
        self.assertEqual(classify_request("Is this business worth entering?"), "strategic")
        self.assertEqual(classify_request("Give me your strategic opinion."), "strategic")
        self.assertEqual(classify_request("ceo: review the quarter"), "strategic")
        self.assertEqual(classify_request("Tell me about Story Protocol."), "informational")
        self.assertEqual(classify_request("Prepare a follow-up email to Story Protocol."), "operational")
        self.assertEqual(classify_request("Story Protocol"), "ambiguous")
        self.assertFalse(is_ceo_request("Tell me about Story Protocol."))
        self.assertFalse(is_ceo_request("Prepare a follow-up email to Story Protocol."))

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())

            class Agent:
                def respond(self, *_args, **_kwargs):
                    raise AssertionError("the chat model rewrote a strategic assessment")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": ""}):
                with patch("skills.ceo_advisor._complete") as complete:
                    text = _answer("Should IDPETECH pursue Story Protocol?", manager, Agent())
            complete.assert_not_called()
            self.assertIn("Decision: DEFER", text)
            self.assertIn("This is advice.", text)
            self.assertNotIn("Executive Assessment", text)

    def test_a_decision_is_saved_and_a_reassessment_links_to_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": "test"}):
                with patch(
                    "skills.ceo_advisor.tavily_search",
                    return_value={
                        "results": [
                            {
                                "title": "Story Protocol",
                                "url": "https://www.story.foundation/",
                                "content": "IP network.",
                            }
                        ]
                    },
                ):
                    with patch("skills.ceo_advisor._complete", return_value=ASSESSMENT):
                        first = manager.run_skill(
                            "ceo_advisor", "t", {"question": "Assess Story Protocol."}
                        )
                        second = manager.run_skill(
                            "ceo_advisor", "t", {"question": "Reassess Story Protocol."}
                        )
            self.assertEqual(first["decision"], "CONDITIONAL GO")
            self.assertTrue(first["decision_id"])
            self.assertEqual(second["decision_id"] != first["decision_id"], True)
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT decision_id, parent_decision_id, decision FROM strategic_decisions ORDER BY created_at"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0][0], first["decision_id"])
            self.assertEqual(rows[0][1], "")
            self.assertEqual(rows[1][2], "CONDITIONAL GO")
            self.assertEqual(rows[1][1], first["decision_id"])
            from skills.ceo_advisor import answer_decision_lookup

            text = answer_decision_lookup(db_path, "What did we decide about Story Protocol?")
            self.assertIn("CONDITIONAL GO", text)
            saved = track_latest_advice(db_path)
            again = track_latest_advice(db_path)
            self.assertFalse(saved.get("duplicate"))
            self.assertTrue(again.get("duplicate"))
            titles = [row["title"] for row in list_commitments(db_path)]
            self.assertEqual(titles, ["Call the prospect this week."])

    def test_invalid_model_output_is_not_stored_as_a_decision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", return_value="I think this is fine.") as complete:
                    result = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Challenge my current priorities."}}
                    )
            self.assertEqual(complete.call_count, 2)
            self.assertIn("did not reach a decision", result["error"])
            self.assertNotIn("decision_id", result)
            conn = sqlite3.connect(db_path)
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='strategic_decisions'"
            ).fetchone()
            self.assertIsNone(table)

    def test_primary_snippets_stay_ahead_and_a_draft_is_not_sent(self):
        def search(query, max_results=4, api_key=None):
            return {
                "results": [
                    {"title": "Coverage", "url": "https://news.example.com/story", "content": "A report."},
                    {"title": "Home", "url": "https://www.story.foundation/", "content": "Official page."},
                ]
            }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test"}):
            with patch("skills.ceo_advisor.tavily_search", search):
                research = gather_research("Assess Story Protocol.")
        self.assertEqual(research["snippets"][0]["source_class"], "possible_primary")
        self.assertIn("not full pages", research["note"])
        self.assertEqual(research["research_status"], "COMPLETE")

        draft = ASSESSMENT.replace("Call the prospect this week.", "Draft an outreach note.")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", return_value=draft):
                    result = manager.run_skill(
                        "ceo_advisor", "t", {"question": "Challenge my current priorities."}
                    )
            self.assertIn("outreach_draft", result["display"])
            self.assertIn("does not send", result["display"])
            names = [
                row[0]
                for row in sqlite3.connect(db_path).execute("SELECT skill_name FROM skill_runs")
            ]
            self.assertEqual(names, ["ceo_advisor"])

    def test_prose_and_a_label_grid_are_not_turned_into_a_decision(self):
        prose = "OneKiraana is interesting. Commercially real for IDPETECH: Unknown. Next action: Stop."
        grid = json.dumps(
            {
                "assessment": "OneKiraana helps kirana stores.",
                "decision": "NO-GO",
                "strategic_rationale": "Strategically interesting: UNKNOWN. Worth the resource commitment: ASSUMED.",
                "commercial_rationale": (
                    "Commercially real for someone: REPORTED. "
                    "Commercially real for IDPETECH: ASSUMED. "
                    "Deliverable by IDPETECH: ASSUMED."
                ),
                "next_action": "Stop. Do not pursue this.",
                "confidence": "Medium",
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                with patch("skills.ceo_advisor._complete", return_value=prose):
                    prose_result = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Review the quarter."}}
                    )
                with patch("skills.ceo_advisor._complete", return_value=grid):
                    grid_result = CeoAdvisorSkill().run(
                        {"db_path": db_path, "payload": {"question": "Review the quarter."}}
                    )
        self.assertIn("did not reach a decision", prose_result["error"])
        self.assertNotIn("decision_id", prose_result)
        self.assertIn("did not reach a decision", grid_result["error"])
        self.assertNotIn("decision_id", grid_result)


if __name__ == "__main__":
    unittest.main()
