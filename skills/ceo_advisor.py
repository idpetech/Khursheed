"""CEO Advisor: an independent assessment. It does not act."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from openai import OpenAI

from desk_work import add_commitment
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import morning_focus
from desk_settings import list_icp_seed
from principal_profile import DEFAULT_PROFILE_PATH
from priority_inbox import list_open_priority_actions
from skills.base import Skill
from skills.tavily_client import tavily_search


DECISION_LABELS = (
    "Strategic rationale:",
    "Commercial rationale:",
    "Evidence:",
    "Unknowns:",
    "Resource commitment:",
    "Opportunity cost:",
    "Next action:",
    "Confidence:",
)

_OPERATIONAL_WORDS = ("inbox", "email", "e-mail", "mail", "calendar", "linkedin", "publish", "post a week")

_INTERNAL_MARKERS = (
    "my current priorities",
    "my priorities",
    "challenge my",
    "90-day",
    "ninety-day",
    "review the quarter",
    "the business as it stands",
    "quarterly strategic review",
)

SYSTEM_PROMPT = """You are the CEO advisor for IDPETECH. You answer the request you were given. You do not replace it with a nearby topic from the desk, and you do not run the desk.

A CEO advisor behaves like this:
- Restate the subject in the terms of the request, after you understand what it actually is.
- Use desk context only where it changes that answer. Mandate is IDPETECH. Priorities are current resource choices and opportunity cost. Operations stay out unless the request is about running the desk. A queued company is not evidence about that company.
- Separate three judgments: strategically interesting, commercially real for someone, and worth IDPETECH's time. A profitable market for its own operators is not IDPETECH's opportunity.
- If IDPETECH has no capability, customer, or mandate to sell, build, or be accountable for the subject, decide NO-GO. Do not study your way in.
- CONDITIONAL GO means the subject is already close to work IDPETECH can do, and one named condition would make it a GO. The next action tests that condition.
- GO means there is evidence a buyer would pay IDPETECH, or a measurable result IDPETECH already knows how to deliver. A market article is not that evidence. An unknown willingness to pay is not a GO.
- ChatGPT and Claude are the buyer's first alternative for generic information, advice, research, writing, or recommendations. Name the accountability, judgment, or context a buyer cannot get from those tools, or say there is none.
- The next action is one concrete step, or "Stop. Do not pursue this." It is not a campaign, a program, a watch-list, or further research.
- Say what is verified, what is assumed, and what would change the decision. Earlier advisor output is not a fact. If the lookup did not happen, say so and do not invent the subject.

End with these labels, each on its own line:

Decision: GO or CONDITIONAL GO or DEFER or NO-GO
Strategic rationale:
Commercial rationale:
Evidence:
Unknowns:
Resource commitment:
Opportunity cost:
Next action:
Confidence: High or Medium or Low, then why

Before the decision, write a short assessment of this subject. No fixed menu of opportunities, risks, and options. No task list."""


def is_ceo_request(query: str) -> bool:
    """True when the user explicitly asked for the CEO advisor."""
    text = query.lower()
    if any(
        marker in text
        for marker in (
            "ceo:",
            "ceo advisor",
            "ceo review",
            "ceo assessment",
            "quarterly strategic review",
            "challenge my current priorities",
            "as a ceo",
            "as the ceo",
        )
    ):
        return True
    return "ceo" in text and "evaluat" in text


def question_from(query: str) -> str:
    """The strategic question, with the invocation prefix removed."""
    text = query.strip()
    if text.lower() in {"ask ceo advisor", "ceo advisor"}:
        return "Give me a CEO assessment of the business as it stands."
    cleaned = re.sub(r"(?i)^ceo:\s*", "", text).strip()
    return cleaned or "Give me a CEO assessment of the business as it stands."


def is_track_request(query: str) -> bool:
    """True when the user asks to save the latest CEO recommendation."""
    text = query.lower()
    return "track this" in text or "track that" in text


class CeoAdvisorSkill(Skill):
    """One advisory assessment. It writes nothing except the skill run record."""

    name = "ceo_advisor"
    description = (
        "Assess a company, market, or choice for IDPETECH and recommend GO, "
        "CONDITIONAL GO, DEFER, or NO-GO. Advice only. It does not send, spend, or save."
    )

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        payload = task.get("payload") or {}
        question = str(payload.get("question") or "Give me a CEO assessment of the business as it stands.").strip()
        if not os.getenv("OPENAI_API_KEY"):
            return {
                "advisory": True,
                "executed": False,
                "error": "CEO Advisor needs the model. Set OPENAI_API_KEY.",
            }
        db_path = task.get("db_path")
        if not db_path:
            return {"advisory": True, "executed": False, "error": "CEO Advisor needs the desk database."}
        research = gather_research(question)
        context = build_context(
            db_path,
            task.get("profile_path") or DEFAULT_PROFILE_PATH,
            question,
            research,
        )
        try:
            assessment = _complete(question, context)
        except Exception as exc:
            return {"advisory": True, "executed": False, "error": f"CEO Advisor could not complete: {exc}"}
        if not _has_decision(assessment):
            return {
                "advisory": True,
                "executed": False,
                "error": "CEO Advisor did not reach a decision.",
                "assessment": assessment,
                "researched": research.get("status") == "ok",
                "research_note": research.get("note", ""),
            }
        if research.get("required") and research.get("status") != "ok":
            assessment = research["note"] + "\n\n" + assessment
        return {
            "advisory": True,
            "executed": False,
            "question": question,
            "assessment": assessment,
            "next_step": _next_action(assessment),
            "researched": research.get("status") == "ok",
            "research_note": research.get("note", ""),
            "sources": [item["url"] for item in research.get("snippets") or [] if item.get("url")],
        }


def research_required(question: str) -> bool:
    """Look the subject up unless the question is only about IDPETECH's own plan."""
    lowered = question.lower()
    if any(marker in lowered for marker in _INTERNAL_MARKERS) and not _names_outside_party(question):
        return False
    return True


def research_queries(question: str) -> list[str]:
    """Search the subject. Do not search IDPETECH's ICP or its current goals."""
    subject = re.sub(r"(?i)\b(for idpetech|idpetech)\b", " ", question)
    subject = re.sub(
        r"(?i)^(give me a ceo assessment of|ceo assessment of|assess whether|assess|should we|should idpetech)\s+",
        "",
        subject.strip(),
    )
    subject = re.sub(r"\s+", " ", subject).strip(" ?.")[:180]
    if not subject:
        return []
    return [subject, f"{subject} business model products customers strategy"]


def gather_research(question: str) -> dict[str, Any]:
    """Retrieve current public information, or say plainly that it was not retrieved."""
    if not research_required(question):
        return {
            "required": False,
            "status": "not_required",
            "note": "No external subject. A web lookup was not required.",
            "snippets": [],
        }
    if not os.getenv("TAVILY_API_KEY"):
        return {
            "required": True,
            "status": "unavailable",
            "note": "Research was not performed. TAVILY_API_KEY is not set.",
            "snippets": [],
        }
    snippets: list[dict[str, str]] = []
    errors: list[str] = []
    for query in research_queries(question):
        try:
            data = tavily_search(query, max_results=4)
        except Exception as exc:
            errors.append(str(exc))
            continue
        for item in data.get("results") or []:
            snippets.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "content": str(item.get("content") or "")[:500],
                }
            )
    if not snippets:
        detail = errors[0] if errors else "the search returned nothing"
        return {
            "required": True,
            "status": "failed",
            "note": f"Research was not performed. {detail}",
            "snippets": [],
        }
    return {
        "required": True,
        "status": "ok",
        "note": f"Retrieved {len(snippets)} public snippets for this question.",
        "snippets": snippets[:8],
    }


def build_context(db_path: str, profile_path, question: str, research: dict[str, Any]) -> str:
    """Four labeled categories. Operational work is included only for an operational question."""
    mandate, priorities, operations = _split_profile(profile_path)
    blocks = [
        "A. Business mandate. Source: principal profile, stated by the principal. This describes IDPETECH, not the subject.",
        mandate or "No business mandate is on file.",
        "",
        "B. Business intelligence. Source: a lookup just performed for this question. This is the subject, not IDPETECH.",
        _research_block(research),
        "",
        "C. Current priorities. Source: the desk. These are resource choices. They are not facts about the subject.",
        _priority_block(db_path, priorities, question),
        "",
        "D. Operational context.",
        _operation_block(db_path, question, operations),
        "",
        "Earlier recommendations. Source: previous CEO Advisor output. Not confirmed facts. Confidence: low.",
        _earlier_advice(db_path) or "None.",
    ]
    return "\n".join(blocks)


def track_latest_advice(db_path: str) -> dict[str, Any]:
    """Save the latest next action as a commitment. Does not call the model."""
    result = _latest_result(db_path)
    if not result:
        return {"status": "error", "message": "There is no CEO assessment to track."}
    title = str(result.get("next_step") or "").strip()
    if not title:
        return {"status": "error", "message": "The latest assessment has no next action to track."}
    add_commitment(db_path, title)
    return {"status": "ok", "title": title}


def _split_profile(profile_path) -> tuple[str, str, str]:
    data = _read_json(profile_path)
    mandate_lines = []
    priority_lines = []
    operation_lines = []
    for goal in _string_list(data.get("goals")):
        if _is_operational(goal):
            operation_lines.append("Stated operating goal: " + goal)
        elif re.search(r"this quarter|this month|this week", goal, re.IGNORECASE):
            priority_lines.append(
                "Current objective, for opportunity cost only. Not the definition of a fit: " + goal
            )
        else:
            mandate_lines.append("Stated objective: " + goal)
    icp = data.get("icp") if isinstance(data.get("icp"), str) else ""
    icp = icp.strip()
    if icp:
        priority_lines.append(
            "Current stated target customer, not a rule for every opportunity: " + icp
        )
    for rule in _string_list(data.get("will_not")):
        if _is_operational(rule):
            operation_lines.append("Operating constraint: " + rule)
        else:
            mandate_lines.append("Commercial constraint: " + rule)
    return "\n".join(mandate_lines), "\n".join(priority_lines), "\n".join(operation_lines)


def _priority_block(db_path: str, profile_priorities: str, question: str) -> str:
    lines = []
    if profile_priorities and (_about_current_offer(question) or "Not the definition of a fit" in profile_priorities):
        kept = []
        for line in profile_priorities.splitlines():
            if line.startswith("Current stated target") and not _about_current_offer(question):
                continue
            kept.append(line)
        if kept:
            lines.append("\n".join(kept))
    commitments = [
        row["title"]
        for row in list_commitments(db_path)
        if not _is_operational(row["title"])
    ]
    if commitments:
        lines.append("Open commercial commitments: " + "; ".join(commitments))
    kept = [row["title"] for row in list_pursuits(db_path) if not _is_operational(row["title"])]
    if kept:
        lines.append("Roles the principal kept: " + "; ".join(kept))
    queued = [row["company_name"] for row in list_icp_seed(db_path)]
    if queued:
        lines.append(
            "Companies queued for outreach. Queue membership is not a description of their business and is not evidence of fit: "
            + "; ".join(queued)
        )
    return "\n".join(lines) if lines else "No current commercial priorities are recorded."


def _operation_block(db_path: str, question: str, profile_operations: str) -> str:
    if not _question_is_operational(question):
        return "Omitted. This question is not about running the desk."
    lines = [profile_operations] if profile_operations else []
    try:
        lines.append("Morning line: " + morning_focus(db_path)["line"])
    except Exception:
        pass
    operational = [
        row["title"]
        for row in list_commitments(db_path)
        if _is_operational(row["title"])
    ]
    if operational:
        lines.append("Open operating commitments: " + "; ".join(operational))
    open_items = [
        row["title"]
        for row in list_open_priority_actions(min_priority=0, db_path=db_path)
        if _is_operational(row["title"])
    ][:8]
    if open_items:
        lines.append("Open desk items: " + "; ".join(open_items))
    return "\n".join(line for line in lines if line) or "No operating items are recorded."


def _research_block(research: dict[str, Any]) -> str:
    if research.get("status") != "ok":
        return research.get("note") or "Research was not performed."
    lines = [research.get("note") or "Retrieved public snippets."]
    for item in research.get("snippets") or []:
        lines.append(f"- {item['title']} ({item['url']}): {item['content']}")
    return "\n".join(lines)


def _read_json(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _question_is_operational(question: str) -> bool:
    lowered = question.lower()
    return any(word in lowered for word in ("inbox", "email", "calendar", "linkedin", "publish", "what's urgent", "what is urgent"))


def _is_operational(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _OPERATIONAL_WORDS)


def _names_outside_party(question: str) -> bool:
    if re.search(r"\b(ChatGPT|Claude|OpenAI|Anthropic)\b", question):
        return True
    body = re.sub(r"^\W*\w+", "", question.strip())
    names = re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3}", body)
    ignored = {"idpetech", "ceo", "i", "go", "no"}
    return any(name.lower() not in ignored for name in names)


def _about_current_offer(question: str) -> bool:
    """True when the question is about IDPETECH's own offer, so the ICP belongs in view."""
    lowered = question.lower()
    return any(
        word in lowered
        for word in ("fractional", "retainer", "advisory", "target customer", " icp", "my priorities", "our offer")
    )


def _plain(text: str) -> str:
    return re.sub(r"\*+", "", text)


def _has_decision(text: str) -> bool:
    plain = _plain(text)
    if not re.search(r"Decision:\s*(CONDITIONAL GO|NO-GO|DEFER|GO)\b", plain):
        return False
    return all(label in plain for label in DECISION_LABELS)


def _next_action(text: str) -> str:
    match = re.search(r"Next action:\s*(.+)", _plain(text))
    if not match:
        match = re.search(r"Next step:\s*(.+)", text)
    if not match:
        return ""
    line = match.group(1).strip().strip("-").strip()
    line = re.sub(r"\*+", "", line).strip()
    return line[:240]


def _complete(question: str, context: str) -> str:
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Request. Answer this request. Do not answer a different question.\n"
                    f"{question}\n\n"
                    "Context. Use a part only when it changes the answer to the request.\n"
                    f"{context}\n\n"
                    "If IDPETECH cannot sell, build, or be accountable for this subject with capabilities it already has, "
                    "the decision is NO-GO even when other people make money in that market. "
                    "Do not turn the answer into a study or a campaign."
                ),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


def _earlier_advice(db_path: str) -> str:
    lines = []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT result_json FROM skill_runs
                WHERE skill_name = 'ceo_advisor'
                ORDER BY executed_at DESC LIMIT 2
                """
            ).fetchall()
    except sqlite3.Error:
        return ""
    for (raw,) in rows:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            continue
        text = str(result.get("assessment") or "").strip()
        if text:
            lines.append(text[:400])
    return "\n---\n".join(lines)


def _latest_result(db_path: str) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT result_json FROM skill_runs
                WHERE skill_name = 'ceo_advisor'
                ORDER BY executed_at DESC LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        result = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None
