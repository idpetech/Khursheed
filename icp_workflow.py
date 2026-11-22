"""Qualify one ICP company, then wait before any contact.

Enaam calls the existing skills one step at a time. Research can finish
on its own. A note stays in To review until a person approves it, and
approval does not send the note.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime import resolve_db_path


WORKFLOW_SQL = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    company_key TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    website TEXT NOT NULL DEFAULT '',
    step TEXT NOT NULL,
    findings_json TEXT NOT NULL DEFAULT '',
    draft TEXT NOT NULL DEFAULT '',
    action_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
)
"""

WAITING = frozenset({"awaiting_approval", "approved", "declined", "not_a_fit"})
RESUME_STEPS = frozenset({"decide", "draft"})
QUALIFY = "icp_prospector"
DRAFT = "outreach_draft"
DEFAULT_PURPOSE = "CTO opportunity"


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def ensure_workflow(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(WORKFLOW_SQL)
    finally:
        conn.close()
    return resolved


def describe_workflow(row: dict[str, Any]) -> str:
    return str(_view(row).get("message") or "")


def get_workflow(db_path: str | Path, company_name: str) -> dict[str, Any] | None:
    key = company_key(company_name)
    if not key:
        return None
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE company_key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def advance_icp(
    db_path: str | Path,
    company: dict[str, Any],
    manager: Any,
    purpose: str = DEFAULT_PURPOSE,
) -> dict[str, Any]:
    """Run the next unfinished step for one company.

    A step already stored is not run again. Waiting for approval does not
    call a skill. purpose is what the company is being qualified for.
    """
    asked = (purpose or "").strip() or DEFAULT_PURPOSE
    name = str(company.get("company_name") or company.get("name") or "").strip()
    key = company_key(name)
    if not key:
        return {"status": "error", "message": "Name the company first.", "sent": False}
    website = str(company.get("website") or "").strip()
    row = _ensure_row(db_path, key, name, website)
    if row["website"] and not website:
        website = row["website"]
    step = row["step"]
    if step == "not_a_fit" and asked != _purpose(_findings(row)):
        row = _save(db_path, key, step="qualify")
        step = "qualify"
    if step in WAITING:
        return _view(row)

    if step == "qualify":
        result = manager.run_skill(
            QUALIFY,
            f"icp-workflow:{key}",
            {
                "company": {**company, "company_name": name, "website": website},
                "purpose": asked,
            },
        )
        if result.get("error"):
            return {
                "status": "error",
                "message": str(result["error"]),
                "sent": False,
                "step": "qualify",
                "company": name,
            }
        result = {**result, "purpose": asked}
        _save(db_path, key, step="decide", findings=result, website=website)
        step = "decide"

    if step == "decide":
        findings = _findings(_row(db_path, key))
        if _ranking_failed(name, findings):
            _save(db_path, key, step="qualify")
            return {
                "status": "error",
                "message": "The model did not rank this company, so no note was written.",
                "sent": False,
                "step": "qualify",
                "company": name,
            }
        if _worth(name, findings):
            _save(db_path, key, step="draft")
            step = "draft"
        else:
            row = _save(db_path, key, step="not_a_fit")
            return _view(row)

    if step == "draft":
        findings = _findings(_row(db_path, key))
        result = manager.run_skill(
            DRAFT,
            f"icp-workflow:{key}",
            {
                "company_name": name,
                "website": website,
                "rationale": _rationale(name, findings),
                "purpose": _purpose(findings),
            },
        )
        if result.get("error") or not result.get("draft"):
            return {
                "status": "error",
                "message": str(result.get("error") or "The note could not be written."),
                "sent": False,
                "step": "draft",
                "company": name,
            }
        row = _save(
            db_path,
            key,
            step="awaiting_approval",
            draft=str(result.get("draft") or ""),
            action_id=str(result.get("action_id") or ""),
        )
        return _view(row)

    return _view(_row(db_path, key))


def decide_icp_draft(db_path: str | Path, action_id: str, approve: bool) -> dict[str, Any]:
    """Record a yes or a no. Neither one contacts the company."""
    row = _by_action(db_path, action_id)
    if row is None:
        return {"status": "error", "message": "That note is no longer waiting.", "sent": False}
    if row["step"] in {"approved", "declined"}:
        return _view(row)
    if approve:
        from action_executor import approve_and_execute

        outcome = approve_and_execute(db_path, action_id, reviewed_by="desk")
        if outcome.get("status") == "error":
            return {
                "status": "error",
                "message": outcome.get("message") or "The note could not be approved.",
                "sent": False,
                "step": row["step"],
                "company": row["company_name"],
            }
        saved = _save(db_path, row["company_key"], step="approved")
        return _view(saved)
    _close(db_path, action_id, "rejected")
    saved = _save(db_path, row["company_key"], step="declined")
    return _view(saved)


def refresh_icp_search(db_path: str | Path, manager: Any) -> dict[str, Any]:
    """Look for new companies now. Names already offered are left off the list."""
    from desk_settings import icp_payload

    result = manager.run_skill("icp_finder", "icp-refresh", icp_payload(db_path))
    found = [item for item in (result.get("candidates") or []) if isinstance(item, dict)]
    if result.get("error") and not found:
        return {"status": "error", "message": str(result["error"]), "found": 0}
    if not found:
        return {
            "status": "ok",
            "message": "No new companies. Names already offered stay off this list.",
            "found": 0,
        }
    noun = "company" if len(found) == 1 else "companies"
    return {"status": "ok", "message": f"Found {len(found)} new {noun}.", "found": len(found)}


def list_company_notes(db_path: str | Path) -> list[dict[str, Any]]:
    """Approved and declined notes, newest first. Pending notes stay in the waiting list."""
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT company_key, company_name, website, step, draft, updated_at
            FROM workflow_runs
            WHERE step IN ('approved', 'declined') AND draft != ''
            ORDER BY updated_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def track_company_note(db_path: str | Path, company_name: str) -> dict[str, Any]:
    """Save a follow-up for an approved note. Tracking does not send it."""
    from desk_work import add_commitment
    from desk_work import list_commitments

    name = (company_name or "").strip()
    row = get_workflow(db_path, name)
    if row is None or row.get("step") != "approved":
        return {"status": "error", "message": "That note is not approved.", "sent": False}
    title = f"Follow up on the approved note for {name}"
    if any(item.get("title") == title for item in list_commitments(db_path)):
        return {
            "status": "ok",
            "message": f"The follow-up for {name} is already on Now. The note was not sent.",
            "duplicate": True,
            "sent": False,
        }
    saved = add_commitment(db_path, title)
    if saved.get("status") != "ok":
        return saved
    return {
        "status": "ok",
        "message": f"The follow-up for {name} is on Now, under Commitments. The note was not sent.",
        "sent": False,
        "commitment_id": saved.get("commitment_id"),
    }


def resume_open_workflows(manager: Any) -> list[str]:
    """Finish a note that was already qualified. Do not start a new search."""
    resolved = ensure_workflow(manager._db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT company_name, website, step
            FROM workflow_runs
            WHERE step IN ('decide', 'draft')
            ORDER BY updated_at ASC
            """
        ).fetchall()
    finally:
        conn.close()
    resumed: list[str] = []
    for row in rows:
        advance_icp(
            resolved,
            {"company_name": row["company_name"], "website": row["website"]},
            manager,
        )
        resumed.append(row["company_name"])
    return resumed


def _ensure_row(db_path: str | Path, key: str, name: str, website: str) -> dict[str, Any]:
    resolved = ensure_workflow(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (
                    company_key, company_name, website, step, updated_at
                ) VALUES (?, ?, ?, 'qualify', ?)
                ON CONFLICT(company_key) DO UPDATE SET
                    website = CASE
                        WHEN excluded.website != '' THEN excluded.website
                        ELSE workflow_runs.website
                    END
                """,
                (key, name, website, now),
            )
    finally:
        conn.close()
    row = _row(resolved, key)
    if row is None:
        raise RuntimeError(f"Workflow row for {name} was not stored.")
    return row


def _row(db_path: str | Path, key: str) -> dict[str, Any] | None:
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE company_key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _by_action(db_path: str | Path, action_id: str) -> dict[str, Any] | None:
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _save(
    db_path: str | Path,
    key: str,
    step: str,
    findings: dict[str, Any] | None = None,
    draft: str | None = None,
    action_id: str | None = None,
    website: str | None = None,
) -> dict[str, Any]:
    resolved = ensure_workflow(db_path)
    fields = ["step = ?", "updated_at = ?"]
    values: list[Any] = [step, datetime.now(UTC).isoformat()]
    if findings is not None:
        fields.append("findings_json = ?")
        values.append(json.dumps(findings))
    if draft is not None:
        fields.append("draft = ?")
        values.append(draft)
    if action_id is not None:
        fields.append("action_id = ?")
        values.append(action_id)
    if website:
        fields.append("website = ?")
        values.append(website)
    values.append(key)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                f"UPDATE workflow_runs SET {', '.join(fields)} WHERE company_key = ?",
                values,
            )
    finally:
        conn.close()
    row = _row(resolved, key)
    if row is None:
        raise RuntimeError(f"Workflow row {key} disappeared.")
    return row


def _purpose(findings: dict[str, Any]) -> str:
    return str(findings.get("purpose") or DEFAULT_PURPOSE).strip() or DEFAULT_PURPOSE


def _findings(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    try:
        parsed = json.loads(row.get("findings_json") or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ranking_failed(company_name: str, findings: dict[str, Any]) -> bool:
    """A checklist fallback is not a judgment, and it must not produce a note."""
    key = company_key(company_name)
    for item in findings.get("top_companies") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("company_name") or item.get("name") or "")
        if company_key(label) != key:
            continue
        return str(item.get("rationale") or "").startswith("llm_unavailable")
    return False


def _worth(company_name: str, findings: dict[str, Any]) -> bool:
    key = company_key(company_name)
    for item in findings.get("top_companies") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("company_name") or item.get("name") or "")
        if company_key(label) == key:
            return True
    return False


def _rationale(company_name: str, findings: dict[str, Any]) -> str:
    key = company_key(company_name)
    for item in findings.get("top_companies") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("company_name") or item.get("name") or "")
        if company_key(label) == key:
            return str(item.get("rationale") or "").strip()
    return ""


def _reason(company_name: str, findings: dict[str, Any]) -> str:
    key = company_key(company_name)
    for item in findings.get("rejected") or []:
        if not isinstance(item, dict):
            continue
        if company_key(str(item.get("name") or item.get("company_name") or "")) == key:
            return str(item.get("reason") or "").strip()
    return "No strong fit."


def _view(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"status": "error", "message": "That company is not in progress.", "sent": False}
    name = row["company_name"]
    step = row["step"]
    if step == "not_a_fit":
        purpose = _purpose(_findings(row))
        message = f"{name} is not a fit for {purpose}. {_reason(name, _findings(row))}"
    elif step == "awaiting_approval":
        purpose = _purpose(_findings(row))
        message = f"A note for {name} is in Companies. Qualified as {purpose}. It has not been sent."
    elif step == "approved":
        message = f"Approved the note for {name}. It was not sent. It stays on Companies under Kept notes."
    elif step == "declined":
        message = f"Left the note for {name}. Nothing was sent."
    elif step == "draft":
        message = f"The note for {name} is not written yet."
    else:
        message = f"{name} is not qualified yet."
    return {"status": "ok", "step": step, "message": message, "sent": False, "company": name}


def _close(db_path: str | Path, action_id: str, status: str) -> None:
    resolved = resolve_db_path(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                UPDATE pending_actions
                SET status = ?, reviewed_by = 'desk', reviewed_at = ?
                WHERE action_id = ? AND status = 'pending'
                """,
                (status, now, action_id),
            )
    finally:
        conn.close()
