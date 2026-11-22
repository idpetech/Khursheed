"""Tests for the shared runner, brief, memory, and approval path."""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from action_executor import approve_and_execute
from action_executor import revise_action_payload
from desk_model import call_model
from executive_summary import generate_executive_summary
from hey_eman_app import _recent_runs
from hey_eman_app import _run_line
from llm_agent import HeyEmanAgent
from manager import Manager
from open_loops import close_open_loop
from open_loops import emit_open_loop
from open_loops import list_open_loops
from open_loops import loop_url
from principal_profile import principal_prompt_block
from runtime import remove_test_pending_actions
from skill_declarations import DECLARATIONS
from skill_declarations import EXTERNAL
from skill_declarations import READ_ONLY
from skill_declarations import REVERSIBLE
from skills.base import Skill
from skills_bootstrap import register_default_skills


class DummySkill(Skill):
    name = "dummy"

    def run(self, task):
        return {"task_id": task.get("id"), "status": "ok"}


class RecordingNotifier:
    def __init__(self):
        self.report = ""

    def send(self, report: str) -> None:
        self.report = report


class _Message:
    def __init__(self, content):
        self.content = content
        self.function_call = None


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response("Noted.")


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class _Client:
    def __init__(self):
        self.chat = _Chat()


def _insert_pending(db_path, action_id, action_type, title, priority=1, payload=None, created_at=None):
    created_at = created_at or datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    created_at, created_by, status, priority
                ) VALUES (?, ?, ?, '', ?, ?, 'test-suite', 'pending', ?)
                """,
                (
                    action_id,
                    action_type,
                    title,
                    json.dumps(payload or {}),
                    created_at,
                    priority,
                ),
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
        return row[0] if row else None
    finally:
        conn.close()


class BootstrapTests(unittest.TestCase):
    def test_entry_points_share_registration(self):
        root = Path(__file__).resolve().parent.parent
        for name in ("khursheed.py", "ask.py", "hey_eman_app.py"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertIn("register_default_skills", text)
        ask_source = (root / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("api_key=api_key", ask_source)
        self.assertIn("HeyEmanAgent(manager)", ask_source)

    def test_register_default_skills_reaches_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = Manager(db_path=str(Path(tmpdir) / "test.db"))
            register_default_skills(manager)
            names = manager.list_skill_names()
            for skill_name in ("sifter", "cto_radar", "icp_prospector", "blogger"):
                self.assertIn(skill_name, names)
            rows = manager._connection.execute(
                "SELECT skill_name FROM skill_configurations"
            ).fetchall()
            configured = {row[0] for row in rows}
            self.assertIn("cto_radar", configured)
            self.assertIn("blogger", configured)
            self.assertIn("icp_prospector", configured)


class ScheduleTests(unittest.TestCase):
    def test_interval_skips_a_recent_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = Manager(db_path=str(Path(tmpdir) / "test.db"))
            manager.register(DummySkill())
            recent = datetime.now(UTC).isoformat()
            manager._record_run("task-1", "dummy", {"status": "ok"})
            manager._connection.execute(
                "UPDATE skill_runs SET executed_at = ? WHERE task_id = ?",
                (recent, "task-1"),
            )
            manager._connection.commit()
            tasks = [{"id": "task-1", "skills": ["dummy"], "interval_days": 3, "payload": {}}]
            manager.run_tasks(tasks)
            count = manager._connection.execute(
                "SELECT COUNT(*) FROM skill_runs WHERE task_id = ? AND skill_name = ?",
                ("task-1", "dummy"),
            ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_due_job_runs_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = Manager(db_path=str(Path(tmpdir) / "test.db"))
            manager.register(DummySkill())
            old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            manager._record_run("task-1", "dummy", {"status": "ok"})
            manager._connection.execute(
                "UPDATE skill_runs SET executed_at = ? WHERE task_id = ?",
                (old, "task-1"),
            )
            manager._connection.commit()
            tasks = [{"id": "task-1", "skills": ["dummy"], "interval_days": 3, "payload": {}}]
            manager.run_tasks(tasks)
            manager.run_tasks(tasks)
            count = manager._connection.execute(
                "SELECT COUNT(*) FROM skill_runs WHERE task_id = ? AND skill_name = ?",
                ("task-1", "dummy"),
            ).fetchone()[0]
            self.assertEqual(count, 2)


class BriefTests(unittest.TestCase):
    def test_open_loop_dedupes_on_source_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            Manager(db_path=db_path)
            first = emit_open_loop("cto_radar", "cto:https://example.com", "Role A", db_path=db_path)
            second = emit_open_loop("cto_radar", "cto:https://example.com", "Role A again", db_path=db_path)
            self.assertEqual(first, second)
            self.assertEqual(len(list_open_loops(db_path)), 1)
            self.assertEqual(loop_url({"source_key": "cto:https://example.com"}), "https://example.com")
            self.assertEqual(close_open_loop(first, db_path=db_path)["status"], "ok")
            self.assertEqual(list_open_loops(db_path), [])
            self.assertEqual(emit_open_loop("cto_radar", "cto:https://example.com", "Role A", db_path=db_path), first)
            self.assertEqual(list_open_loops(db_path), [])

    def test_summary_lists_loop_and_three_recommendations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            manager = Manager(db_path=db_path)
            emit_open_loop("cto_radar", "cto:northwind", "Call Northwind", db_path=db_path)
            _insert_pending(db_path, "bill-1", "new_bill", "Pay the host", priority=2)
            _insert_pending(
                db_path,
                "draft-1",
                "linkedin_post_draft",
                "Draft: hiring",
                priority=1,
                created_at="2026-10-16T12:00:00+00:00",
            )
            notifier = RecordingNotifier()
            report = generate_executive_summary(manager, notifier)
            self.assertIn("Call Northwind", report)
            self.assertIn("- Pay the host", report)
            self.assertNotIn("Handle priority action: Pay the host", report)
            self.assertIn("2. Follow up: Call Northwind", report)
            self.assertIn("3. Review LinkedIn draft: Draft: hiring", report)

    def test_cleanup_keeps_real_bills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            Manager(db_path=db_path)
            _insert_pending(db_path, "t1", "test", "fixture")
            _insert_pending(db_path, "t2", "test_dedup", "fixture")
            _insert_pending(db_path, "t3", "test_financial", "fixture")
            _insert_pending(db_path, "bill-1", "new_bill", "Pay the host", priority=2)
            removed = remove_test_pending_actions(db_path)
            self.assertEqual(removed, 3)
            self.assertIsNone(_pending_status(db_path, "t1"))
            self.assertEqual(_pending_status(db_path, "bill-1"), "pending")


class MemoryTests(unittest.TestCase):
    def test_empty_profile_adds_nothing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "principal.json"
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(principal_prompt_block(path), "")

    def test_profile_and_prior_turn_reach_the_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            profile = Path(tmpdir) / "principal.json"
            profile.write_text(json.dumps({"goals": ["Ship the brief"]}), encoding="utf-8")
            manager = Manager(db_path=db_path)
            agent = HeyEmanAgent(manager, profile_path=str(profile))
            agent._client = _Client()
            agent.respond("first question", session_id="hey-eman")
            agent.respond("second question", session_id="hey-eman")
            messages = agent._client.chat.completions.calls[-1]["messages"]
            self.assertIn("Ship the brief", messages[0]["content"])
            user_texts = [message["content"] for message in messages if message["role"] == "user"]
            self.assertIn("first question", user_texts)
            self.assertIn("second question", user_texts)


class _TokenUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _TokenResponse:
    def __init__(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.choices = [_Choice("ok")]
        self.model = model
        self.usage = _TokenUsage(prompt_tokens, completion_tokens)


class _TokenCompletions:
    def __init__(self, steps: list[tuple[str, int, int]]) -> None:
        self._steps = list(steps)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        model, prompt_tokens, completion_tokens = self._steps.pop(0)
        return _TokenResponse(model, prompt_tokens, completion_tokens)


class _TokenClient:
    def __init__(self, steps: list[tuple[str, int, int]]) -> None:
        self.completions = _TokenCompletions(steps)
        chat = type("Chat", (), {})()
        chat.completions = self.completions
        self.chat = chat


class TaskLogTests(unittest.TestCase):
    def test_a_failed_run_shows_duration_and_error_and_a_completed_run_does_not(self):
        done = _run_line("sifter", "task-1", "2026-11-22T12:00:00", "completed", 40, "mailbox body")
        self.assertEqual(done, "`sifter` for `task-1` at 2026-11-22T12:00:00")
        self.assertNotIn("mailbox", done)
        failed = _run_line("blogger", "chat-publish", "2026-11-22T12:01:00", "refused", 12, "Nothing was posted.")
        self.assertIn("(refused)", failed)
        self.assertIn("12 ms", failed)
        self.assertIn("Nothing was posted.", failed)
        counted = _run_line(
            "sifter",
            "task-1",
            "2026-11-22T12:00:00",
            "completed",
            40,
            "mailbox body",
            "gpt-4o-mini",
            18,
            8,
        )
        self.assertEqual(
            counted,
            "`sifter` for `task-1` at 2026-11-22T12:00:00 — gpt-4o-mini, 18 prompt tokens, 8 completion tokens",
        )
        self.assertNotIn("mailbox", counted)
        self.assertNotIn("40", counted)
        one = _run_line(
            "sifter",
            "task-1",
            "2026-11-22T12:00:00",
            "completed",
            model="gpt-4o-mini",
            prompt_tokens=1,
            completion_tokens=1,
        )
        self.assertIn("1 prompt token, 1 completion token", one)
        refused = _run_line(
            "blogger",
            "chat-publish",
            "2026-11-22T12:01:00",
            "refused",
            12,
            "Nothing was posted.",
            "gpt-4o-mini",
            2,
            1,
        )
        self.assertIn("(refused)", refused)
        self.assertIn("12 ms", refused)
        self.assertIn("Nothing was posted.", refused)
        self.assertIn("gpt-4o-mini, 2 prompt tokens, 1 completion token", refused)

    def test_a_skill_run_stores_token_totals_and_a_chat_turn_does_not(self):
        secret = "do-not-store-this-prompt-text"
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            manager = Manager(db_path=db_path)
            client = _TokenClient(
                [
                    ("gpt-4o-mini", 11, 5),
                    ("gpt-4o-mini", 3, 1),
                    ("gpt-4o-mini", 4, 2),
                    ("gpt-4o-mini", 7, 3),
                ]
            )
            outside = _TokenClient(
                [
                    ("gpt-4o-mini", 100, 50),
                    ("gpt-4o-mini", 100, 50),
                ]
            )

            class Quiet(Skill):
                name = "calculator"

                def run(self, task):
                    return {"status": "ok"}

            class Child(Skill):
                name = "scout"

                def run(self, task):
                    call_model([{"role": "user", "content": secret}], client=task["payload"]["client"])
                    call_model([{"role": "user", "content": secret + "-child"}], client=task["payload"]["client"])
                    return {"status": "child"}

            class Parent(Skill):
                name = "echo"

                def run(self, task):
                    call_model([{"role": "user", "content": secret}], client=task["payload"]["client"])
                    nested = task["ctx"].run_skill("scout", {"client": task["payload"]["client"]})
                    call_model([{"role": "user", "content": secret + "-parent"}], client=task["payload"]["client"])
                    return {"status": "ok", "nested": nested.get("status")}

            class Blogger(Skill):
                name = "blogger"
                called = False

                def run(self, task):
                    Blogger.called = True
                    return {"status": "published"}

            manager.register(Quiet())
            manager.register(Child())
            manager.register(Parent())
            manager.register(Blogger())
            with patch.dict(os.environ, {"KHURSHEED_MODEL": ""}, clear=False):
                call_model([{"role": "user", "content": secret}], client=outside)
                self.assertEqual(
                    manager._connection.execute("SELECT COUNT(*) FROM skill_runs").fetchone()[0],
                    0,
                )
                quiet = manager.run_skill("calculator", "quiet", {})
                result = manager.run_skill("echo", "totals", {"client": client})
                refused = manager.run_skill("blogger", "chat-publish", {"mode": "publish"})
                call_model([{"role": "user", "content": secret}], client=outside)
            self.assertEqual(quiet["status"], "ok")
            self.assertEqual(result["nested"], "child")
            self.assertEqual(refused["status"], "refused")
            self.assertFalse(Blogger.called)
            self.assertFalse(refused["published"])
            parent = manager._connection.execute(
                """
                SELECT model, prompt_tokens, completion_tokens, status, result_json
                FROM skill_runs WHERE task_id = ?
                """,
                ("totals",),
            ).fetchone()
            child = manager._connection.execute(
                """
                SELECT model, prompt_tokens, completion_tokens
                FROM skill_runs WHERE skill_name = ?
                """,
                ("scout",),
            ).fetchone()
            untouched = manager._connection.execute(
                """
                SELECT model, prompt_tokens, completion_tokens
                FROM skill_runs WHERE task_id = ?
                """,
                ("quiet",),
            ).fetchone()
            blocked = manager._connection.execute(
                """
                SELECT status, model, prompt_tokens, completion_tokens
                FROM skill_runs WHERE task_id = ?
                """,
                ("chat-publish",),
            ).fetchone()
            self.assertEqual(parent[0], "gpt-4o-mini")
            self.assertEqual(parent[1], 18)
            self.assertEqual(parent[2], 8)
            self.assertEqual(parent[3], "completed")
            self.assertNotIn(secret, parent[4])
            self.assertEqual(child, ("gpt-4o-mini", 7, 3))
            self.assertEqual(untouched, (None, None, None))
            self.assertEqual(blocked, ("refused", None, None, None))
            stored = manager._connection.execute("SELECT * FROM skill_runs").fetchall()
            self.assertNotIn(secret, str(stored))
            self.assertEqual(len(stored), 4)
            rows = _recent_runs(manager)
            logged = _run_line(*next(row for row in rows if row[1] == "totals"))
            self.assertEqual(
                logged,
                "`echo` for `totals` at "
                + next(row[2] for row in rows if row[1] == "totals")
                + " — gpt-4o-mini, 18 prompt tokens, 8 completion tokens",
            )
            self.assertNotIn(secret, logged)
            self.assertNotIn("$", logged)

    def test_usage_columns_are_added_without_deleting_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "test.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            for version in range(1, 14):
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, f"test-{version}", "2026-01-01T00:00:00+00:00"),
                )
            conn.execute(
                """
                CREATE TABLE skill_runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    executed_at TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'completed',
                    error_message TEXT,
                    execution_time_ms INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                """
                INSERT INTO skill_runs
                (run_id, task_id, skill_name, executed_at, result_json, status, created_at)
                VALUES ('keep-1', 'kept', 'sifter', '2026-01-01T00:00:00+00:00',
                        '{"status": "keep-this-row"}', 'completed', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.commit()
            conn.close()
            manager = Manager(db_path=db_path)
            columns = {row[1] for row in manager._connection.execute("PRAGMA table_info(skill_runs)")}
            self.assertIn("model", columns)
            self.assertIn("prompt_tokens", columns)
            self.assertIn("completion_tokens", columns)
            kept = manager._connection.execute(
                """
                SELECT run_id, result_json, model, prompt_tokens, completion_tokens
                FROM skill_runs
                """
            ).fetchone()
            self.assertEqual(kept[0], "keep-1")
            self.assertIn("keep-this-row", kept[1])
            self.assertEqual(kept[2:], (None, None, None))
            again = Manager(db_path=db_path)
            count = again._connection.execute("SELECT COUNT(*) FROM skill_runs").fetchone()[0]
            self.assertEqual(count, 1)


class ApprovalTests(unittest.TestCase):
    def _db(self, tmpdir):
        db_path = str(Path(tmpdir) / "test.db")
        Manager(db_path=db_path)
        return db_path

    def test_kill_switch_leaves_draft_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            _insert_pending(
                db_path,
                "draft-1",
                "linkedin_post_draft",
                "Draft",
                payload={"title": "Hello", "body_markdown": "Body"},
            )
            with (
                patch.dict(os.environ, {"KHURSHEED_BLOGGER_PUBLISH_ENABLED": "false"}, clear=False),
                patch("skills.blogger.requests.post") as post,
            ):
                result = approve_and_execute(db_path, "draft-1")
                post.assert_not_called()
            self.assertEqual(result["outcome"], "pending")
            self.assertEqual(_pending_status(db_path, "draft-1"), "pending")

    def test_publish_marks_executed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            _insert_pending(
                db_path,
                "draft-1",
                "linkedin_post_draft",
                "Draft",
                payload={"title": "Hello", "body_markdown": "Body", "hashtags": ["cto"]},
            )
            env = {
                "KHURSHEED_BLOGGER_PUBLISH_ENABLED": "true",
                "LINKEDIN_ACCESS_TOKEN": "token",
                "LINKEDIN_PAGE_ID": "123",
            }
            with patch.dict(os.environ, env, clear=False), patch("skills.blogger.requests.post") as post:
                post.return_value.status_code = 201
                post.return_value.json.return_value = {"id": "urn:li:share:1"}
                result = approve_and_execute(db_path, "draft-1")
                post.assert_called_once()
            self.assertEqual(result["outcome"], "executed")
            self.assertEqual(_pending_status(db_path, "draft-1"), "executed")

    def test_bill_is_acknowledged_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            _insert_pending(db_path, "bill-1", "new_bill", "Pay the host", priority=2)
            with patch("skills.blogger.requests.post") as post:
                result = approve_and_execute(db_path, "bill-1")
                post.assert_not_called()
            self.assertEqual(result["outcome"], "acknowledged")
            self.assertEqual(_pending_status(db_path, "bill-1"), "acknowledged")

    def test_a_changed_payload_drops_the_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            _insert_pending(db_path, "bill-1", "new_bill", "Pay the host", priority=2)
            approve_and_execute(db_path, "bill-1")
            self.assertEqual(_pending_status(db_path, "bill-1"), "acknowledged")
            result = revise_action_payload(db_path, "bill-1", {"amount": "40"})
            self.assertTrue(result["invalidated"])
            self.assertEqual(_pending_status(db_path, "bill-1"), "pending")
            missing = revise_action_payload(db_path, "missing", {"amount": "1"})
            self.assertEqual(missing["status"], "error")
            _insert_pending(db_path, "bill-2", "new_bill", "Still open", priority=1)
            edited = revise_action_payload(db_path, "bill-2", {"amount": "12"})
            self.assertFalse(edited["invalidated"])
            self.assertEqual(_pending_status(db_path, "bill-2"), "pending")

    def test_the_model_and_another_skill_cannot_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            manager = Manager(db_path=db_path)

            class Blogger(Skill):
                name = "blogger"
                called = False

                def run(self, task):
                    Blogger.called = True
                    return {"status": "published"}

            manager.register(Blogger())
            with patch("skills.blogger.requests.post") as post:
                direct = manager.run_skill("blogger", "chat-publish", {"mode": "publish"})
                nested = manager._skill_context.run_skill("blogger", {"mode": "publish"})
                draft = manager.run_skill("blogger", "chat-draft", {"mode": "draft", "theme": "cto"})
                post.assert_not_called()
            self.assertEqual(direct["status"], "refused")
            self.assertFalse(direct["published"])
            self.assertEqual(nested["status"], "refused")
            self.assertTrue(Blogger.called)
            self.assertEqual(draft["status"], "published")
            row = manager._connection.execute(
                "SELECT status FROM skill_runs WHERE task_id = ?",
                ("chat-publish",),
            ).fetchone()
            self.assertEqual(row[0], "refused")

    def test_a_skill_cannot_run_an_external_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            manager = Manager(db_path=db_path)

            class Blogger(Skill):
                name = "blogger"
                called = False

                def run(self, task):
                    Blogger.called = True
                    return {"status": "drafted"}

            class Radar(Skill):
                name = "cto_radar"
                called = False

                def run(self, task):
                    Radar.called = True
                    return {"opportunities": []}

            class Wrapper(Skill):
                name = "wrapper"

                def run(self, task):
                    draft = task["ctx"].run_skill("blogger", {"mode": "draft", "theme": "cto"})
                    radar = task["ctx"].run_skill("cto_radar", {})
                    return {"draft": draft, "radar": radar}

            manager.register(Blogger())
            manager.register(Radar())
            manager.register(Wrapper())
            result = manager.run_skill("wrapper", "nested-external", {})
            self.assertEqual(result["draft"]["status"], "refused")
            self.assertFalse(result["draft"]["published"])
            self.assertIn("external", result["draft"]["message"])
            self.assertFalse(Blogger.called)
            self.assertTrue(Radar.called)
            self.assertEqual(result["radar"]["opportunities"], [])
            desk_draft = manager.run_skill("blogger", "desk-draft", {"mode": "draft", "theme": "cto"})
            self.assertEqual(desk_draft["status"], "drafted")
            self.assertTrue(Blogger.called)

    def test_too_many_model_calls_do_not_run_the_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            manager = Manager(db_path=db_path)

            class Advisor(Skill):
                name = "ceo_advisor"
                called = False

                def run(self, task):
                    Advisor.called = True
                    return {"status": "ok"}

            class Calendar(Skill):
                name = "calendar_prep"
                called = False

                def run(self, task):
                    Calendar.called = True
                    return {"meetings": []}

            manager.register(Advisor())
            manager.register(Calendar())
            over = manager.run_skill("ceo_advisor", "too-many", {"question": "now", "model_calls": 3})
            self.assertEqual(over["status"], "refused")
            self.assertIn("2 model calls", over["message"])
            self.assertFalse(Advisor.called)
            row = manager._connection.execute(
                "SELECT status FROM skill_runs WHERE task_id = ?",
                ("too-many",),
            ).fetchone()
            self.assertEqual(row[0], "refused")
            within = manager.run_skill("ceo_advisor", "within", {"question": "now", "model_calls": 2})
            self.assertTrue(Advisor.called)
            self.assertEqual(within["status"], "ok")
            blocked = manager.run_skill("calendar_prep", "calendar", {"model_calls": 1})
            self.assertEqual(blocked["status"], "refused")
            self.assertFalse(Calendar.called)
            quiet = manager.run_skill("calendar_prep", "calendar-read", {})
            self.assertEqual(quiet["meetings"], [])
            self.assertTrue(Calendar.called)

    def test_the_ceo_skill_does_not_run_another_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = self._db(tmpdir)
            manager = Manager(db_path=db_path)

            class Echo(Skill):
                name = "echo"
                called = False

                def run(self, task):
                    Echo.called = True
                    return {"status": "ok"}

            class Advisor(Skill):
                name = "ceo_advisor"

                def run(self, task):
                    return task["ctx"].run_skill("echo", {})

            manager.register(Echo())
            manager.register(Advisor())
            result = manager.run_skill("ceo_advisor", "ceo", {"question": "now"})
            self.assertEqual(result["status"], "refused")
            self.assertIn("CEO skill", result["message"])
            self.assertFalse(Echo.called)

    def test_live_skills_are_declared_and_leftovers_are_not(self):
        self.assertEqual(
            set(DECLARATIONS),
            {
                "icp_finder",
                "cto_radar",
                "lead_scout",
                "icp_prospector",
                "outreach_draft",
                "sifter",
                "calendar_prep",
                "blogger",
                "ceo_advisor",
            },
        )
        for name in ("echo", "timestamp", "calculator", "weather", "file_analyzer", "scout"):
            self.assertNotIn(name, DECLARATIONS)
        self.assertEqual(DECLARATIONS["blogger"]["side_effect"], EXTERNAL)
        self.assertEqual(DECLARATIONS["blogger"]["max_model_calls"], 1)
        self.assertEqual(DECLARATIONS["ceo_advisor"]["max_model_calls"], 2)
        self.assertEqual(DECLARATIONS["icp_finder"]["max_model_calls"], 1)
        self.assertEqual(DECLARATIONS["icp_prospector"]["max_model_calls"], 2)
        self.assertEqual(DECLARATIONS["sifter"]["max_model_calls"], 100)
        self.assertEqual(DECLARATIONS["sifter"]["side_effect"], REVERSIBLE)
        for name in ("lead_scout", "calendar_prep"):
            self.assertEqual(DECLARATIONS[name]["side_effect"], READ_ONLY)
            self.assertEqual(DECLARATIONS[name]["max_model_calls"], 0)
        for name in ("cto_radar", "outreach_draft"):
            self.assertEqual(DECLARATIONS[name]["max_model_calls"], 0)


class DeskLabelTests(unittest.TestCase):
    def test_buttons_and_chat_skip_material_names(self):
        from streamlit.testing.v1 import AppTest

        source = Path(__file__).resolve().parent.parent.joinpath("hey_eman_app.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(":material/", source)
        self.assertIn('st.button("Config", use_container_width=True)', source)
        families = [
            line.strip()
            for line in source.splitlines()
            if "font-family" in line
        ]
        self.assertEqual(
            families,
            [
                'font-family: "Material Symbols Rounded" !important;',
                'font-family: "Material Symbols Outlined" !important;',
            ],
        )
        self.assertIn('[data-testid="stIconMaterial"]', source)
        self.assertNotIn("button, summary, *", source)

        script = """
import streamlit as st
import hey_eman_app as desk

desk._render_chips = lambda manager: None

class _Manager:
    _db_path = ":memory:"

desk._render_header(_Manager())
st.button("Config", use_container_width=True)
desk._render_turn({
    "user_content": "What's urgent?",
    "assistant_content": "Here's what's urgent:",
})
"""
        app = AppTest.from_string(script, default_timeout=30)
        app.run()
        self.assertEqual(len(app.exception), 0)
        labels = [button.label for button in app.button]
        self.assertIn("Run morning brief", labels)
        self.assertIn("Check mail now", labels)
        self.assertIn("Config", labels)
        for button in app.button:
            self.assertNotIn(":material/", button.label)
            self.assertFalse(button.proto.icon)
        avatars = [message.avatar for message in app.chat_message]
        self.assertEqual(avatars, ["👤", "✏"])


if __name__ == "__main__":
    unittest.main()
