"""Qualify one ICP company, then wait before any contact.

Enaam calls the existing skills one step at a time. Research can finish
on its own. A note stays in To review until a person approves it, and
approval does not send the note.

A saved note for another purpose stays on the same company row. The desk
asks before qualifying that purpose. Yes copies the saved note into
prior_notes_json, then runs the new purpose. No leaves the row as it is.
Nothing is sent.
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
    updated_at TEXT NOT NULL,
    prior_notes_json TEXT NOT NULL DEFAULT ''
)
"""

CONFIRM_SQL = """
CREATE TABLE IF NOT EXISTS qualify_confirmations (
    session_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    previous_purpose TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

WAITING = frozenset({"awaiting_approval", "approved", "declined", "not_a_fit"})
HELD_NOTE = frozenset({"awaiting_approval", "approved", "declined"})
RESUME_STEPS = frozenset({"decide", "draft"})
QUALIFY = "icp_prospector"
DRAFT = "outreach_draft"
DEFAULT_PURPOSE = "CTO opportunity"
DESK_SESSION = "hey-eman"
_CTO_ENGAGEMENT = re.compile(
    r"^(?:(?:a|an|the)\s+)?(?:fractional\s+)?cto(?:\s+(?:opportunity|engagement))?$"
)


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def ensure_workflow(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(WORKFLOW_SQL)
            conn.execute(CONFIRM_SQL)
            _ensure_prior_notes_column(conn)
    finally:
        conn.close()
    return resolved


def _ensure_prior_notes_column(conn: sqlite3.Connection) -> None:
    """Keep an older note on the company row when a new purpose replaces it."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    if "prior_notes_json" not in columns:
        conn.execute(
            "ALTER TABLE workflow_runs ADD COLUMN prior_notes_json TEXT NOT NULL DEFAULT ''"
        )


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
    confirmed: bool = False,
    session_id: str = DESK_SESSION,
) -> dict[str, Any]:
    """Run the next unfinished step for one company.

    A step already stored is not run again. Waiting for approval does not
    call a skill. purpose is what the company is being qualified for.
    A saved note for a different purpose stays on the row until the same
    session confirms it. The reply asks, and it does not present the old
    note as the new answer. A confirmed yes copies that note aside, then
    qualifies the new purpose. Nothing is sent.
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
    stored_purpose = _purpose(_findings(row))
    replacing: dict[str, Any] | None = None

    def _fail(message: str, failed_step: str) -> dict[str, Any]:
        if replacing is not None:
            _save(
                db_path,
                key,
                step=str(replacing["step"]),
                findings=replacing["findings"],
                draft=str(replacing["draft"]),
                action_id=str(replacing["action_id"]),
                prior_notes=replacing["prior_notes"],
            )
        return {
            "status": "error",
            "message": message,
            "sent": False,
            "step": failed_step,
            "company": name,
        }

    if step == "not_a_fit" and not _same_purpose(asked, stored_purpose):
        row = _save(db_path, key, step="qualify")
        step = "qualify"
    elif step in HELD_NOTE and not _same_purpose(asked, stored_purpose):
        if not confirmed:
            _remember_confirmation(db_path, session_id, name, asked, stored_purpose)
            return {
                "status": "ok",
                "step": step,
                "message": _confirm_purpose_message(name, stored_purpose, asked),
                "sent": False,
                "company": name,
                "note_withheld": True,
                "needs_confirmation": True,
            }
        findings_now = json.loads(json.dumps(_findings(row)))
        prior = _prior_notes(row)
        replacing = {
            "step": step,
            "draft": str(row.get("draft") or ""),
            "action_id": str(row.get("action_id") or ""),
            "findings": findings_now,
            "prior_notes": json.loads(json.dumps(prior)),
        }
        prior.append(
            {
                "step": step,
                "purpose": stored_purpose,
                "draft": replacing["draft"],
                "action_id": replacing["action_id"],
                "findings": findings_now,
            }
        )
        row = _save(db_path, key, step="qualify", draft="", prior_notes=prior)
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
            return _fail(str(result["error"]), "qualify")
        result = {**result, "purpose": asked}
        _save(db_path, key, step="decide", findings=result, website=website)
        step = "decide"

    if step == "decide":
        findings = _findings(_row(db_path, key))
        if _ranking_failed(name, findings):
            if replacing is None:
                _save(db_path, key, step="qualify")
            return _fail(
                "The model did not rank this company, so no note was written.",
                "qualify",
            )
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
            return _fail(
                str(result.get("error") or "The note could not be written."),
                "draft",
            )
        row = _save(
            db_path,
            key,
            step="awaiting_approval",
            draft=str(result.get("draft") or ""),
            action_id=str(result.get("action_id") or ""),
        )
        return _view(row)

    return _view(_row(db_path, key))


def qualify_known_company(
    db_path: str | Path,
    query: str,
    manager: Any,
    session_id: str = DESK_SESSION,
) -> str | None:
    """Qualify one company already on the desk.

    A company in review, on the ICP list, or already in a workflow uses that
    company's qualify step. A unique near miss of one of those names uses that
    company. A qualify request that matches none, or several equally, returns a
    plain reply and does not call the model. A message that is not a qualify
    request returns None. This does not search for other companies, send a
    note, or approve one.
    """
    parsed = _qualify_request(query)
    if parsed is None:
        return None
    name, purpose = parsed
    company = _company_on_desk(db_path, name)
    if company is None:
        return "No single company on the desk matches. Nothing was sent."
    if not purpose:
        row = get_workflow(db_path, company["company_name"])
        if row is not None:
            purpose = _purpose(_findings(row))
    result = advance_icp(
        db_path,
        company,
        manager,
        purpose=purpose or DEFAULT_PURPOSE,
        session_id=session_id,
    )
    message = str(result.get("message") or "").strip()
    if not message:
        message = f"{company['company_name']} could not be qualified. Nothing was sent."
    if result.get("note_withheld"):
        return message
    return _reply_with_note(message, get_workflow(db_path, company["company_name"]))


def pending_qualification(
    db_path: str | Path,
    session_id: str = DESK_SESSION,
) -> dict[str, str] | None:
    """The one purpose change waiting for yes or no in this session."""
    resolved = ensure_workflow(db_path)
    session = _session_id(session_id)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT company_name, purpose, previous_purpose
            FROM qualify_confirmations
            WHERE session_id = ?
            """,
            (session,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "company_name": str(row["company_name"]),
        "purpose": str(row["purpose"]),
        "previous_purpose": str(row["previous_purpose"]),
    }


def preserved_company_notes(db_path: str | Path, company_name: str) -> list[dict[str, Any]]:
    """Notes copied aside on this company before a later purpose replaced them."""
    return _prior_notes(get_workflow(db_path, company_name))


def answer_qualify_confirmation(
    db_path: str | Path,
    query: str,
    manager: Any,
    session_id: str = DESK_SESSION,
) -> str | None:
    """Yes runs the pending qualification. No leaves it. Anything else clears it."""
    pending = pending_qualification(db_path, session_id)
    if pending is None:
        return None
    choice = _confirmation_choice(query)
    _clear_confirmation(db_path, session_id)
    if choice == "yes":
        return _run_confirmed_qualify(db_path, pending, manager, session_id)
    if choice == "no":
        return "Nothing was changed. Nothing was sent."
    return None


def _qualify_request(query: str) -> tuple[str, str] | None:
    """A request to qualify one named company, and an optional purpose."""
    text = re.sub(r"[\s.!?]+$", "", (query or "").strip())
    match = re.match(
        r"(?i)^(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?"
        r"(?:please\s+)?qualify\s+(?P<rest>.+)$",
        text,
    )
    if not match:
        return None
    rest = match.group("rest").strip(" \t\"'")
    rest = re.sub(r"(?i)\s+please$", "", rest).strip()
    purpose = ""
    split = re.search(r"(?i)\s+for\s+(.+)$", rest)
    if split:
        purpose = split.group(1).strip()
        rest = rest[: split.start()].strip()
    rest = re.sub(r"(?i)^(?:the\s+)?company\s+", "", rest).strip()
    if not company_key(rest):
        return None
    return rest, purpose


def _company_on_desk(db_path: str | Path, name: str) -> dict[str, Any] | None:
    """The stored company, when it is in review, on the ICP list, or in a workflow.

    A unique closest name within two edits of the company key resolves to that
    company. Zero matches, or several names at that same distance, do not.
    """
    key = company_key(name)
    if not key:
        return None
    found = _exact_company(db_path, name)
    if found is not None:
        return found
    near = _unique_near_name(db_path, key)
    if near is None:
        return None
    return _exact_company(db_path, near)


def _exact_company(db_path: str | Path, name: str) -> dict[str, Any] | None:
    key = company_key(name)
    if not key:
        return None
    workflow = get_workflow(db_path, name)
    candidate = _pending_candidate(db_path, key)
    seed = _seed_company(db_path, key)
    if workflow is None and candidate is None and seed is None:
        return None
    source: dict[str, Any] = {}
    if seed:
        source.update(seed)
    if candidate:
        for field, value in candidate.items():
            if value is None or value == "":
                continue
            source[field] = value
    company_name = str(
        source.get("company_name") or (workflow or {}).get("company_name") or name
    ).strip()
    website = str(source.get("website") or (workflow or {}).get("website") or "").strip()
    return {
        "company_name": company_name,
        "website": website,
        "industry": str(source.get("industry") or ""),
        "employee_count": source.get("employee_count") or 0,
        "funding_stage": str(source.get("funding_stage") or ""),
        "has_cto": str(source.get("has_cto") or "unknown").strip().lower() or "unknown",
        "acquired": str(source.get("acquired") or "unknown").strip().lower() or "unknown",
    }


def _unique_near_name(db_path: str | Path, key: str) -> str | None:
    """The one desk name within two edits, when no other name is equally close."""
    closest: list[str] = []
    closest_distance = 3
    seen: set[str] = set()
    for label in _desk_names(db_path):
        other = company_key(label)
        if not other or other in seen or other == key:
            continue
        seen.add(other)
        distance = _edit_distance(key, other, 2)
        if distance is None:
            continue
        if distance < closest_distance:
            closest = [label]
            closest_distance = distance
        elif distance == closest_distance:
            closest.append(label)
    if len(closest) != 1:
        return None
    return closest[0]


def _desk_names(db_path: str | Path) -> list[str]:
    """Company names in a workflow, in review, or on the ICP list."""
    names: list[str] = []
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        rows = conn.execute("SELECT company_name FROM workflow_runs").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for row in rows:
        label = str(row[0] or "").strip()
        if label:
            names.append(label)
    for candidate in _pending_candidates(db_path):
        label = str(candidate.get("company_name") or "").strip()
        if label:
            names.append(label)
    from desk_settings import list_icp_seed

    for row in list_icp_seed(db_path):
        label = str(row.get("company_name") or "").strip()
        if label:
            names.append(label)
    return names


def _edit_distance(left: str, right: str, limit: int) -> int | None:
    """Levenshtein distance, or None when it is past limit."""
    if abs(len(left) - len(right)) > limit:
        return None
    previous = list(range(len(right) + 1))
    for left_char in left:
        current = [previous[0] + 1]
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            current.append(
                min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost)
            )
        previous = current
    distance = previous[-1]
    if distance > limit:
        return None
    return distance


def _reply_with_note(message: str, row: dict[str, Any] | None) -> str:
    """Start with the step sentence, then the stored note when one was saved."""
    if row is None or row.get("step") not in WAITING:
        return message
    draft = str(row.get("draft") or "").strip()
    if draft:
        return f"{message}\n\n{draft}"
    if row.get("step") == "not_a_fit":
        return message
    return f"{message}\n\nThe note text is not stored."


def _pending_candidate(db_path: str | Path, key: str) -> dict[str, Any] | None:
    for found in _pending_candidates(db_path):
        if company_key(str(found.get("company_name") or "")) == key:
            return found
    return None


def _pending_candidates(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return []
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT title, payload_json
            FROM pending_actions
            WHERE action_type = 'icp_candidate' AND status = 'pending'
            """
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    found_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        label = str(payload.get("company_name") or row["title"] or "").strip()
        if not label:
            continue
        found = dict(payload)
        found["company_name"] = label
        found_rows.append(found)
    return found_rows


def _seed_company(db_path: str | Path, key: str) -> dict[str, Any] | None:
    from desk_settings import list_icp_seed

    for row in list_icp_seed(db_path):
        if company_key(str(row.get("company_name") or "")) == key:
            return row
    return None


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
    prior_notes: list[dict[str, Any]] | None = None,
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
    if prior_notes is not None:
        fields.append("prior_notes_json = ?")
        values.append(json.dumps(prior_notes))
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


def _normalize_purpose(purpose: str) -> str:
    text = (purpose or "").strip().casefold()
    text = text.replace("-", " ")
    text = re.sub(r"[.!?]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_cto_engagement(purpose: str) -> bool:
    """True for the default CTO purpose and the same fractional-CTO engagement."""
    return _CTO_ENGAGEMENT.fullmatch(_normalize_purpose(purpose)) is not None


def _same_purpose(asked: str, stored: str) -> bool:
    """Trimmed, case-insensitive equality. The CTO engagement is one purpose."""
    left = _normalize_purpose(asked) or _normalize_purpose(DEFAULT_PURPOSE)
    right = _normalize_purpose(stored) or _normalize_purpose(DEFAULT_PURPOSE)
    if left == right:
        return True
    return _is_cto_engagement(left) and _is_cto_engagement(right)


def _confirm_purpose_message(name: str, stored: str, asked: str) -> str:
    return (
        f"{name} already has a note for {stored}. "
        f"Qualify it for {asked}? Reply yes to run that. "
        f"The saved note stays. Nothing will be sent."
    )


def _session_id(session_id: str) -> str:
    return (session_id or "").strip() or DESK_SESSION


def _confirmation_choice(query: str) -> str | None:
    """Yes, yes please, or y. No is no. Any other sentence is neither."""
    text = re.sub(r"[\s.!?]+$", "", (query or "").strip())
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    if text in {"y", "yes", "yes please"}:
        return "yes"
    if text == "no":
        return "no"
    return None


def _remember_confirmation(
    db_path: str | Path,
    session_id: str,
    company_name: str,
    purpose: str,
    previous_purpose: str,
) -> None:
    resolved = ensure_workflow(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO qualify_confirmations (
                    session_id, company_name, purpose, previous_purpose, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    company_name = excluded.company_name,
                    purpose = excluded.purpose,
                    previous_purpose = excluded.previous_purpose,
                    updated_at = excluded.updated_at
                """,
                (
                    _session_id(session_id),
                    company_name,
                    purpose,
                    previous_purpose,
                    now,
                ),
            )
    finally:
        conn.close()


def _clear_confirmation(db_path: str | Path, session_id: str) -> None:
    resolved = ensure_workflow(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                "DELETE FROM qualify_confirmations WHERE session_id = ?",
                (_session_id(session_id),),
            )
    finally:
        conn.close()


def _run_confirmed_qualify(
    db_path: str | Path,
    pending: dict[str, str],
    manager: Any,
    session_id: str,
) -> str:
    name = str(pending.get("company_name") or "").strip()
    purpose = str(pending.get("purpose") or "").strip() or DEFAULT_PURPOSE
    company = _company_on_desk(db_path, name)
    if company is None:
        return f"{name} is not on the desk. Nothing was changed. Nothing was sent."
    result = advance_icp(
        db_path,
        company,
        manager,
        purpose=purpose,
        confirmed=True,
        session_id=session_id,
    )
    message = str(result.get("message") or "").strip()
    if not message:
        message = f"{company['company_name']} could not be qualified. Nothing was sent."
    if result.get("note_withheld"):
        return message
    text = _reply_with_note(message, get_workflow(db_path, company["company_name"]))
    lowered = text.lower()
    if (
        "nothing was sent" not in lowered
        and "not been sent" not in lowered
        and "was not sent" not in lowered
        and "not sent" not in lowered
    ):
        text = f"{text}\n\nNothing was sent."
    return text


def _prior_notes(row: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not row:
        return []
    raw = row.get("prior_notes_json") or ""
    if not str(raw).strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


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
