"""Commitments, kept roles, and skill requests the desk can show and clear.

These records sit beside saved search pages. Approving a skill request
keeps its workflow and briefing. It does not install or run new code, and
it does not send mail.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runtime import resolve_db_path


COMMITMENTS_SQL = """
CREATE TABLE IF NOT EXISTS commitments (
    commitment_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_on TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

PURSUITS_SQL = """
CREATE TABLE IF NOT EXISTS pursuits (
    pursuit_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL,
    next_on TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

PAUSED_RESEARCH = frozenset({"lead_scout", "cto_radar", "icp_finder", "icp_prospector"})

REQUESTS_SQL = """
CREATE TABLE IF NOT EXISTS skill_requests (
    request_id TEXT PRIMARY KEY,
    ask TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    workflow_json TEXT NOT NULL,
    briefing TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

REVIEW_KINDS = ("role_candidate", "outreach_draft", "skill_request", "icp_candidate")

_DIRECTORY_WORDS = (
    "jobs",
    "now hiring",
    "hiring now",
    "for hire",
    "hire a",
    "ctos in",
    "best freelance",
)
_BOARD_HOSTS = (
    "indeed.com",
    "ziprecruiter.com",
    "glassdoor.",
    "ctodirectory.com",
    "gofractional.com",
    "recruitfractional.com",
    "arc.dev",
)


def ensure_desk_work(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(COMMITMENTS_SQL)
            conn.execute(PURSUITS_SQL)
            conn.execute(REQUESTS_SQL)
            _ensure_pursuit_date(conn)
            _ensure_commitment_decision(conn)
    finally:
        conn.close()
    return resolved


def add_commitment(
    db_path: str | Path,
    title: str,
    due_on: str = "",
    decision_id: str = "",
) -> dict[str, Any]:
    text = (title or "").strip()
    if not text:
        return {"status": "error", "message": "Enter what you promised."}
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    link = (decision_id or "").strip()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        if link:
            existing = conn.execute(
                """
                SELECT commitment_id FROM commitments
                WHERE decision_id = ? AND title = ? AND status = 'open'
                """,
                (link, text),
            ).fetchone()
            if existing:
                return {
                    "status": "ok",
                    "message": "That action is already tracked.",
                    "commitment_id": existing[0],
                    "duplicate": True,
                }
        commitment_id = str(uuid.uuid4())
        with conn:
            conn.execute(
                """
                INSERT INTO commitments (
                    commitment_id, title, due_on, status, created_at, updated_at, decision_id
                ) VALUES (?, ?, ?, 'open', ?, ?, ?)
                """,
                (commitment_id, text, (due_on or "").strip(), now, now, link),
            )
    finally:
        conn.close()
    return {"status": "ok", "message": "Commitment saved.", "commitment_id": commitment_id, "duplicate": False}


def list_commitments(
    db_path: str | Path,
    statuses: tuple[str, ...] = ("open",),
) -> list[dict[str, Any]]:
    """Commitments in these statuses, oldest first. The default is open."""
    allowed = ("open", "done", "blocked", "cancelled")
    chosen = tuple(status for status in statuses if status in allowed)
    if not chosen:
        return []
    resolved = ensure_desk_work(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT commitment_id, title, due_on, status, created_at
            FROM commitments
            WHERE status IN (?, ?, ?, ?)
            ORDER BY created_at ASC
            """,
            (chosen + ("", "", "", ""))[:4],
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def complete_commitment(db_path: str | Path, commitment_id: str) -> dict[str, Any]:
    return _move_commitment(db_path, commitment_id, "done")


def block_commitment(db_path: str | Path, commitment_id: str) -> dict[str, Any]:
    return _move_commitment(db_path, commitment_id, "blocked")


def cancel_commitment(db_path: str | Path, commitment_id: str) -> dict[str, Any]:
    return _move_commitment(db_path, commitment_id, "cancelled")


def _move_commitment(db_path: str | Path, commitment_id: str, new_status: str) -> dict[str, Any]:
    """Move an open or blocked commitment to done, blocked, or cancelled.

    Done and cancelled stay as they are. Waiting for approval is a pending
    action, not one of these statuses.
    """
    messages = {
        "done": "Marked done.",
        "blocked": "Marked blocked.",
        "cancelled": "Marked cancelled.",
    }
    if new_status not in messages:
        return {"status": "error", "message": "Use done, blocked, or cancelled."}
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    current: str | None = None
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE commitments
                SET status = ?, updated_at = ?
                WHERE commitment_id = ? AND status IN ('open', 'blocked') AND status != ?
                """,
                (new_status, now, commitment_id, new_status),
            )
            moved = cursor.rowcount > 0
            if not moved:
                row = conn.execute(
                    "SELECT status FROM commitments WHERE commitment_id = ?",
                    (commitment_id,),
                ).fetchone()
                current = None if row is None else str(row[0])
    finally:
        conn.close()
    if moved:
        return {"status": "ok", "message": messages[new_status]}
    if current == "done":
        return {"status": "error", "message": "That commitment is already done."}
    if current == "cancelled":
        return {"status": "error", "message": "That commitment is already cancelled."}
    if current == "blocked":
        return {"status": "error", "message": "That commitment is already blocked."}
    return {"status": "error", "message": "That commitment is not on the list."}


def is_single_role(title: str, url: str) -> bool:
    """True for one employer posting. Directory and job-board pages are false."""
    text = f"{title} {url}".lower()
    host = urlparse(url).netloc.lower()
    if any(board in host or board in text for board in _BOARD_HOSTS):
        return False
    if re.search(r"\b\d+\+?\s+\w+", title.lower()):
        return False
    if any(word in title.lower() for word in _DIRECTORY_WORDS):
        return False
    return bool(title.strip() and url.strip())


def queue_single_roles(opportunities: list[dict[str, Any]], db_path: str | Path) -> int:
    """Offer one-employer roles for Keep or Skip. Board pages stay in saved leads."""
    from priority_inbox import emit_priority_action

    offered = 0
    for opportunity in opportunities:
        title = str(opportunity.get("title") or "").strip()
        url = str(opportunity.get("url") or "").strip()
        if not is_single_role(title, url):
            continue
        emit_priority_action(
            kind="role_candidate",
            title=title,
            description=str(opportunity.get("snippet") or "One employer is hiring."),
            payload={"title": title, "url": url, "snippet": opportunity.get("snippet") or ""},
            priority=1,
            source_key=f"role:{url}",
            db_path=str(db_path),
        )
        offered += 1
    return offered


def choose_role(db_path: str | Path, action_id: str, keep: bool) -> dict[str, Any]:
    action = _pending(db_path, action_id, "role_candidate")
    if action is None:
        return {"status": "error", "message": "That role is no longer waiting."}
    payload = json.loads(action["payload_json"] or "{}")
    title = str(payload.get("title") or action["title"] or "Role").strip()
    if keep:
        _insert_pursuit(db_path, title, str(payload.get("url") or ""))
        _close(db_path, action_id, "acknowledged")
        return {"status": "ok", "message": f"Kept {title}."}
    _close(db_path, action_id, "rejected")
    return {"status": "ok", "message": f"Skipped {title}."}


def list_pursuits(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = ensure_desk_work(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT pursuit_id, title, url, stage, next_on, created_at
            FROM pursuits
            WHERE stage = 'kept'
            ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def set_pursuit_date(db_path: str | Path, pursuit_id: str, next_on: str) -> dict[str, Any]:
    """Store the next follow-up date for a kept role. An empty value clears it."""
    text = (next_on or "").strip()
    if text and _parse_date(text) is None:
        return {"status": "error", "message": "Use a date like 2026-11-20."}
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE pursuits
                SET next_on = ?, updated_at = ?
                WHERE pursuit_id = ? AND stage = 'kept'
                """,
                (text, now, pursuit_id),
            )
            saved = cursor.rowcount > 0
    finally:
        conn.close()
    if not saved:
        return {"status": "error", "message": "That role is no longer kept."}
    if text:
        return {"status": "ok", "message": f"Next step set for {text}."}
    return {"status": "ok", "message": "Date cleared."}


def morning_focus(db_path: str | Path, today: date | None = None) -> dict[str, Any]:
    """The one or two lines the morning leads with, and whether research waits."""
    moment = today or datetime.now().astimezone().date()
    pursuits = list_pursuits(db_path)
    undated = [row for row in pursuits if not str(row.get("next_on") or "").strip()]
    dated = []
    for row in pursuits:
        parsed = _parse_date(str(row.get("next_on") or ""))
        if parsed is not None:
            dated.append((parsed, row))
    dated.sort(key=lambda item: (item[0], str(item[1].get("title") or "")))
    actions = _open_actions(db_path)
    if undated:
        role_line = "Set a date on a kept role."
        pause = True
    elif dated:
        when, row = dated[0]
        title = row.get("title") or "Role"
        stamp = when.isoformat()
        if when <= moment:
            role_line = f"Follow up: {title}, due {stamp}."
        else:
            role_line = f"Next follow-up: {title} on {stamp}."
        pause = False
    elif any(action.get("action_type") == "role_candidate" for action in actions):
        role_line = "Keep or skip the role waiting."
        pause = True
    else:
        role_line = "No kept role yet."
        pause = False
    bill_line = _urgent_bill_line(actions, moment)
    lines = [bill_line, role_line] if bill_line else [role_line]
    commitment_line = _due_commitment_line(db_path, moment)
    if commitment_line:
        lines.append(commitment_line)
    blocked_line = _blocked_commitment_line(db_path, moment)
    if blocked_line:
        lines.append(blocked_line)
    conditional_line = _conditional_decision_line(db_path)
    if conditional_line:
        lines.append(conditional_line)
    suggestion = _suggestion_line(db_path, moment)
    if suggestion:
        lines.append(suggestion)
    return {
        "lines": lines,
        "pause_research": pause,
        "bill_line": bill_line,
        "role_line": role_line,
    }


def _suggestion_line(db_path: str | Path, today: date) -> str:
    """A high-priority finding with no follow-up. This is not a commitment."""
    try:
        from briefing import next_suggestion
        from briefing import remember_suggestion

        hint = next_suggestion(db_path, today)
        if hint.get("status") == "new" and hint.get("line"):
            remember_suggestion(db_path, str(hint.get("key") or ""), str(hint.get("evidence") or ""))
            return str(hint["line"])
    except Exception:
        return ""
    return ""


def _ensure_pursuit_date(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(pursuits)")}
    if "next_on" not in columns:
        conn.execute("ALTER TABLE pursuits ADD COLUMN next_on TEXT NOT NULL DEFAULT ''")


def _ensure_commitment_decision(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(commitments)")}
    if "decision_id" not in columns:
        conn.execute("ALTER TABLE commitments ADD COLUMN decision_id TEXT NOT NULL DEFAULT ''")


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _open_actions(db_path: str | Path) -> list[dict[str, Any]]:
    try:
        from priority_inbox import list_open_priority_actions

        return list_open_priority_actions(min_priority=0, db_path=str(db_path))
    except Exception:
        return []


def _due_commitment_line(db_path: str | Path, today: date) -> str:
    """Name an open commitment that is due today or earlier. A blank date stays off this line."""
    return _commitment_due_line(list_commitments(db_path, ("open",)), today, blocked=False)


def _blocked_commitment_line(db_path: str | Path, today: date) -> str:
    """Name a blocked commitment that is due today or earlier. A blank date stays off this line."""
    return _commitment_due_line(list_commitments(db_path, ("blocked",)), today, blocked=True)


def _commitment_due_line(rows: list[dict[str, Any]], today: date, blocked: bool) -> str:
    due: list[tuple[date, dict[str, Any]]] = []
    for row in rows:
        parsed = _parse_date(str(row.get("due_on") or ""))
        if parsed is not None and parsed <= today:
            due.append((parsed, row))
    if not due:
        return ""
    due.sort(key=lambda item: (item[0], str(item[1].get("title") or "")))
    when, row = due[0]
    title = row.get("title") or "Commitment"
    word = "overdue" if when < today else "due"
    if blocked:
        line = f"Blocked commitment {word}: {title}, due {when.isoformat()}."
    else:
        line = f"Commitment {word}: {title}, due {when.isoformat()}."
    extra = len(due) - 1
    if extra == 1:
        if blocked:
            return f"{line} 1 other blocked commitment is also due."
        return f"{line} 1 other commitment is also due."
    if extra > 1:
        if blocked:
            return f"{line} {extra} other blocked commitments are also due."
        return f"{line} {extra} other commitments are also due."
    return line


def _conditional_decision_line(db_path: str | Path) -> str:
    """Name a subject whose latest stored decision is still conditional."""
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'strategic_decisions'"
        ).fetchone()
        if not exists:
            return ""
        rows = conn.execute(
            """
            SELECT subject, subject_key, decision
            FROM strategic_decisions
            ORDER BY created_at DESC
            """
        ).fetchall()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    latest: dict[str, tuple[str, str]] = {}
    for subject, key, decision in rows:
        if key not in latest:
            latest[str(key)] = (str(subject or ""), str(decision or ""))
    names = sorted(subject for subject, decision in latest.values() if decision == "CONDITIONAL GO" and subject)
    if not names:
        return ""
    line = f"Conditional decision: {names[0]}."
    extra = len(names) - 1
    if extra == 1:
        line = f"{line} 1 other conditional decision."
    elif extra > 1:
        line = f"{line} {extra} other conditional decisions."
    return line


def _urgent_bill_line(actions: list[dict[str, Any]], today: date) -> str:
    from priority_inbox import BILL_KINDS
    from priority_inbox import priority_for_bill

    current = datetime(today.year, today.month, today.day, 12, 0, 0)
    urgent: list[tuple[str, dict[str, Any]]] = []
    for action in actions:
        kind = str(action.get("action_type") or "")
        if kind not in BILL_KINDS:
            continue
        payload = _action_payload(action)
        priority, _expires = priority_for_bill(kind, payload.get("due_date"), now=current)
        if priority < 3:
            continue
        due = str(payload.get("due_date") or "")
        urgent.append((due or "0000-00-00", action))
    if not urgent:
        return ""
    urgent.sort(key=lambda item: item[0])
    return _bill_sentence(urgent[0][1], len(urgent) - 1)


def _bill_sentence(action: dict[str, Any], extra: int) -> str:
    payload = _action_payload(action)
    vendor = str(payload.get("vendor") or "").strip()
    title = str(action.get("title") or "Bill").strip()
    label = vendor or title
    due = str(payload.get("due_date") or "").strip()
    text = f"Pay or close: {label}"
    if due:
        text += f", due {due}"
    if extra == 1:
        text += ", and 1 other bill"
    elif extra > 1:
        text += f", and {extra} other bills"
    return text + "."


def _action_payload(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("payload_json") or action.get("payload") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def propose_skill(ask: str) -> dict[str, Any]:
    """Turn a request into a visible workflow and a morning-brief line."""
    text = " ".join((ask or "").split())
    if not text:
        return {"status": "error", "message": "Say what the skill should do."}
    name = _skill_name(text)
    workflow = [
        "Read this request and the principal profile.",
        "Do only the work described below, and stop before sending anything.",
        "Put the result on Now.",
        "After approval, add the briefing line to the morning note.",
        text,
    ]
    lowered = text.lower()
    if "calendar" in lowered or "meeting" in lowered:
        workflow.insert(1, "Read the calendar only when Calendar prep is on in Config.")
    if "email" in lowered or "outreach" in lowered or "note" in lowered:
        workflow.insert(1, "Write the note. Leave it on Now. Do not send it.")
    briefing = f"You asked for a skill to {text[:180].rstrip('.')}."
    return {
        "status": "ok",
        "skill_name": name,
        "ask": text,
        "workflow": workflow,
        "briefing": briefing,
    }


def submit_skill_request(db_path: str | Path, ask: str) -> dict[str, Any]:
    """Save the proposal and put the workflow and briefing in To review."""
    proposal = propose_skill(ask)
    if proposal.get("status") != "ok":
        return proposal
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    request_id = str(uuid.uuid4())
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO skill_requests (
                    request_id, ask, skill_name, workflow_json, briefing, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)
                """,
                (
                    request_id,
                    proposal["ask"],
                    proposal["skill_name"],
                    json.dumps(proposal["workflow"]),
                    proposal["briefing"],
                    now,
                    now,
                ),
            )
    finally:
        conn.close()
    from priority_inbox import emit_priority_action

    emit_priority_action(
        kind="skill_request",
        title=proposal["skill_name"],
        description=proposal["briefing"],
        payload={**proposal, "request_id": request_id},
        priority=1,
        source_key=f"skill-request:{request_id}",
        db_path=str(resolved),
    )
    workflow = "\n".join(f"{index}. {step}" for index, step in enumerate(proposal["workflow"], start=1))
    message = (
        f"### Workflow\n{workflow}\n\n"
        f"### Briefing\n{proposal['briefing']}\n\n"
        "It is waiting on Now. Approve it there to add the briefing to the morning note. "
        "Approving does not install code and does not send anything."
    )
    return {"status": "ok", "message": message, "request_id": request_id, **proposal}


def decide_skill_request(db_path: str | Path, action_id: str, approve: bool) -> dict[str, Any]:
    action = _pending(db_path, action_id, "skill_request")
    if action is None:
        return {"status": "error", "message": "That skill request is no longer waiting."}
    payload = json.loads(action["payload_json"] or "{}")
    request_id = str(payload.get("request_id") or "")
    status = "approved" if approve else "declined"
    _set_request_status(db_path, request_id, status)
    _close(db_path, action_id, "acknowledged" if approve else "rejected")
    if approve:
        return {"status": "ok", "message": "Approved. The briefing will be in the morning note."}
    return {"status": "ok", "message": "Declined."}


def approved_skill_briefings(db_path: str | Path) -> list[str]:
    resolved = ensure_desk_work(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT briefing FROM skill_requests
            WHERE status = 'approved'
            ORDER BY created_at ASC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return [str(row[0]) for row in rows if row[0]]


def list_skill_requests(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = ensure_desk_work(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT request_id, ask, skill_name, workflow_json, briefing, status
            FROM skill_requests
            ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["workflow"] = json.loads(item.pop("workflow_json") or "[]")
        except json.JSONDecodeError:
            item["workflow"] = []
        items.append(item)
    return items


def is_skill_request(query: str) -> bool:
    text = (query or "").strip().lower()
    return text.startswith("skill:") or "new skill" in text


def outreach_body(title: str, url: str = "") -> str:
    """A note the desk can hold. Nothing in this text is sent."""
    link = f"\n{url}\n" if url else "\n"
    return (
        f"Hello,\n\n"
        f"I help seed to series B software companies that still need a CTO. "
        f"I saw {title}.{link}\n"
        "If a fractional CTO would be useful for the next stage, I can talk for 20 minutes this week.\n\n"
        "Haseeb"
    )


def _insert_pursuit(db_path: str | Path, title: str, url: str) -> None:
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            existing = conn.execute("SELECT pursuit_id FROM pursuits WHERE url = ? AND url != ''", (url,)).fetchone()
            if existing:
                return
            conn.execute(
                """
                INSERT INTO pursuits (pursuit_id, title, url, stage, created_at, updated_at)
                VALUES (?, ?, ?, 'kept', ?, ?)
                """,
                (str(uuid.uuid4()), title, url, now, now),
            )
    finally:
        conn.close()


def _set_request_status(db_path: str | Path, request_id: str, status: str) -> None:
    resolved = ensure_desk_work(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                UPDATE skill_requests SET status = ?, updated_at = ? WHERE request_id = ?
                """,
                (status, now, request_id),
            )
    finally:
        conn.close()


def _pending(db_path: str | Path, action_id: str, kind: str) -> sqlite3.Row | None:
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT action_id, action_type, title, payload_json, status
            FROM pending_actions
            WHERE action_id = ?
            """,
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["status"] != "pending" or row["action_type"] != kind:
        return None
    return row


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


def _skill_name(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:4]) or "custom-skill"
    return slug[:40]
