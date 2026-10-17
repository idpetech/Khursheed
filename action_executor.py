"""Finish an approved pending action, or leave it pending when the side effect cannot run."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime import resolve_db_path
from skills.blogger import BloggerSkill


LINKEDIN_DRAFT = "linkedin_post_draft"


def approve_and_execute(
    db_path: str | Path,
    action_id: str,
    reviewed_by: str = "user",
) -> dict[str, Any]:
    """Execute a pending action, then record the outcome."""
    resolved = resolve_db_path(db_path)
    action = _fetch_pending(resolved, action_id)
    if action is None:
        return {
            "status": "error",
            "message": "Action not found or already processed",
            "action_id": action_id,
        }
    payload = json.loads(action["payload_json"] or "{}")
    outcome = execute_pending_action(action["action_type"], payload)
    apply_approval_outcome(resolved, action_id, reviewed_by, outcome)
    if outcome["status"] == "pending":
        reason = outcome.get("reason") or "pending"
        messages = {
            "publish_disabled": "Publish is disabled. The draft stays pending.",
            "linkedin_credentials_missing": "LinkedIn credentials are missing. The draft stays pending.",
        }
        return {
            "status": "error",
            "message": messages.get(reason, f"Action remains pending: {reason}"),
            "outcome": "pending",
            "reason": reason,
            "action_id": action_id,
        }
    return {
        "status": "success",
        "message": f"Action {outcome['status']}.",
        "outcome": outcome["status"],
        "reason": outcome.get("reason"),
        "execution": outcome.get("result"),
        "action_id": action_id,
    }


def execute_pending_action(action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the side effect for an action type. Non-publish types are acknowledged."""
    if action_type != LINKEDIN_DRAFT:
        return {"status": "acknowledged"}
    if os.getenv("KHURSHEED_BLOGGER_PUBLISH_ENABLED", "").lower() not in ("true", "1"):
        return {"status": "pending", "reason": "publish_disabled"}
    if not os.getenv("LINKEDIN_ACCESS_TOKEN") or not os.getenv("LINKEDIN_PAGE_ID"):
        return {"status": "pending", "reason": "linkedin_credentials_missing"}
    try:
        result = BloggerSkill()._publish_to_linkedin(payload)
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "pending", "reason": str(exc)}
    else:
        return {"status": "executed", "result": result}


def apply_approval_outcome(
    db_path: str | Path,
    action_id: str,
    reviewed_by: str,
    outcome: dict[str, Any],
) -> None:
    """Persist executed or acknowledged. A pending outcome leaves the row pending."""
    status = outcome.get("status")
    if status not in ("executed", "acknowledged"):
        return
    resolved = resolve_db_path(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            if status == "executed":
                conn.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'executed', reviewed_by = ?, reviewed_at = ?, executed_at = ?
                    WHERE action_id = ? AND status = 'pending'
                    """,
                    (reviewed_by, now, now, action_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'acknowledged', reviewed_by = ?, reviewed_at = ?
                    WHERE action_id = ? AND status = 'pending'
                    """,
                    (reviewed_by, now, action_id),
                )
    finally:
        conn.close()


def _fetch_pending(db_path: Path, action_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT action_id, action_type, payload_json, status
            FROM pending_actions
            WHERE action_id = ?
            """,
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["status"] != "pending":
        return None
    return dict(row)
