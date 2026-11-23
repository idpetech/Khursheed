"""Local MCP listener for the Enaam desk.

Binds 127.0.0.1:8765 only. That port is not the desk (8510), and it is not
8501, 8502, 5001, or 8080. The listener starts when KHURSHEED_MCP_SERVER=1.
A normal desk start leaves it off. It uses the same SQLite file as the desk
and does not import the older enaam MCP server.

GET /health returns {"status": "healthy"}.
POST / accepts {"method", "params"} and returns that method's JSON itself.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from llm_agent import HeyEmanAgent
from mcp_registry import MCPRegistry
from manager import Manager
from runtime import resolve_db_path
from skills_bootstrap import register_default_skills


logger = logging.getLogger(__name__)

# Local only. Do not bind this on the public Railway port.
DESK_MCP_HOST = "127.0.0.1"
DESK_MCP_PORT = 8765
_MAX_BODY = 65536

_started = False
_server: ThreadingHTTPServer | None = None
_lock = threading.Lock()


class _BadRequest(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class DeskState:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.manager = Manager(db_path=db_path)
        register_default_skills(self.manager)

    def reload_connections(self) -> None:
        try:
            registry = MCPRegistry.load(db_path=self.db_path)
        except Exception:
            logger.warning("MCP connections could not be reloaded")
            return
        self.manager._mcp_registry = registry
        self.manager._skill_context._mcp_registry = registry


def _enabled() -> bool:
    return os.getenv("KHURSHEED_MCP_SERVER", "").strip().lower() in {"1", "true", "yes", "on"}


def build_server(
    db_path: str | Path | None = None,
    host: str = DESK_MCP_HOST,
    port: int | None = None,
) -> ThreadingHTTPServer:
    resolved = str(resolve_db_path(db_path or "khursheed.db"))
    state = DeskState(resolved)
    handler = _handler_class(state)
    chosen = DESK_MCP_PORT if port is None else port
    server = ThreadingHTTPServer((host, chosen), handler)
    server.daemon_threads = True
    return server


def start_if_enabled() -> None:
    """Open the local listener once per process, and only when the flag is set."""
    global _started, _server
    if not _enabled():
        return
    with _lock:
        if _started:
            return
        _started = True
    try:
        server = build_server()
    except OSError:
        logger.warning(
            "Local MCP server could not listen on %s:%s",
            DESK_MCP_HOST,
            DESK_MCP_PORT,
        )
        return
    thread = threading.Thread(target=server.serve_forever, name="desk-mcp", daemon=True)
    server._desk_thread = thread  # type: ignore[attr-defined]
    with _lock:
        _server = server
    thread.start()


def stop_listener() -> None:
    """Stop a listener this process started. Safe when none is running."""
    global _started, _server
    with _lock:
        server = _server
        _server = None
        _started = False
    if server is None:
        return
    thread = getattr(server, "_desk_thread", None)
    server.shutdown()
    server.server_close()
    if thread is not None:
        thread.join(timeout=2)


def dispatch(state: DeskState, payload: dict) -> tuple[int, dict]:
    method = payload.get("method")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if not isinstance(method, str) or not method.strip():
        return 400, {"error": "The request needs a method."}
    name = method.strip()
    state.reload_connections()
    if name == "list_skills":
        return 200, {"skills": state.manager.list_skill_names()}
    if name == "ask":
        return _ask(state, params)
    if name == "run_skill":
        return _run_skill(state, params)
    return 404, {"error": "Unknown method."}


def _ask(state: DeskState, params: dict) -> tuple[int, dict]:
    """Read a question on the hey-eman session. This does not approve an action."""
    query = str(params.get("query") or params.get("question") or "").strip()
    if not query:
        return 400, {"error": "Ask needs a question."}
    try:
        answer = HeyEmanAgent(state.manager).respond(query, session_id="hey-eman")
    except Exception:
        logger.warning("MCP ask failed")
        answer = "The question could not be answered. Nothing was sent or posted."
    return 200, {"answer": answer}


def _run_skill(state: DeskState, params: dict) -> tuple[int, dict]:
    """Run only through Manager.run_skill. A refusal is not a successful post."""
    skill_name = str(params.get("skill_name") or "").strip()
    if not skill_name:
        return 400, {"error": "run_skill needs a skill name."}
    if "input" in params:
        payload = params.get("input")
    else:
        payload = params.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return 400, {"error": "The skill input must be an object."}
    task_id = f"mcp-{skill_name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    try:
        result = state.manager.run_skill(skill_name, task_id, payload)
    except KeyError:
        return 404, {"error": f"Skill {skill_name} is not registered."}
    except Exception:
        logger.warning("MCP run_skill failed")
        return 500, {"error": "The skill could not be run."}
    if isinstance(result, dict) and result.get("status") == "refused":
        return 403, result
    if not isinstance(result, dict):
        return 200, {"value": result}
    return 200, result


def _handler_class(state: DeskState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._send(200, {"status": "healthy"})
                return
            self._send(404, {"error": "Not found."})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in {"", "/"}:
                self._send(404, {"error": "Not found."})
                return
            try:
                payload = self._read_json()
            except _BadRequest as exc:
                self._send(exc.status, {"error": exc.message})
                return
            status, body = dispatch(state, payload)
            self._send(status, body)

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length < 0 or length > _MAX_BODY:
                raise _BadRequest(413, "The request is too large.")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                raise _BadRequest(400, "The request was not JSON.")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise _BadRequest(400, "The request was not JSON.") from None
            if not isinstance(payload, dict):
                raise _BadRequest(400, "The request was not a JSON object.")
            return payload

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            logger.debug("desk mcp " + fmt, *args)

    return Handler
