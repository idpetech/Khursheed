"""Persist Hey Eman turns in khursheed.db."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC
from datetime import datetime
from pathlib import Path

from runtime import resolve_db_path


def load_recent_turns(
    session_id: str,
    db_path: str | Path = "khursheed.db",
    limit: int = 8,
) -> list[dict[str, str]]:
    """Return up to `limit` turns, oldest first."""
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        cursor = conn.execute(
            """
            SELECT user_content, assistant_content
            FROM chat_turns
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    rows.reverse()
    return [{"user_content": row[0], "assistant_content": row[1]} for row in rows]


def load_turns(
    session_id: str,
    db_path: str | Path = "khursheed.db",
    limit: int = 200,
) -> list[dict[str, str]]:
    """Return up to `limit` turns (oldest first), including created_at."""
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        cursor = conn.execute(
            """
            SELECT user_content, assistant_content, created_at
            FROM chat_turns
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    rows.reverse()
    return [
        {"user_content": row[0], "assistant_content": row[1], "created_at": row[2]}
        for row in rows
    ]


def record_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    db_path: str | Path = "khursheed.db",
) -> str:
    resolved = resolve_db_path(db_path)
    turn_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO chat_turns (
                    turn_id, session_id, user_content, assistant_content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (turn_id, session_id, user_content, assistant_content, created_at),
            )
        return turn_id
    finally:
        conn.close()
