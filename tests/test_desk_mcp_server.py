import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from chat_memory import load_turns
from desk_mcp_server import DESK_MCP_HOST
from desk_mcp_server import DESK_MCP_PORT
from desk_mcp_server import build_server
from desk_mcp_server import start_if_enabled
from desk_mcp_server import stop_listener
from enaam_mcp_client import EnaamMCPClient


class DeskMCPServerTests(unittest.TestCase):
    def setUp(self):
        stop_listener()

    def tearDown(self):
        stop_listener()

    def test_default_is_local_and_off_the_desk_ports(self):
        source = Path(__file__).resolve().parents[1].joinpath("desk_mcp_server.py").read_text(encoding="utf-8")
        self.assertNotIn("enaam.mcp", source)
        self.assertNotIn("approve_and_execute", source)
        self.assertEqual(DESK_MCP_HOST, "127.0.0.1")
        self.assertEqual(DESK_MCP_PORT, 8765)
        self.assertNotIn(DESK_MCP_PORT, {8510, 8501, 8502, 5001, 8080})
        import desk_mcp_server

        self.assertIsNone(desk_mcp_server._server)

    def test_flag_off_does_not_listen(self):
        with patch.dict(os.environ, {"KHURSHEED_MCP_SERVER": ""}, clear=False):
            start_if_enabled()
        import desk_mcp_server

        self.assertIsNone(desk_mcp_server._server)

    def test_health_skills_ask_and_refused_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            server = build_server(db_path=db_path, port=0)
            thread = threading.Thread(target=server.serve_forever, name="desk-mcp-test", daemon=True)
            thread.start()
            host, port = server.server_address
            base = f"http://{host}:{port}"
            try:
                status, health = _request("GET", f"{base}/health")
                self.assertEqual(status, 200)
                self.assertEqual(health, {"status": "healthy"})
                client = EnaamMCPClient(base)
                self.assertEqual(client.health()["status"], "healthy")
                listed = client.request("list_skills")
                self.assertIn("echo", listed["skills"])
                self.assertIn("blogger", listed["skills"])
                self.assertNotIn("result", listed)
                echoed = client.request(
                    "run_skill",
                    {"skill_name": "echo", "input": {"message": "hi"}},
                )
                self.assertEqual(echoed["message"], "hi")
                self.assertNotIn("result", echoed)
                refused_status, refused = _request(
                    "POST",
                    base,
                    {
                        "method": "run_skill",
                        "params": {
                            "skill_name": "blogger",
                            "input": {"mode": "publish", "theme": "test"},
                        },
                    },
                )
                self.assertEqual(refused_status, 403)
                self.assertEqual(refused["status"], "refused")
                self.assertFalse(refused["published"])
                self.assertIn("Nothing was posted", refused["message"])
                limited_status, limited = _request(
                    "POST",
                    base,
                    {
                        "method": "run_skill",
                        "params": {
                            "skill_name": "blogger",
                            "input": {"mode": "draft", "theme": "test", "model_calls": 5},
                        },
                    },
                )
                self.assertGreaterEqual(limited_status, 400)
                self.assertIn("was not called", limited["message"])

                def fake_respond(self, query, session_id="hey-eman"):
                    from chat_memory import record_turn

                    record_turn(session_id, query, "desk answer", db_path=self._db_path)
                    fake_respond.session_id = session_id
                    return "desk answer"

                with patch("desk_mcp_server.HeyEmanAgent.respond", fake_respond):
                    ask_status, ask_body = _request(
                        "POST",
                        base,
                        {"method": "ask", "params": {"query": "What is waiting?"}},
                    )
                self.assertEqual(ask_status, 200)
                self.assertEqual(ask_body, {"answer": "desk answer"})
                self.assertEqual(fake_respond.session_id, "hey-eman")
                turns = load_turns("hey-eman", db_path=db_path)
                self.assertEqual(turns[-1]["user_content"], "What is waiting?")
                self.assertEqual(turns[-1]["assistant_content"], "desk answer")
                with sqlite3.connect(db_path) as conn:
                    statuses = [
                        row[0]
                        for row in conn.execute(
                            "SELECT status FROM skill_runs WHERE skill_name = 'blogger'"
                        )
                    ]
                self.assertEqual(statuses, ["refused", "refused"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_flag_on_listens_on_localhost_and_stops(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            with patch.dict(
                os.environ,
                {"KHURSHEED_MCP_SERVER": "1", "KHURSHEED_DB_PATH": db_path},
                clear=False,
            ):
                with patch("desk_mcp_server.DESK_MCP_PORT", 0):
                    start_if_enabled()
            import desk_mcp_server

            server = desk_mcp_server._server
            self.assertIsNotNone(server)
            try:
                host, port = server.server_address
                self.assertEqual(host, "127.0.0.1")
                self.assertNotEqual(port, 8510)
                status, body = _request("GET", f"http://{host}:{port}/health")
                self.assertEqual((status, body), (200, {"status": "healthy"}))
            finally:
                stop_listener()
            self.assertIsNone(desk_mcp_server._server)


def _request(method: str, url: str, payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    last_error = None
    for _ in range(30):
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(last_error)


if __name__ == "__main__":
    unittest.main()
