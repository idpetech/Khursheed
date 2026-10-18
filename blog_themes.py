"""Blog theme queue.

Lets the user line up future LinkedIn post themes (from the UI) that the
blogger skill consumes when asked to pick a theme automatically.

Simple, additive SQLite table in the existing khursheed.db. No destructive
migrations: the table is created lazily on first use.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

DEFAULT_DB_PATH = "khursheed.db"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_theme_queue (
            theme_id TEXT PRIMARY KEY,
            theme TEXT NOT NULL,
            context_json TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )


def add_theme(
    theme: str,
    context: dict[str, Any] | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """Queue a theme for a future post. Returns the new theme_id."""
    theme = (theme or "").strip()
    if not theme:
        raise ValueError("theme must be a non-empty string")
    theme_id = f"theme-{uuid.uuid4().hex[:12]}"
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO blog_theme_queue (theme_id, theme, context_json, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (
                theme_id,
                theme,
                json.dumps(context, default=str) if context else None,
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return theme_id


def list_themes(
    status: str | None = None, db_path: str = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    """List queued themes, newest first. Optionally filter by status."""
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        if status:
            rows = conn.execute(
                "SELECT * FROM blog_theme_queue WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM blog_theme_queue ORDER BY created_at DESC"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def next_pending_theme(db_path: str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Return the oldest pending theme (FIFO) without consuming it."""
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT * FROM blog_theme_queue WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def mark_used(theme_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Mark a queued theme as used (reversible: status only, row retained)."""
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        conn.execute(
            "UPDATE blog_theme_queue SET status = 'used', used_at = ? WHERE theme_id = ?",
            (datetime.now(UTC).isoformat(), theme_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_theme(theme_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Remove a queued theme entirely."""
    conn = _connect(db_path)
    try:
        _ensure_table(conn)
        conn.execute("DELETE FROM blog_theme_queue WHERE theme_id = ?", (theme_id,))
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    raw = data.get("context_json")
    if raw:
        try:
            data["context"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data["context"] = None
    else:
        data["context"] = None
    return data
