"""Fill remaining branches in the chief-of-staff runner, brief, and ask CLI."""

import json
import os
import runpy
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
from openai import APIConnectionError

import ask
from action_executor import approve_and_execute
from chat_memory import load_recent_turns
from enaam_orchestrator import VictorOrchestrator
from executive_summary import _build_recommendations
from executive_summary import _extract_cto_opportunities
from executive_summary import _extract_icp_companies
from executive_summary import _extract_open_loops
from executive_summary import _extract_pending_bills
from executive_summary import _extract_priority_alerts
from executive_summary import _extract_top_leads
from executive_summary import _format_cto_opportunities
from executive_summary import _format_icp_companies
from executive_summary import _format_leads
from executive_summary import _format_open_loops
from executive_summary import _format_pending_bills
from executive_summary import _format_priority_alerts
from executive_summary import _format_recommendations
from executive_summary import _format_tasks
from executive_summary import _highest_other_priority_action
from executive_summary import _newest_linkedin_draft
from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from open_loops import emit_open_loop
from open_loops import list_open_loops
from open_loops import record_cto_opportunities
from open_loops import record_icp_companies
from principal_profile import principal_prompt_block
from runtime import prepare_runtime
from runtime import remove_test_pending_actions
from runtime import resolve_db_path
from schedule_sync import _run_due_jobs
from skills.base import Skill
from skills.cto_radar import CtoRadarSkill
from skills.icp_prospector import IcpProspectorSkill
from skills_bootstrap import _description
from skills_bootstrap import _upsert_skill_records
from skills_bootstrap import default_skill_names


class NamedSkill(Skill):
    """Finds the next step."""

    name = "documented"

    def run(self, task):
        return {"ok": bool(task)}


class BlankSkill(Skill):
    name = "blank"

    def run(self, task):
        return {"ok": bool(task)}


class BoomSkill(Skill):
    name = "boom"

    def run(self, task):
        raise RuntimeError(str(task.get("id", "boom")))


class SifterStub(Skill):
    name = "sifter"

    def run(self, task):
        return {"ok": bool(task)}


class RecordingNotifier:
    def __init__(self):
        self.report = ""

    def send(self, report: str) -> None:
        self.report = report


class _Message:
    def __init__(self, content=None, function_call=None):
        self.content = content
        self.function_call = function_call


class _Response:
    def __init__(self, content=None, function_call=None):
        choice = MagicMock()
        choice.message = _Message(content, function_call)
        self.choices = [choice]


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
        return self._responses.pop(0)


class _Client:
    def __init__(self, responses):
        self.chat = MagicMock()
        self.chat.completions = _Completions(responses)


def _db():
    tmp = tempfile.TemporaryDirectory()
    path = str(Path(tmp.name) / "test.db")
    Manager(db_path=path)
    return tmp, path


def _insert_pending(db_path, action_id, action_type, title, payload=None, priority=1):
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    created_at, created_by, status, priority
                ) VALUES (?, ?, ?, '', ?, ?, 'coverage', 'pending', ?)
                """,
                (
                    action_id,
                    action_type,
                    title,
                    json.dumps(payload) if payload is not None else "",
                    datetime.now(UTC).isoformat(),
                    priority,
                ),
            )
    finally:
        conn.close()


class RuntimeCoverageTests(unittest.TestCase):
    def test_relative_path_missing_file_and_prepare(self):
        resolved = resolve_db_path("khursheed.db")
        self.assertTrue(resolved.is_absolute())
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "absent.db"
            self.assertEqual(remove_test_pending_actions(missing), 0)
            prepared = prepare_runtime(Path(tmpdir) / "fresh.db")
            self.assertEqual(prepared, 0)
            bad = Path(tmpdir) / "not-a-database"
            bad.write_text("nope", encoding="utf-8")
            self.assertEqual(remove_test_pending_actions(bad), 0)

    def test_open_loop_edges_and_sqlite_failures(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(record_cto_opportunities([{"title": "", "url": ""}, {}], db_path=db_path), 0)
        self.assertEqual(
            record_cto_opportunities(
                [{"url": "https://jobs.example/cto", "snippet": "remote " * 80}],
                db_path=db_path,
            ),
            1,
        )
        self.assertEqual(record_icp_companies([{"name": "  "}, {}], db_path=db_path), 0)
        self.assertEqual(
            record_icp_companies(
                [{"company_name": "Northwind", "rationale": "needs a CTO"}],
                db_path=db_path,
            ),
            1,
        )
        bad = Path(tmp.name) / "not-a-database"
        bad.write_text("nope", encoding="utf-8")
        self.assertEqual(emit_open_loop("x", "k", "t", db_path=bad), "")
        self.assertEqual(list_open_loops(bad), [])
        self.assertEqual(load_recent_turns("hey-eman", db_path=bad), [])

    def test_profile_fields_and_bad_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "principal.json"
            path.write_text(
                json.dumps(
                    {
                        "goals": "Ship the brief",
                        "icp": "seed startups",
                        "voice": "plain",
                        "will_not": ["", "spam"],
                        "people": ["Ada"],
                    }
                ),
                encoding="utf-8",
            )
            block = principal_prompt_block(path)
            self.assertIn("Ship the brief", block)
            self.assertIn("seed startups", block)
            self.assertIn("plain", block)
            self.assertIn("spam", block)
            self.assertIn("Ada", block)
            path.write_text("{", encoding="utf-8")
            self.assertEqual(principal_prompt_block(path), "")
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(principal_prompt_block(path), "")
            path.write_text(
                json.dumps({"goals": 4, "icp": 3, "voice": None, "will_not": None, "people": None}),
                encoding="utf-8",
            )
            self.assertEqual(principal_prompt_block(path), "")
            self.assertEqual(principal_prompt_block(Path(tmpdir)), "")
            self.assertEqual(principal_prompt_block(Path(tmpdir) / "missing.json"), "")

    def test_skill_registry_edges(self):
        self.assertIn("sifter", default_skill_names())
        self.assertEqual(_description(NamedSkill()), "Finds the next step.")
        self.assertIsNone(_description(BlankSkill()))
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager = Manager(db_path=db_path)
        manager.register(NamedSkill())
        manager._connection.execute("DROP TABLE skill_configurations")
        manager._connection.commit()
        _upsert_skill_records(manager, [NamedSkill()])
        self.assertIn("documented", manager.list_skill_names())

    def test_schedule_failure_empty_and_missing_skill(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager = Manager(db_path=db_path)
        manager.register(BoomSkill())
        manager.run_tasks([{"id": "empty", "skills": []}])
        manager.run_tasks([{"id": "boom", "skills": ["boom"], "payload": {}}])
        status = manager._connection.execute(
            "SELECT status FROM skill_runs WHERE task_id = 'boom'"
        ).fetchone()[0]
        self.assertEqual(status, "failed")
        with self.assertRaises(KeyError):
            manager.run_tasks([{"id": "gone", "skills": ["missing"]}])
        now = datetime.now(UTC).isoformat()
        manager._connection.execute(
            """
            UPDATE scheduled_jobs
            SET next_run_at = ?, payload_json = '', schedule_config = ?
            WHERE job_name = 'boom:boom'
            """,
            (now, json.dumps({"type": "one_time", "interval_days": None})),
        )
        manager._connection.commit()
        _run_due_jobs(manager, ["boom:boom"], datetime.now(UTC))


class SummaryCoverageTests(unittest.TestCase):
    def test_summary_renders_every_section_and_degrades(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager = Manager(db_path=db_path)
        manager._record_run(
            "cto",
            "cto_radar",
            {
                "opportunities": [
                    {
                        "title": "Role",
                        "url": "https://x",
                        "score": 2,
                        "tags": [],
                        "location": "FL",
                        "work_mode": "remote",
                    }
                ]
            },
        )
        manager._record_run("bad", "cto_radar", {})
        manager._connection.execute(
            "UPDATE skill_runs SET result_json = ? WHERE task_id = 'bad'",
            ("{",),
        )
        manager._record_run(
            "icp",
            "icp_prospector",
            {"top_companies": [{"company_name": "Acme", "score": 3}]},
        )
        manager._record_run(
            "mail",
            "sifter",
            {
                "accounts": [
                    {
                        "categorized": [
                            {"category": "Urgent/Bill", "subject": "Invoice", "from": "ap@x"},
                            {"category": "Other", "subject": "Hi", "from": "a@x"},
                            {"category": "Urgent/Bill", "subject": "", "from": ""},
                        ]
                    }
                ]
            },
        )
        manager._record_run(
            "leads",
            "lead_scout",
            {"queries": [{"leads": [{"title": "Lead", "url": "https://l", "score": 1, "tags": []}]}]},
        )
        manager._connection.commit()
        emit_open_loop("cto_radar", "cto:due", "Call Ada", due_at="2026-10-20", db_path=db_path)
        _insert_pending(db_path, "alert-1", "alert", "Pager", priority=3)
        report = generate_executive_summary(manager, RecordingNotifier())
        self.assertIn("Role", report)
        self.assertIn("Acme", report)
        self.assertIn("Invoice", report)
        self.assertIn("Lead", report)
        self.assertIn("Call Ada", report)
        self.assertIn("due 2026-10-20", report)

        self.assertIn("No fractional", _format_cto_opportunities([]))
        self.assertIn("Uncategorized", _format_cto_opportunities([{"title": "R", "tags": []}]))
        self.assertIn("No ICP", _format_icp_companies([]))
        self.assertIn("(unknown)", _format_icp_companies([{}]))
        self.assertIn("No leads", _format_leads([]))
        self.assertIn("Uncategorized", _format_leads([{"title": "L", "tags": []}]))
        self.assertEqual(
            _extract_cto_opportunities([{"skill_name": "cto_radar", "result_json": None}], 5),
            [],
        )
        self.assertEqual(
            _extract_icp_companies([{"skill_name": "icp_prospector", "result_json": None}], 5),
            [],
        )
        self.assertEqual(_build_recommendations(None, [], None)[0], "No further recommendation.")
        self.assertEqual(_format_tasks([]), "_No tasks executed in the last 24 hours._")
        self.assertEqual(_format_pending_bills([]), "_No pending bills detected._")
        self.assertEqual(_format_priority_alerts([]), "_No open priority alerts._")
        self.assertIn("due tomorrow", _format_priority_alerts([{"priority": 9, "expires_at": "tomorrow"}]))
        detailed = _format_priority_alerts(
            [
                {
                    "priority": 3,
                    "title": "Bill",
                    "created_at": "2026-05-29T03:12:59+00:00",
                    "description": "Invoice subject",
                    "payload_json": json.dumps(
                        {
                            "from": "billing@testcorp.com",
                            "subject": "Invoice subject",
                            "account": "yahoo",
                            "sent_at": "Thu, 28 May 2026 12:00:00 +0000",
                        }
                    ),
                },
                {
                    "priority": 2,
                    "title": "Critical System Alert",
                    "description": "Database backup failed",
                    "payload_json": "{'severity': 'high', 'from': '  '}",
                },
                {
                    "priority": 1,
                    "title": "Same",
                    "description": "Same",
                    "payload_json": "{1}",
                },
                {
                    "priority": 0,
                    "title": "Broken",
                    "description": 3,
                    "payload_json": "not json",
                },
                {
                    "priority": 0,
                    "title": "List payload",
                    "payload_json": "[1]",
                },
                {
                    "priority": 0,
                    "title": "Dict payload",
                    "payload_json": {"from": "ada@example.com"},
                },
                {
                    "priority": 0,
                    "title": "Number payload",
                    "payload_json": 5,
                },
            ]
        )
        self.assertIn("From: billing@testcorp.com", detailed)
        self.assertIn("Mailbox: yahoo", detailed)
        self.assertIn("Sent: Thu, 28 May 2026 12:00:00 +0000", detailed)
        self.assertIn("Recorded: 2026-05-29T03:12:59+00:00", detailed)
        self.assertIn("Subject: Database backup failed", detailed)
        self.assertIn("From: ada@example.com", detailed)
        self.assertIn("From: not recorded", detailed)
        self.assertIn("Sent: not recorded", detailed)
        self.assertIn("(untitled)", _format_open_loops([{}]))
        self.assertIn("1. No further recommendation.", _format_recommendations([]))
        recommendations = _build_recommendations({"priority": 1}, [{}], {"id": "draft"})
        self.assertIn("(untitled)", recommendations[0])
        self.assertIn("(untitled)", recommendations[1])
        self.assertIn("(untitled)", recommendations[2])

        runs = manager.get_runs_since(datetime.now(UTC).replace(year=2020))
        self.assertEqual(_extract_cto_opportunities(runs, 5)[0]["title"], "Role")
        self.assertTrue(_extract_icp_companies(runs, 5))
        self.assertTrue(_extract_top_leads(runs, 5))
        self.assertTrue(_extract_pending_bills(runs))
        self.assertIsNone(_newest_linkedin_draft(db_path))
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM pending_actions WHERE action_id = 'alert-1'")
        conn.commit()
        conn.close()
        self.assertIsNone(_highest_other_priority_action(db_path))
        _insert_pending(db_path, "draft-only", "linkedin_post_draft", "Only draft")
        self.assertEqual(_newest_linkedin_draft(db_path)["title"], "Only draft")

        with patch("priority_inbox.list_open_priority_actions", side_effect=RuntimeError("down")):
            self.assertEqual(_extract_priority_alerts(db_path=db_path), [])
            self.assertIsNone(_highest_other_priority_action(db_path))
            self.assertIsNone(_newest_linkedin_draft(db_path))
        with patch("open_loops.list_open_loops", side_effect=RuntimeError("down")):
            self.assertEqual(_extract_open_loops(db_path), [])

        empty = generate_executive_summary(Manager(db_path=str(Path(tmp.name) / "empty.db")), RecordingNotifier())
        self.assertIn("_No open loops._", empty)
        self.assertIn("_No open priority alerts._", empty)


class AgentCoverageTests(unittest.TestCase):
    def _agent(self, db_path, responses):
        manager = Manager(db_path=db_path)
        agent = HeyEmanAgent(manager)
        agent._client = _Client(responses)
        return manager, agent

    def test_direct_reply_connection_error_and_empty_registry(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        _manager, agent = self._agent(db_path, [_Response(content=None)])
        self.assertEqual(agent.respond("hi"), "No response available.")
        agent._client = _Client([])
        agent._client.chat.completions.create = MagicMock(
            side_effect=APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
        )
        self.assertIn("OpenAI connection error", agent.respond("again"))

        bare = HeyEmanAgent(Manager(db_path=db_path))
        self.assertIn("(none registered)", bare._system_prompt())
        self.assertNotIn("enum", bare._tool_definitions()[0]["function"]["parameters"]["properties"]["skill_name"])
        with patch("llm_agent.OpenAI", return_value=_Client([_Response(content="ok")])):
            created = HeyEmanAgent(Manager(db_path=db_path))
            self.assertEqual(created.respond("ping"), "ok")

    def test_function_calls(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager, agent = self._agent(
            db_path,
            [
                _Response(function_call=_FunctionCall("run_skill", "{}")),
                _Response(content=None),
            ],
        )
        manager.register(SifterStub())
        self.assertEqual(agent.respond("run"), "Task completed.")

        agent._client = _Client(
            [
                _Response(
                    function_call=_FunctionCall(
                        "run_skill",
                        json.dumps({"skill_name": "sifter", "payload": {}}),
                    )
                ),
                _Response(content="Ran it."),
            ]
        )
        self.assertEqual(agent.respond("check"), "Ran it.")

        agent._client = _Client(
            [
                _Response(function_call=_FunctionCall("list_skills")),
                _Response(content="Listed."),
            ]
        )
        self.assertEqual(agent.respond("skills"), "Listed.")

        agent._client = _Client(
            [
                _Response(function_call=_FunctionCall("executive_summary", "")),
                _Response(content="Summarized."),
            ]
        )
        with patch("llm_agent.MarkdownFileNotifier", RecordingNotifier):
            self.assertEqual(agent.respond("summary"), "Summarized.")

        agent._client = _Client(
            [
                _Response(function_call=_FunctionCall("list_priority_actions")),
                _Response(content="None urgent."),
            ]
        )
        self.assertEqual(agent.respond("urgent"), "None urgent.")

        agent._client = _Client(
            [
                _Response(function_call=_FunctionCall("unknown_tool")),
                _Response(content="Unknown handled."),
            ]
        )
        self.assertEqual(agent.respond("nope"), "Unknown handled.")


class ApprovalCoverageTests(unittest.TestCase):
    def test_missing_credentials_failure_and_unknown_reason(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(approve_and_execute(db_path, "missing")["status"], "error")
        _insert_pending(db_path, "empty-payload", "new_bill", "Blank", payload=None)
        self.assertEqual(approve_and_execute(db_path, "empty-payload")["outcome"], "acknowledged")
        self.assertEqual(approve_and_execute(db_path, "empty-payload")["status"], "error")
        _insert_pending(
            db_path,
            "draft-1",
            "linkedin_post_draft",
            "Draft",
            payload={"title": "Hello", "body_markdown": "Body"},
        )
        env = {"KHURSHEED_BLOGGER_PUBLISH_ENABLED": "true", "LINKEDIN_ACCESS_TOKEN": "", "LINKEDIN_PAGE_ID": ""}
        with patch.dict(os.environ, env, clear=False):
            result = approve_and_execute(db_path, "draft-1")
        self.assertEqual(result["reason"], "linkedin_credentials_missing")

        with patch("action_executor.execute_pending_action", return_value={"status": "pending", "reason": "weird"}):
            weird = approve_and_execute(db_path, "draft-1")
        self.assertIn("weird", weird["message"])
        with patch("action_executor.execute_pending_action", return_value={"status": "pending"}):
            blank = approve_and_execute(db_path, "draft-1")
        self.assertEqual(blank["outcome"], "pending")

        with (
            patch.dict(
                os.environ,
                {
                    "KHURSHEED_BLOGGER_PUBLISH_ENABLED": "true",
                    "LINKEDIN_ACCESS_TOKEN": "token",
                    "LINKEDIN_PAGE_ID": "1",
                },
                clear=False,
            ),
            patch("skills.blogger.BloggerSkill._publish_to_linkedin", side_effect=RuntimeError("down")),
        ):
            failed = approve_and_execute(db_path, "draft-1")
        self.assertEqual(failed["outcome"], "pending")
        self.assertIn("down", failed["reason"])

    def test_orchestrator_approve_handler(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        orchestrator = VictorOrchestrator.__new__(VictorOrchestrator)
        orchestrator.db_path = db_path
        missing = orchestrator._handle_approve_action("run-1", {})
        self.assertEqual(missing["message"], "action_id is required")
        _insert_pending(db_path, "bill-1", "new_bill", "Pay the host", priority=2)
        approved = orchestrator._handle_approve_action("run-2", {"action_id": "bill-1", "reviewed_by": "coverage"})
        self.assertEqual(approved["run_id"], "run-2")
        self.assertEqual(approved["outcome"], "acknowledged")
        with patch("action_executor.approve_and_execute", side_effect=RuntimeError("explode")):
            exploded = orchestrator._handle_approve_action("run-3", {"action_id": "bill-1"})
        self.assertIn("explode", exploded["message"])


class ManagerCoverageTests(unittest.TestCase):
    def test_context_manager_missing_skill_and_init_failure(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        with Manager(db_path=db_path) as manager:
            manager._initialize_database()
            with self.assertRaises(KeyError):
                manager.run_skill("missing", "task", {})
            tasks_file = Path(tmp.name) / "tasks.json"
            tasks_file.write_text("{}", encoding="utf-8")
            self.assertEqual(manager.load_tasks(str(tasks_file)), [])
            manager._initialized = False

            class LockedConnection:
                def execute(self, *_args, **_kwargs):
                    message = "locked"
                    raise sqlite3.OperationalError(message)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def locked_connection():
                return LockedConnection()

            manager._connection_manager.get_connection = locked_connection
            with self.assertRaises(RuntimeError):
                manager._initialize_database()


class SkillLoopTests(unittest.TestCase):
    def test_cto_and_icp_write_loops_and_survive_loop_failures(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        fake = {
            "results": [
                {"title": "Fractional CTO", "url": "https://example.com/job", "content": "remote Jacksonville"}
            ]
        }
        with patch("skills.cto_radar.tavily_search", return_value=fake):
            found = CtoRadarSkill().run({"id": "t", "payload": {}, "db_path": db_path})
        self.assertTrue(found["opportunities"])
        self.assertTrue(list_open_loops(db_path))
        with (
            patch("skills.cto_radar.tavily_search", return_value=fake),
            patch("open_loops.record_cto_opportunities", side_effect=RuntimeError("loop")),
        ):
            survived = CtoRadarSkill().run({"id": "t2", "payload": {}, "db_path": db_path})
        self.assertIn("opportunities", survived)

        prospector = IcpProspectorSkill()
        ranked = {"top_companies": [{"name": "Acme"}], "rejected": []}
        with (
            patch.object(prospector, "_load_and_filter_csv", return_value=[{"company_name": "Acme"}]),
            patch.object(prospector, "_enrich_companies", side_effect=lambda rows: rows),
            patch.object(prospector, "_rank_companies", return_value=ranked),
        ):
            result = prospector.run({"id": "p", "payload": {}, "db_path": db_path})
        self.assertEqual(result["top_companies"][0]["name"], "Acme")
        with (
            patch.object(prospector, "_load_and_filter_csv", return_value=[{"company_name": "Acme"}]),
            patch.object(prospector, "_enrich_companies", side_effect=lambda rows: rows),
            patch.object(prospector, "_rank_companies", return_value=ranked),
            patch("open_loops.record_icp_companies", side_effect=RuntimeError("loop")),
        ):
            again = prospector.run({"id": "p2", "payload": {}, "db_path": db_path})
        self.assertIn("top_companies", again)


class AskCoverageTests(unittest.TestCase):
    def test_keyword_router(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager = Manager(db_path=db_path)
        manager.register(SifterStub())
        manager.load_tasks = lambda _path: [{"id": "only", "skills": ["sifter"], "payload": {}}]
        with patch("ask.MarkdownFileNotifier", RecordingNotifier):
            self.assertIn("Executive Summary", ask._handle_query("executive summary", manager))
        self.assertIn("only", ask._handle_query("todos", manager))
        self.assertIn("Email check", ask._handle_query("check emails", manager))
        self.assertIn("Tasks executed", ask._handle_query("run tasks", manager))
        self.assertIn("Try:", ask._handle_query("hello", manager))

    def test_interactive_and_one_shot(self):
        tmp, db_path = _db()
        self.addCleanup(tmp.cleanup)
        manager = Manager(db_path=db_path)
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch("builtins.input", side_effect=["", "hello", "exit"]),
        ):
            ask._interactive(manager)
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch("builtins.input", side_effect=EOFError),
        ):
            ask._interactive(manager)
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            ask._interactive(manager)
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False),
            patch("ask.HeyEmanAgent") as agent_cls,
            patch("builtins.input", side_effect=["what is urgent", "quit"]),
        ):
            agent_cls.return_value.respond.return_value = "Nothing urgent."
            ask._interactive(manager)
        agent_cls.return_value.respond.assert_called_once()

        with (
            patch("ask.load_dotenv"),
            patch("ask.prepare_runtime"),
            patch("ask.Manager", return_value=manager),
            patch("ask.register_default_skills"),
            patch("ask._interactive") as interactive,
            patch.object(sys, "argv", ["ask.py"]),
        ):
            ask.main()
        interactive.assert_called_once()

        with (
            patch("ask.load_dotenv"),
            patch("ask.prepare_runtime"),
            patch("ask.Manager", return_value=manager),
            patch("ask.register_default_skills"),
            patch("ask._answer", return_value="Noted."),
            patch.object(sys, "argv", ["ask.py", "hello"]),
        ):
            ask.main()

    def test_modules_run_as_main(self):
        root = Path(__file__).resolve().parent.parent
        with (
            patch("dotenv.load_dotenv"),
            patch("runtime.prepare_runtime"),
            patch("skills_bootstrap.register_default_skills"),
            patch("manager.Manager") as manager_cls,
            patch("executive_summary.generate_executive_summary"),
            patch("notifications.MarkdownFileNotifier"),
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False),
            patch.object(sys, "argv", ["ask.py", "hello"]),
        ):
            manager_cls.return_value.load_tasks.return_value = []
            runpy.run_path(str(root / "khursheed.py"), run_name="__main__")
            runpy.run_path(str(root / "ask.py"), run_name="__main__")


if __name__ == "__main__":
    unittest.main()
