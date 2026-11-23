"""Inbound Telegram for the live desk.

One daemon thread in the desk process. It starts when TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are both set, including on a laptop. It does not start a
second process. Missing config leaves the desk running and the thread idle.

The first start confirms updates already waiting and does not answer them.
Later text from TELEGRAM_CHAT_ID is answered on the hey-eman session. Every
other chat is ignored. The bot token is never logged.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import certifi

from desk_settings import get_setting
from desk_settings import set_setting
from runtime import resolve_db_path


logger = logging.getLogger(__name__)

OFFSET_KEY = "telegram_update_offset"
LONG_POLL_SECONDS = 25
REPLY_LIMIT = 3500

_started = False
_lock = threading.Lock()


class TelegramPollError(Exception):
    """A poll failure whose message does not include the bot token."""


def start_if_configured() -> bool:
    """Start one poll thread. Later calls, and a missing token, do nothing."""
    global _started
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    with _lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_loop, name="telegram-inbox", daemon=True).start()
    return True


def reset_for_tests() -> None:
    global _started
    with _lock:
        _started = False


def truncate_reply(content: str) -> str:
    text = (content or "").strip() or "No reply."
    if len(text) <= REPLY_LIMIT:
        return text
    return text[: REPLY_LIMIT - 1].rstrip() + "…"


def read_offset(db_path: str | Path) -> int | None:
    raw = get_setting(db_path, OFFSET_KEY, "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def next_offset(updates: list) -> int | None:
    highest = None
    for update in updates or []:
        if not isinstance(update, dict):
            continue
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            continue
        candidate = update_id + 1
        if highest is None or candidate > highest:
            highest = candidate
    return highest


def prime_offset(db_path: str | Path, token: str) -> int:
    """Confirm updates already waiting. Do not answer them."""
    saved = read_offset(db_path)
    if saved is not None:
        return saved
    offset: int | None = None
    confirmed = 0
    for _ in range(20):
        updates = fetch_updates(token, offset, 0)
        nxt = next_offset(updates)
        if nxt is None:
            break
        if offset is not None and nxt <= offset:
            break
        offset = nxt
        confirmed = nxt
    set_setting(db_path, OFFSET_KEY, str(confirmed))
    return confirmed


def fetch_updates(token: str, offset: int | None, timeout: int) -> list:
    body: dict[str, object] = {
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        body["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=timeout + 15, context=ssl_ctx) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise TelegramPollError(f"Telegram poll failed: HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise TelegramPollError("Telegram poll could not connect.") from None
    except TimeoutError:
        raise TelegramPollError("Telegram poll did not answer in time.") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise TelegramPollError("Telegram poll returned an unreadable reply.") from None
    if not isinstance(data, dict) or not data.get("ok"):
        raise TelegramPollError("Telegram poll was rejected.")
    result = data.get("result")
    if not isinstance(result, list):
        return []
    return result


def send_reply(text: str, token: str, chat_id: str) -> None:
    """One message back to the configured chat. The token is not logged."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": truncate_reply(text),
        "disable_web_page_preview": True,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=20, context=ssl_ctx) as response:
            if response.status >= 400:
                raise TelegramPollError(f"Telegram reply failed: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        raise TelegramPollError(f"Telegram reply failed: HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise TelegramPollError("Telegram reply could not be sent.") from None


def apply_updates(
    updates: list,
    *,
    chat_id: str,
    reply: Callable[[str], str],
    send: Callable[[str], None],
) -> int | None:
    """Answer text from one chat. Advance past every update, including ignored ones."""
    allowed = str(chat_id).strip()
    if not isinstance(updates, list):
        return None
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if str(chat.get("id", "")) != allowed:
            continue
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            answer = reply(text.strip())
        except Exception:
            logger.warning("Telegram message could not be answered")
            answer = "That could not be answered. Nothing was sent or posted."
        try:
            send(str(answer) if answer is not None else "")
        except TelegramPollError as exc:
            logger.warning("%s", exc)
        except Exception:
            logger.warning("Telegram reply could not be sent")
    return next_offset(updates)


def route_text(text: str, manager=None, agent=None) -> str:
    """Ask Enaam's path. Skill gates and CEO routing stay in that function."""
    from hey_eman_app import _answer
    from llm_agent import HeyEmanAgent
    from manager import Manager
    from mcp_registry import MCPRegistry
    from skills_bootstrap import register_default_skills

    owns_manager = manager is None
    if manager is None:
        manager = Manager()
        register_default_skills(manager)
    else:
        try:
            registry = MCPRegistry.load(db_path=manager._db_path)
            manager._mcp_registry = registry
            manager._skill_context._mcp_registry = registry
        except Exception:
            logger.warning("MCP connections could not be reloaded for Telegram")
    if agent is None:
        agent = HeyEmanAgent(manager)
    try:
        return _answer(text, manager, agent)
    finally:
        if owns_manager:
            manager.close()


def _loop() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    db_path = resolve_db_path("khursheed.db")
    try:
        from llm_agent import HeyEmanAgent
        from manager import Manager
        from skills_bootstrap import register_default_skills

        manager = Manager()
        register_default_skills(manager)
        agent = HeyEmanAgent(manager)
    except Exception:
        logger.warning("Telegram poll could not open the desk")
        return

    def reply(text: str) -> str:
        return route_text(text, manager, agent)

    try:
        offset = prime_offset(db_path, token)
    except TelegramPollError as exc:
        logger.warning("%s", exc)
        offset = read_offset(db_path) or 0
    while True:
        try:
            updates = fetch_updates(token, offset, LONG_POLL_SECONDS)
            nxt = apply_updates(
                updates,
                chat_id=chat_id,
                reply=reply,
                send=lambda text: send_reply(text, token, chat_id),
            )
            if nxt is not None:
                offset = nxt
                set_setting(db_path, OFFSET_KEY, str(offset))
        except TelegramPollError as exc:
            logger.warning("%s", exc)
            time.sleep(5)
        except Exception:
            logger.warning("Telegram poll failed")
            time.sleep(5)
