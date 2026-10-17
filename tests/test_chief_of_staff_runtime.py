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
from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from open_loops import emit_open_loop
from open_loops import list_open_loops
from principal_profile import principal_prompt_block
from runtime import remove_test_pending_actions
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
            self.assertIn("1. Handle priority action: Pay the host", report)
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


if __name__ == "__main__":
    unittest.main()
