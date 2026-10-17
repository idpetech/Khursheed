"""Open loops: conversations and follow-ups that are not side effects."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime import resolve_db_path


logger = logging.getLogger(__name__)


def emit_open_loop(
    source: str,
    source_key: str,
    title: str,
    detail: str | None = None,
    due_at: str | None = None,
    db_path: str | Path = "khursheed.db",
) -> str:
    """Insert a loop, or return the existing id when source_key already exists."""
    resolved = resolve_db_path(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            existing = conn.execute(
                "SELECT loop_id FROM open_loops WHERE source_key = ?",
                (source_key,),
            ).fetchone()
            if existing:
                return existing[0]
            loop_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO open_loops (
                    loop_id, source, source_key, title, detail, due_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (loop_id, source, source_key, title, detail, due_at, now, now),
            )
            return loop_id
    except sqlite3.Error as exc:
        logger.warning("Could not write open loop %s: %s", source_key, exc)
        return ""
    finally:
        conn.close()


def list_open_loops(
    db_path: str | Path = "khursheed.db",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return open loops, oldest first."""
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        cursor = conn.execute(
            """
            SELECT loop_id, source, source_key, title, detail, due_at, status, created_at
            FROM open_loops
            WHERE status = 'open'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        columns = [
            "loop_id",
            "source",
            "source_key",
            "title",
            "detail",
            "due_at",
            "status",
            "created_at",
        ]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        logger.warning("Could not read open loops: %s", exc)
        return []
    finally:
        conn.close()


def record_cto_opportunities(
    opportunities: list[dict[str, Any]],
    db_path: str | Path = "khursheed.db",
) -> int:
    """Write one loop per CTO opportunity, deduped on URL."""
    written = 0
    for opportunity in opportunities:
        url = (opportunity.get("url") or "").strip()
        title = (opportunity.get("title") or url or "").strip()
        if not title:
            continue
        source_key = f"cto:{url or title}"
        detail = opportunity.get("snippet") or ""
        loop_id = emit_open_loop(
            source="cto_radar",
            source_key=source_key,
            title=title,
            detail=detail[:500] if detail else None,
            db_path=db_path,
        )
        if loop_id:
            written += 1
    return written


def record_icp_companies(
    companies: list[dict[str, Any]],
    db_path: str | Path = "khursheed.db",
) -> int:
    """Write one loop per ICP company, deduped on name."""
    written = 0
    for company in companies:
        name = (company.get("name") or company.get("company_name") or "").strip()
        if not name:
            continue
        source_key = f"icp:{name.lower()}"
        detail = company.get("rationale") or ""
        loop_id = emit_open_loop(
            source="icp_prospector",
            source_key=source_key,
            title=name,
            detail=detail[:500] if detail else None,
            db_path=db_path,
        )
        if loop_id:
            written += 1
    return written
