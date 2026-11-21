"""Strategic advice for the principal. It recommends. It does not act."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from skills.base import Skill


NAME = "ceo_advisor"

SECTIONS = (
    "Executive assessment",
    "Relevant facts and assumptions",
    "Opportunities",
    "Risks and constraints",
    "Available options",
    "Recommended decision",
    "Immediate next steps",
)

_SYSTEM = """You are the CEO Advisor for this principal. You advise. You do not act.

Use only the desk context below. A line under "Earlier recommendations" is a previous recommendation, not a fact.
If a cost, margin, revenue figure, or market fact is not in the context, say it is not on the desk. Do not invent it.
Separate facts already on the desk from assumptions.
Challenge a weak priority instead of agreeing with it.
Do not send messages, spend money, contact anyone, or change records.

Answer in markdown with these headings, in this order, and no others:
## Executive assessment
## Relevant facts and assumptions
## Opportunities
## Risks and constraints
## Available options
## Recommended decision
## Immediate next steps

Under Immediate next steps, include one line in the form "Next step: ..." naming the single operational step the chief of staff could track.
Keep it short unless the question asks for depth.
"""


class CeoAdvisorSkill(Skill):
    """Advise on strategy. Do not send, spend, or record a decision."""

    name = NAME

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = task.get("payload") or {}
        question = str(payload.get("question") or "").strip()
        if not question:
            return _stopped("Say what you want assessed.")
        if not os.getenv("OPENAI_API_KEY", "").strip():
            return _stopped("CEO Advisor needs the model. Nothing was assessed.")
        db_path = str(task.get("db_path") or "khursheed.db")
        context = build_context(db_path, task.get("profile_path"))
        try:
            assessment = _complete(question, context)
        except Exception as exc:
            return _stopped(f"CEO Advisor could not answer. {exc}")
        if not assessment or not _has_sections(assessment):
            return _stopped("CEO Advisor did not return an assessment.")
        return {
            "advisory": True,
            "executed": False,
            "question": question,
            "assessment": assessment,
            "next_step": _next_step(assessment),
        }


def build_context(db_path: str, profile_path: str | None = None) -> str:
    """Facts already stored on the desk, plus earlier advice marked as advice."""
    from desk_settings import list_icp_seed
    from desk_work import list_commitments
    from desk_work import list_pursuits
    from desk_work import morning_focus
    from principal_profile import principal_prompt_block

    parts = ["Desk context. Use this. Do not treat a recommendation as a fact."]
    profile = principal_prompt_block(profile_path).strip()
    parts.append(profile or "Principal profile: not on the desk.")
    try:
        focus = morning_focus(db_path)
        lines = focus.get("lines") or []
        paused = "yes" if focus.get("pause_research") else "no"
        parts.append("Morning line: " + (" ".join(lines) or "none") + f" Research paused: {paused}.")
    except Exception:
        parts.append("Morning line: not available.")
    parts.append("Commitments: " + _titles(lambda: list_commitments(db_path), "title"))
    parts.append("Kept roles: " + _titles(lambda: list_pursuits(db_path), "title"))
    parts.append("Chosen companies: " + _titles(lambda: list_icp_seed(db_path), "company_name"))
    parts.append("Open items: " + _open_titles(db_path))
    earlier = _earlier_advice(db_path)
    if earlier:
        parts.append("Earlier recommendations, not facts:\n" + earlier)
    else:
        parts.append("Earlier recommendations: none.")
    return "\n".join(parts)


def is_ceo_request(query: str) -> bool:
    """True when the principal asked for the advisor by name."""
    text = " ".join((query or "").lower().split())
    if text.startswith("ceo:"):
        return True
    markers = (
        "ceo advisor",
        "ceo review",
        "ceo assessment",
        "quarterly strategic review",
        "challenge my current priorities",
        "challenge my priorities",
    )
    return any(marker in text for marker in markers)


def question_from(query: str) -> str:
    text = " ".join((query or "").split())
    lowered = text.lower()
    if lowered.startswith("ceo:"):
        rest = text[4:].strip()
        return rest or _default_question()
    if lowered in {"ask ceo advisor", "ceo review", "ceo advisor"}:
        return _default_question()
    return text or _default_question()


def is_track_request(query: str) -> bool:
    text = " ".join((query or "").lower().split()).rstrip(".")
    return text == "track this" or text.startswith("track this ")


def track_latest_advice(db_path: str) -> dict[str, Any]:
    """Save the latest recommended next step. Does not call the model."""
    from desk_work import add_commitment

    stored = _latest_result(db_path)
    if stored is None:
        return {"status": "error", "message": "There is no CEO assessment to track."}
    step = str(stored.get("next_step") or "").strip() or _next_step(str(stored.get("assessment") or ""))
    if not step:
        return {"status": "error", "message": "The latest assessment has no next step to track."}
    saved = add_commitment(db_path, step)
    if saved.get("status") != "ok":
        return saved
    return {"status": "ok", "message": f"Tracking: {step}", "commitment_id": saved.get("commitment_id")}


def _default_question() -> str:
    return "Give me a CEO assessment of the business as it stands."


def _stopped(message: str) -> dict[str, Any]:
    return {"advisory": True, "executed": False, "error": message}


def _has_sections(assessment: str) -> bool:
    return all(f"## {section}" in assessment for section in SECTIONS)


def _next_step(assessment: str) -> str:
    section = assessment.split("## Immediate next steps", 1)
    body = section[1] if len(section) == 2 else assessment
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("next step:"):
            return stripped.split(":", 1)[1].strip()
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            return stripped[2:].strip()
    return ""


def _titles(loader, field: str) -> str:
    try:
        rows = loader()
    except Exception:
        return "not available"
    names = [str(row.get(field) or "").strip() for row in rows if str(row.get(field) or "").strip()]
    return "; ".join(names) if names else "none"


def _open_titles(db_path: str) -> str:
    try:
        from priority_inbox import list_open_priority_actions

        rows = list_open_priority_actions(min_priority=0, db_path=db_path)
    except Exception:
        return "not available"
    names = [str(row.get("title") or "").strip() for row in rows[:12] if str(row.get("title") or "").strip()]
    return "; ".join(names) if names else "none"


def _earlier_advice(db_path: str) -> str:
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        rows = conn.execute(
            """
            SELECT result_json FROM skill_runs
            WHERE skill_name = ?
            ORDER BY executed_at DESC
            LIMIT 3
            """,
            (NAME,),
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return ""
    notes = []
    for (raw,) in rows:
        try:
            result = json.loads(raw or "{}")
        except json.JSONDecodeError:
            continue
        text = str(result.get("assessment") or "").strip()
        if text:
            notes.append(text[:500])
    return "\n---\n".join(notes)


def _latest_result(db_path: str) -> dict[str, Any] | None:
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        row = conn.execute(
            """
            SELECT result_json FROM skill_runs
            WHERE skill_name = ?
            ORDER BY executed_at DESC
            LIMIT 1
            """,
            (NAME,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if row is None or not row[0]:
        return None
    try:
        result = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _complete(question: str, context: str) -> str:
    import openai

    client = openai.OpenAI()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Question:\n{question}\n\n{context}"},
        ],
    )
    return (response.choices[0].message.content or "").strip()
