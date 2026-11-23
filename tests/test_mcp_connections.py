import logging
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from desk_settings import get_setting
from enaam_mcp_client import EnaamMCPClient
from manager import Manager
from mcp_registry import MCPRegistry
from mcp_registry import add_mcp_server
from mcp_registry import health_message
from mcp_registry import mcp_servers
from mcp_registry import remove_mcp_server


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


class MCPClientTests(unittest.TestCase):
    def test_bearer_is_sent_when_the_env_var_is_set_and_never_logged(self):
        logs = _capture("enaam_mcp_client")
        with patch.dict(os.environ, {"INSIGHT_VAULT_API_KEY": "unit-test-key"}):
            client = EnaamMCPClient(
                "http://127.0.0.1:9",
                auth_env="INSIGHT_VAULT_API_KEY",
                health_path="ready",
            )
            with patch("enaam_mcp_client.requests.get", return_value=_Response({"status": "healthy"})) as get:
                self.assertEqual(client.health()["status"], "healthy")
            with patch("enaam_mcp_client.requests.post", return_value=_Response({"items": [{"id": 1}]})) as post:
                result = client.request("retrieve_biases", {"theme": "cto"})
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:9/ready")
        self.assertEqual(get.call_args.kwargs["headers"].get("Authorization"), "Bearer unit-test-key")
        body = post.call_args.kwargs["json"]
        self.assertEqual(
            body,
            {"method": "retrieve_biases", "params": {"theme": "cto"}, "response_type": "json"},
        )
        self.assertEqual(post.call_args.kwargs["headers"].get("Authorization"), "Bearer unit-test-key")
        self.assertEqual(result["items"][0]["id"], 1)
        self.assertNotIn("unit-test-key", logs.getvalue())

    def test_blank_or_unset_env_sends_no_authorization_header(self):
        client = EnaamMCPClient("http://127.0.0.1:9", auth_env="")
        with patch("enaam_mcp_client.requests.get", return_value=_Response({"status": "healthy"})) as get:
            client.health()
        self.assertEqual(get.call_args.kwargs["headers"], {})
        with patch.dict(os.environ, {"MISSING_MCP_KEY": ""}, clear=False):
            bare = EnaamMCPClient("http://127.0.0.1:9", auth_env="MISSING_MCP_KEY")
            with patch("enaam_mcp_client.requests.post", return_value=_Response({})) as post:
                bare.request("list_skills")
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_a_closed_port_fails_in_plain_words(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with patch.dict(os.environ, {"INSIGHT_VAULT_API_KEY": "unit-test-key"}):
            message = health_message(
                {
                    "alias": "down",
                    "display_name": "down",
                    "base_url": f"http://127.0.0.1:{port}",
                    "auth_env": "INSIGHT_VAULT_API_KEY",
                    "health_path": "/health",
                }
            )
        self.assertIn("could not be reached", message)
        self.assertNotIn("unit-test-key", message)
        self.assertNotIn("Bearer", message)


class MCPRegistryTests(unittest.TestCase):
    def test_empty_setting_seeds_the_three_aliases_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            rows = mcp_servers(db_path)
            aliases = [row["alias"] for row in rows]
            self.assertEqual(aliases, ["business_assessment", "insight_vault", "cto_dashboard"])
            vault = next(row for row in rows if row["alias"] == "insight_vault")
            self.assertEqual(vault["base_url"], "http://localhost:8501")
            self.assertEqual(vault["auth_env"], "INSIGHT_VAULT_API_KEY")
            self.assertIn("insight_vault", get_setting(db_path, "mcp_servers"))
            again = mcp_servers(db_path)
            self.assertEqual([row["alias"] for row in again], aliases)

    def test_saved_list_wins_and_an_empty_list_is_not_reseeded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            added = add_mcp_server(db_path, "local_notes", "http://127.0.0.1:9", "LOCAL_NOTES_API_KEY")
            self.assertEqual(added["status"], "ok")
            # The first add seeds the file, then appends. Replace with only the custom row.
            from desk_settings import set_setting

            set_setting(
                db_path,
                "mcp_servers",
                '[{"alias":"local_notes","base_url":"http://127.0.0.1:9","auth_env":"LOCAL_NOTES_API_KEY"}]',
            )
            registry = MCPRegistry.load(db_path=db_path)
            self.assertEqual(registry.list_aliases(), ["local_notes"])
            handle = registry.get_handle("local_notes")
            self.assertEqual(handle.auth_env, "LOCAL_NOTES_API_KEY")
            self.assertEqual(handle._client._auth_env, "LOCAL_NOTES_API_KEY")
            set_setting(db_path, "mcp_servers", "[]")
            self.assertEqual(MCPRegistry.load(db_path=db_path).list_aliases(), [])

    def test_blank_setting_falls_back_to_the_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "t.db"
            from desk_settings import set_setting

            set_setting(db_path, "mcp_servers", "   ")
            aliases = MCPRegistry.load(db_path=db_path).list_aliases()
            self.assertEqual(aliases, ["business_assessment", "insight_vault", "cto_dashboard"])

    def test_custom_alias_updates_and_manager_reads_the_saved_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            self.assertEqual(
                add_mcp_server(db_path, "Bad Name", "http://127.0.0.1:9", "")["status"],
                "error",
            )
            self.assertEqual(
                add_mcp_server(db_path, "notes", "http://user:secret@127.0.0.1:9", "")["status"],
                "error",
            )
            add_mcp_server(db_path, "notes", "http://127.0.0.1:9", "")
            updated = add_mcp_server(db_path, "notes", "http://127.0.0.1:10", "NOTES_API_KEY")
            self.assertIn("Updated notes", updated["message"])
            rows = {row["alias"]: row for row in mcp_servers(db_path)}
            self.assertEqual(rows["notes"]["base_url"], "http://127.0.0.1:10")
            self.assertEqual(rows["notes"]["auth_env"], "NOTES_API_KEY")
            self.assertIn("Removed notes", remove_mcp_server(db_path, "notes")["message"])
            self.assertNotIn("notes", {row["alias"] for row in mcp_servers(db_path)})
            manager = Manager(db_path=db_path)
            self.assertIn("insight_vault", manager._mcp_registry.list_aliases())
            manager.close()


class MCPConfigUITests(unittest.TestCase):
    def test_bills_stay_under_mail_days_and_mcp_controls_are_in_config(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "t.db")
            root = str(Path(__file__).resolve().parents[1])
            script = f"""
import sys
sys.path.insert(0, {root!r})
from manager import Manager
from hey_eman_app import _render_mail_page, _render_research

db = {db_path!r}
manager = Manager(db_path=db)
_render_research(db)
_render_mail_page(manager)
"""
            with patch.dict(os.environ, {"INSIGHT_VAULT_API_KEY": "unit-test-key-should-not-render"}):
                app = AppTest.from_string(script, default_timeout=30)
                app.run()
            labels = _ordered_labels(app)
            mail = labels.index("Days of mail to scan")
            bills = next(index for index, label in enumerate(labels) if label.startswith("Bills and subscriptions"))
            connection = labels.index("Connection name")
            research = labels.index("Days of research to include in the brief")
            self.assertLess(mail, bills)
            self.assertLess(bills, connection)
            self.assertLess(connection, research)
            self.assertEqual(sum(label.startswith("Bills and subscriptions") for label in labels), 1)
            self.assertIn("Base URL", labels)
            self.assertIn("API key env var", labels)
            self.assertIn("Add connection", labels)
            self.assertIn("Check health", labels)
            text = "\n".join(labels)
            self.assertIn("insight_vault", text)
            self.assertIn("INSIGHT_VAULT_API_KEY", text)
            self.assertNotIn("unit-test-key-should-not-render", text)
            name = next(item for item in app.text_input if item.label == "Connection name")
            url = next(item for item in app.text_input if item.label == "Base URL")
            env_name = next(item for item in app.text_input if item.label == "API key env var")
            name.set_value("local_notes")
            url.set_value("http://127.0.0.1:9")
            env_name.set_value("LOCAL_NOTES_API_KEY")
            add = next(item for item in app.button if item.label == "Add connection")
            add.click().run()
            saved = {row["alias"]: row for row in mcp_servers(db_path)}
            self.assertEqual(saved["local_notes"]["base_url"], "http://127.0.0.1:9")
            self.assertEqual(saved["local_notes"]["auth_env"], "LOCAL_NOTES_API_KEY")
            self.assertIn("insight_vault", saved)


def _ordered_labels(app) -> list[str]:
    found = []
    for node in app._tree:
        kind = getattr(node, "type", "")
        if kind in {"markdown", "caption"}:
            value = getattr(node, "value", "")
            if isinstance(value, str) and value.strip():
                found.append(value.strip())
            continue
        label = getattr(node, "label", None)
        if isinstance(label, str) and label.strip():
            found.append(label.strip())
    return found


def _capture(logger_name: str) -> "logging.handlers.MemoryHandler | object":
    import io

    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    logger = logging.getLogger(logger_name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    class _Buffer:
        def getvalue(self):
            return buffer.getvalue()

        def __del__(self):
            logger.removeHandler(handler)

    return _Buffer()


if __name__ == "__main__":
    unittest.main()
