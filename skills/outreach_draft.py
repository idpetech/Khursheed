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
        title = str(payload.get("title") or "").strip()
        url = str(payload.get("url") or "").strip()
        db_path = task.get("db_path") or "khursheed.db"
        if not title:
            title, url = _latest_kept(db_path)
        if not title:
            return {"draft": "", "error": "Keep a role before asking for a note."}
        body = _body(title, url)
        try:
            from priority_inbox import emit_priority_action

            emit_priority_action(
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
        return {"draft": body, "title": title, "sent": False}


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


def _body(title: str, url: str) -> str:
    from desk_work import outreach_body

    return outreach_body(title, url)
