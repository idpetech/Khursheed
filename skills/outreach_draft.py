"""Write a short note for a kept role and leave it for review. Never send it."""

from __future__ import annotations

import logging
import re
from typing import Any

from skills.base import Skill
from skills.tavily_client import tavily_search


logger = logging.getLogger(__name__)

_ROLE_RE = re.compile(r"\b(co-?founder|founder|CEO)\b", re.IGNORECASE)
_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,2})\b")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_NAME_STOP = {
    "the",
    "a",
    "an",
    "our",
    "this",
    "that",
    "and",
    "for",
    "with",
    "from",
    "their",
    "his",
    "her",
    "email",
    "contact",
    "about",
}
_NAME_GAP = 40


class OutreachDraftSkill(Skill):
    name = "outreach_draft"

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task.get("payload") or {}
        db_path = task.get("db_path") or "khursheed.db"
        company_name = str(payload.get("company_name") or "").strip()
        if company_name:
            return _queue_company(db_path, company_name, payload)
        title = str(payload.get("title") or "").strip()
        url = str(payload.get("url") or "").strip()
        if not title:
            title, url = _latest_kept(db_path)
        if not title:
            return {"draft": "", "error": "Keep a role before asking for a note."}
        body = _body(title, url)
        try:
            from priority_inbox import emit_priority_action

            action_id = emit_priority_action(
                kind="outreach_draft",
                title=f"Note for {title}",
                description="Draft only. Keeping it does not send the note.",
                payload={"title": title, "url": url, "body": body, "send": False},
                priority=1,
                source_key=f"outreach:{url or title}",
                db_path=str(db_path),
            )
        except Exception as exc:
            logger.warning("Outreach draft could not be queued: %s", exc)
            return {"draft": body, "error": str(exc), "sent": False}
        return {"draft": body, "title": title, "sent": False, "action_id": action_id}


def _queue_company(db_path: str, company_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Leave a company note in To review. The note is not sent."""
    from icp_workflow import company_key
    from priority_inbox import emit_priority_action

    saved = _saved_draft(db_path, company_name)
    if saved:
        return saved

    website = str(payload.get("website") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    purpose = str(payload.get("purpose") or "").strip()
    recipient = _lookup_recipient(company_name, website)
    body = _body(company_name, website, purpose, rationale, recipient)
    try:
        action_id = emit_priority_action(
            kind="outreach_draft",
            title=f"Note for {company_name}",
            description="Draft only. Approving it does not send the note.",
            payload={
                "title": company_name,
                "url": website,
                "body": body,
                "send": False,
                "company": True,
                "rationale": rationale,
            },
            priority=1,
            source_key=f"icp-outreach:{company_key(company_name)}",
            db_path=str(db_path),
        )
    except Exception as exc:
        logger.warning("Company note could not be queued: %s", exc)
        return {"draft": body, "error": str(exc), "sent": False}
    return {"draft": body, "title": company_name, "sent": False, "action_id": action_id}


def _latest_kept(db_path: str) -> tuple[str, str]:
    try:
        from desk_work import list_pursuits

        pursuits = list_pursuits(db_path)
    except Exception:
        return "", ""
    if not pursuits:
        return "", ""
    first = pursuits[0]
    return str(first.get("title") or ""), str(first.get("url") or "")


def _saved_draft(db_path: str, company_name: str) -> dict[str, Any] | None:
    """Return a note that was already stored. Reading it does not search."""
    from icp_workflow import company_key
    from icp_workflow import get_workflow

    row = get_workflow(db_path, company_name)
    if row and str(row.get("draft") or "").strip():
        return {
            "draft": str(row["draft"]),
            "title": company_name,
            "sent": False,
            "action_id": str(row.get("action_id") or ""),
        }
    source_key = f"icp-outreach:{company_key(company_name)}"
    return _saved_action(db_path, company_name, source_key)


def _saved_action(db_path: str, company_name: str, source_key: str) -> dict[str, Any] | None:
    import json
    import sqlite3

    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            "SELECT action_id, payload_json FROM pending_actions WHERE source_key = ?",
            (source_key,),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        payload = json.loads(row[1] or "{}")
    except json.JSONDecodeError:
        return None
    body = str(payload.get("body") or "")
    if not body.strip():
        return None
    return {"draft": body, "title": company_name, "sent": False, "action_id": str(row[0])}


def _lookup_recipient(company_name: str, website: str) -> dict[str, str]:
    """One search for a founder or CEO named on a public page."""
    try:
        data = tavily_search(_recipient_query(company_name, website), 5)
    except Exception as exc:
        logger.warning("Recipient lookup failed: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        snippet = _snippet(item)
        found = _person_in_snippet(snippet, company_name)
        if not found:
            continue
        source = str(item.get("url") or "").strip()
        if not source:
            continue
        name, role = found
        return {"name": name, "role": role, "email": _email_in(snippet), "source": source}
    return {}


def _recipient_query(company_name: str, website: str) -> str:
    from skills.icp_finder import _own_website

    query = f"{company_name} founder or CEO"
    own = _own_website(company_name, website)
    if own:
        return f"{query} {own}"
    return query


def _snippet(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    return f"{title}\n{content}".strip()


def _person_in_snippet(text: str, company_name: str) -> tuple[str, str] | None:
    company = _name_key(company_name)
    best: tuple[int, int, str, str] | None = None
    for role_match in _ROLE_RE.finditer(text):
        role = _role_label(role_match.group(1))
        for name_match in _NAME_RE.finditer(text):
            if name_match.start() < role_match.end() and name_match.end() > role_match.start():
                continue
            gap = _span_gap(
                name_match.start(),
                name_match.end(),
                role_match.start(),
                role_match.end(),
            )
            if gap > _NAME_GAP:
                continue
            name = name_match.group(1)
            if _skip_name(name, company):
                continue
            rank = (gap, name_match.start())
            if best is None or rank < (best[0], best[1]):
                best = (gap, name_match.start(), name, role)
    if best is None:
        return None
    return best[2], best[3]


def _span_gap(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    if left_end <= right_start:
        return right_start - left_end
    if right_end <= left_start:
        return left_start - right_end
    return 0


def _skip_name(name: str, company: str) -> bool:
    first = name.split()[0].lower()
    if first in _NAME_STOP:
        return True
    return _name_key(name) == company


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _role_label(raw: str) -> str:
    word = re.sub(r"[^a-z]", "", raw.lower())
    if word == "ceo":
        return "CEO"
    if word == "cofounder":
        return "cofounder"
    return "founder"


def _email_in(text: str) -> str:
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else ""


def _body(
    title: str,
    url: str,
    purpose: str = "",
    rationale: str = "",
    recipient: dict[str, str] | None = None,
) -> str:
    text = _letter(title, url, purpose, rationale)
    if recipient is None:
        return text
    return _with_recipient(text, recipient)


def _letter(title: str, url: str, purpose: str, rationale: str) -> str:
    from desk_work import outreach_body

    if "cto" in (purpose or "CTO opportunity").lower():
        return outreach_body(title, url)
    link = f"\n{url}\n" if url else "\n"
    because = f"\n{rationale}\n" if rationale else "\n"
    return (
        f"Hello,\n\n"
        f"I am looking at {title} as a {purpose}.{link}"
        f"{because}\n"
        "Haseeb"
    )


def _with_recipient(text: str, recipient: dict[str, str]) -> str:
    name = (recipient.get("name") or "").strip()
    if not name:
        return f"No recipient found.\n\n{text}"
    first = name.split()[0]
    if text.startswith("Hello,"):
        text = f"Hello {first}," + text[len("Hello,") :]
    email = (recipient.get("email") or "").strip() or "none on the source page."
    header = (
        f"To: {name}, {recipient.get('role') or ''}\n"
        f"Email: {email}\n"
        f"Source: {recipient.get('source') or ''}"
    )
    return f"{header}\n\n{text}"
