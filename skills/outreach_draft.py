"""Write a short note for a kept role and leave it for review. Never send it."""

from __future__ import annotations

import logging
from typing import Any

from skills.base import Skill


logger = logging.getLogger(__name__)


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

    website = str(payload.get("website") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    purpose = str(payload.get("purpose") or "").strip()
    body = _body(company_name, website, purpose, rationale)
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


def _body(title: str, url: str, purpose: str = "", rationale: str = "") -> str:
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
