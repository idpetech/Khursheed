"""Desk eval for the checks that define this desk.

A fake model stands in for the provider. This module does not call a paid API.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from action_executor import approve_and_execute
from desk_model import ModelReply
from desk_work import add_commitment
from desk_work import block_commitment
from desk_work import cancel_commitment
from desk_work import complete_commitment
from desk_work import list_commitments
from llm_agent import HeyEmanAgent
from manager import Manager
from skills.base import Skill
from skills.blogger import BloggerSkill
from skills.ceo_advisor import CeoAdvisorSkill
from skills.icp_finder import _offer
from skills.icp_finder import _own_website


VALID_DECISION = json.dumps(
    {
        "assessment": "The fit is not established.",
        "decision": "DEFER",
        "strategic_rationale": "The fit is not established yet.",
        "commercial_rationale": "No buyer has offered to pay.",
        "evidence": [],
        "unknowns": ["Whether a buyer would pay."],
        "assumptions": [],
        "conditions": [],
        "resource_commitment": "None until the fit is known.",
        "opportunity_cost": "Time spent on a weak fit.",
        "next_action": "Stop. Do not pursue this.",
        "confidence": "Low, because the fit is unknown.",
    }
)

PROSE_DECISION = (
    "Decision: GO. Next action: Call the prospect. "
    "This is strategically interesting and commercially real for IDPETECH."
)

BROKEN_JSON = '{"decision": "GO", "strategic_rationale": "The fit is real"'

JSON_WITHOUT_DECISION = json.dumps(
    {
        "assessment": "The fit is not established.",
        "strategic_rationale": "The fit is not established yet.",
        "commercial_rationale": "No buyer has offered to pay.",
        "next_action": "Call the prospect this week.",
    }
)

DIRECTORY_PAGE = "https://100xfounder.com/startups/early-stage-startups"


class FakeModel:
    """Returns one scripted reply. It does not open a provider client."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return ModelReply(
            text=self.text,
            prompt_tokens=3,
            completion_tokens=2,
            model="fake-model",
        )


class _Message:
    def __init__(self, content, function_call=None):
        self.content = content
        self.function_call = function_call


class _Choice:
    def __init__(self, message):
        self.message = message


class _Response:
    def __init__(self, content=None, function_call=None):
        self.choices = [_Choice(_Message(content, function_call))]


class _FunctionCall:
    def __init__(self, name, arguments="{}"):
        self.name = name
        self.arguments = arguments


class _Completions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("the fake model was called again")
        return self._responses.pop(0)


class _Chat:
    def __init__(self, responses):
        self.completions = _Completions(responses)


class _Client:
    """OpenAI-shaped client. create() never leaves the process."""

    def __init__(self, responses):
        self.chat = _Chat(responses)


class _Caller(Skill):
    name = "desk_note"

    def run(self, task):
        return task["ctx"].run_skill("blogger", {"mode": "publish", "theme": "fractional CTOs"})


def _decision_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'strategic_decisions'"
        ).fetchone()
        if exists is None:
            return 0
        return conn.execute("SELECT COUNT(*) FROM strategic_decisions").fetchone()[0]
    finally:
        conn.close()


def _sessions(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [
            row[0]
            for row in conn.execute("SELECT session_id FROM chat_turns ORDER BY created_at")
        ]
    finally:
        conn.close()


def _insert_pending(db_path, action_id, action_type, title, payload):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    created_at, created_by, status, priority
                ) VALUES (?, ?, ?, '', ?, '2026-11-22T12:00:00+00:00', 'eval', 'pending', 1)
                """,
                (action_id, action_type, title, json.dumps(payload)),
            )
    finally:
        conn.close()


def _pending_status(db_path, action_id):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM pending_actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else row[0]


class EnaamEvalTests(unittest.TestCase):
    def test_a_strategic_question_writes_the_ceo_session_and_skips_the_chief_of_staff(self):
        from hey_eman_app import _answer

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            manager.register(CeoAdvisorSkill())
            agent = HeyEmanAgent(manager, model="gpt-4o-mini")
            responded = []

            def respond(*args, **kwargs):
                responded.append((args, kwargs))
                raise AssertionError("HeyEmanAgent.respond")

            agent.respond = respond
            fake = FakeModel(VALID_DECISION)
            env = {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": "", "ANTHROPIC_API_KEY": ""}
            with patch.dict(os.environ, env, clear=False):
                with patch("skills.ceo_advisor.call_model", fake):
                    with patch("desk_model._openai_client", side_effect=AssertionError("paid client")):
                        answer = _answer("Challenge my current priorities.", manager, agent)
            self.assertEqual(responded, [])
            self.assertEqual(len(fake.calls), 1)
            self.assertIn("DEFER", answer)
            self.assertEqual(_sessions(db_path), ["hey-eman-ceo"])
            self.assertEqual(_decision_count(db_path), 1)

    def test_a_model_tool_call_cannot_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            manager = Manager(db_path=db_path)
            blogger = BloggerSkill()
            ran = []

            def run(task):
                ran.append(task.get("id"))
                return {"status": "published", "published": True}

            blogger.run = run
            manager.register(blogger)
            manager.register(_Caller())
            _insert_pending(
                db_path,
                "draft-1",
                "linkedin_post_draft",
                "Draft: hiring",
                {"title": "Hello", "body_markdown": "Body", "hashtags": ["cto"]},
            )
            publish_call = json.dumps(
                {"skill_name": "blogger", "payload": {"mode": "publish", "theme": "fractional CTOs"}}
            )
            client = _Client(
                [
                    _Response(function_call=_FunctionCall("run_skill", publish_call)),
                    _Response(content="Nothing was posted."),
                ]
            )
            agent = HeyEmanAgent(manager, model="gpt-4o-mini")
            agent._client = client
            env = {
                "OPENAI_API_KEY": "test",
                "ANTHROPIC_API_KEY": "",
                "KHURSHEED_BLOGGER_PUBLISH_ENABLED": "true",
                "LINKEDIN_ACCESS_TOKEN": "test-token",
                "LINKEDIN_PAGE_ID": "test-page",
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("desk_model._openai_client", side_effect=AssertionError("paid client")):
                    with patch("skills.blogger.requests.post", side_effect=AssertionError("network")):
                        agent.respond("Publish the LinkedIn post.", session_id="hey-eman")
                        nested = manager.run_skill("desk_note", "from-another-skill", {})
                        direct = manager.run_skill(
                            "blogger",
                            "direct-publish",
                            {"mode": "publish", "theme": "fractional CTOs"},
                        )
                        self.assertEqual(_pending_status(db_path, "draft-1"), "pending")
                        self.assertEqual(ran, [])
                        with patch.object(
                            BloggerSkill,
                            "_publish_to_linkedin",
                            return_value={"id": "urn:li:share:eval"},
                        ) as publish:
                            approved = approve_and_execute(db_path, "draft-1", reviewed_by="desk")
                        publish.assert_called_once()
            function_rows = [
                message
                for message in client.chat.completions.calls[1]["messages"]
                if message.get("role") == "function"
            ]
            tool_result = json.loads(function_rows[-1]["content"])
            self.assertEqual(tool_result["status"], "refused")
            self.assertFalse(tool_result["published"])
            self.assertIn("approval on Content", tool_result["message"])
            self.assertEqual(nested["status"], "refused")
            self.assertFalse(nested["published"])
            self.assertIn("approval on Content", nested["message"])
            self.assertEqual(direct["status"], "refused")
            self.assertFalse(direct["published"])
            self.assertEqual(approved["outcome"], "executed")
            self.assertEqual(_pending_status(db_path, "draft-1"), "executed")
            refused = [
                row[0]
                for row in sqlite3.connect(db_path).execute(
                    "SELECT status FROM skill_runs WHERE skill_name = 'blogger' ORDER BY rowid"
                )
            ]
            self.assertEqual(refused, ["refused", "refused", "refused"])

    def test_a_directory_page_is_not_stored_as_a_company_website(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            snippets = [
                {
                    "title": "Early stage startups",
                    "url": DIRECTORY_PAGE,
                    "content": "Secoda, Capital, and Simplified are on this list.",
                }
            ]
            extracted = [
                {
                    "company_name": "Secoda",
                    "website": DIRECTORY_PAGE,
                    "industry": "saas",
                    "funding_stage": "seed",
                    "why": "Needs a fractional CTO.",
                },
                {
                    "company_name": "Capital",
                    "website": DIRECTORY_PAGE,
                    "industry": "fintech",
                    "funding_stage": "seed",
                    "why": "Needs a fractional CTO.",
                },
                {
                    "company_name": "Simplified",
                    "website": DIRECTORY_PAGE,
                    "industry": "saas",
                    "funding_stage": "seed",
                    "why": "Needs a fractional CTO.",
                },
            ]
            for row in extracted:
                self.assertEqual(_own_website(row["company_name"], row["website"]), "")
            offered = _offer(extracted, snippets, 5, db_path)
            self.assertEqual(
                [row["company_name"] for row in offered],
                ["Secoda", "Capital", "Simplified"],
            )
            self.assertEqual([row["website"] for row in offered], ["", "", ""])
            stored = []
            conn = sqlite3.connect(db_path)
            try:
                payloads = [
                    row[0]
                    for row in conn.execute(
                        "SELECT payload_json FROM pending_actions ORDER BY title"
                    )
                ]
            finally:
                conn.close()
            self.assertEqual(len(payloads), 3)
            for payload_json in payloads:
                self.assertNotIn(DIRECTORY_PAGE, payload_json)
                stored.append(json.loads(payload_json)["website"])
            self.assertEqual(stored, ["", "", ""])

    def test_invalid_ceo_json_is_not_stored_as_a_decision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            env = {"OPENAI_API_KEY": "test", "TAVILY_API_KEY": "", "ANTHROPIC_API_KEY": ""}
            question = {"question": "Review the quarter."}
            with patch.dict(os.environ, env, clear=False):
                with patch("desk_model._openai_client", side_effect=AssertionError("paid client")):
                    for text in (PROSE_DECISION, BROKEN_JSON, JSON_WITHOUT_DECISION):
                        fake = FakeModel(text)
                        with patch("skills.ceo_advisor.call_model", fake):
                            result = CeoAdvisorSkill().run({"db_path": db_path, "payload": question})
                        self.assertEqual(len(fake.calls), 2)
                        self.assertIn("did not reach a decision", result["error"])
                        self.assertNotIn("decision_id", result)
                        self.assertIsNone(result.get("decision"))
            self.assertEqual(_decision_count(db_path), 0)

    def test_a_commitment_can_move_to_blocked_and_cancelled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            Manager(db_path=db_path)
            _insert_pending(
                db_path,
                "wait-1",
                "linkedin_post_draft",
                "Draft waiting for approval",
                {"title": "Hello", "body_markdown": "Body"},
            )
            send = add_commitment(db_path, "Send the proposal", "2026-11-20")
            held = add_commitment(db_path, "Call the bank", "2026-11-19")
            dropped = add_commitment(db_path, "Skip the intro", "2026-11-18")
            conn = sqlite3.connect(db_path)
            try:
                columns = [row[1] for row in conn.execute("PRAGMA table_info(commitments)")]
                stored = {
                    row[0]: row[1]
                    for row in conn.execute("SELECT commitment_id, status FROM commitments")
                }
            finally:
                conn.close()
            self.assertIn("status", columns)
            self.assertNotIn("blocked", columns)
            self.assertNotIn("cancelled", columns)
            self.assertEqual(
                stored,
                {
                    send["commitment_id"]: "open",
                    held["commitment_id"]: "open",
                    dropped["commitment_id"]: "open",
                },
            )
            self.assertEqual(
                [row["title"] for row in list_commitments(db_path)],
                ["Send the proposal", "Call the bank", "Skip the intro"],
            )
            self.assertEqual(block_commitment(db_path, held["commitment_id"])["status"], "ok")
            self.assertEqual(cancel_commitment(db_path, dropped["commitment_id"])["status"], "ok")
            self.assertEqual(complete_commitment(db_path, send["commitment_id"])["message"], "Marked done.")
            conn = sqlite3.connect(db_path)
            try:
                statuses = {
                    row[0]: row[1]
                    for row in conn.execute("SELECT title, status FROM commitments")
                }
                waiting = conn.execute(
                    "SELECT action_type, status FROM pending_actions WHERE action_id = 'wait-1'"
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(
                statuses,
                {
                    "Send the proposal": "done",
                    "Call the bank": "blocked",
                    "Skip the intro": "cancelled",
                },
            )
            self.assertEqual(list_commitments(db_path), [])
            self.assertEqual(
                [row["title"] for row in list_commitments(db_path, ("blocked",))],
                ["Call the bank"],
            )
            self.assertEqual(
                [row["title"] for row in list_commitments(db_path, ("cancelled",))],
                ["Skip the intro"],
            )
            self.assertEqual(waiting, ("linkedin_post_draft", "pending"))
            self.assertNotIn("pending", statuses.values())


if __name__ == "__main__":
    unittest.main()
