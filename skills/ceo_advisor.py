"""CEO Advisor: an independent assessment. It does not act."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

from desk_work import add_commitment
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import morning_focus
from desk_settings import list_icp_seed
from icp_workflow import company_key
from principal_profile import DEFAULT_PROFILE_PATH
from priority_inbox import list_open_priority_actions
from skills.base import Skill
from skills.tavily_client import tavily_search

logger = logging.getLogger(__name__)


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
- Use a context section only where it changes that answer. Business identity describes IDPETECH. A quarterly objective is opportunity cost, not the definition of the business. Operations stay out unless the request is about running the desk.
- A queued company, an ICP candidate, and an earlier recommendation are not verified facts about the subject.
- Separate five judgments in sentences: strategically interesting, commercially real for someone, commercially real for IDPETECH, deliverable by IDPETECH, and worth the resource commitment. Name the reason. A judgment answered with only UNKNOWN, REPORTED, ASSUMED, or VERIFIED is invalid.
- Search snippets are reports of what a page excerpt said. They are not a full-page reading. In Evidence, write the claim in words, then say that a snippet reported it, that you assumed it, or that it is unknown. Do not invent customers, revenue, or willingness to pay.
- If IDPETECH has no capability, customer, or mandate to sell, build, or be accountable for the subject, decide NO-GO. If the fit is unknown or only assumed, decide DEFER.
- CONDITIONAL GO means the subject is already close to work IDPETECH can do, and one named condition would make it a GO.
- GO means there is evidence a buyer would pay IDPETECH, or a measurable result IDPETECH can already deliver.
- ChatGPT and Claude are the buyer's first alternative for generic information, advice, research, writing, or recommendations. Name the accountability, judgment, or implementation IDPETECH adds, or say there is none.
- The next action is one concrete step, or "Stop. Do not pursue this." It is not authorization to send, spend, or publish.
- Strategic rationale and commercial rationale are sentences that name the reason. A rationale that is only UNKNOWN, REPORTED, ASSUMED, or VERIFIED is invalid.
- Return one JSON object and nothing else. The keys are assessment, decision, strategic_rationale, commercial_rationale, evidence, unknowns, assumptions, conditions, resource_commitment, opportunity_cost, next_action, and confidence.
- decision is exactly GO, CONDITIONAL GO, DEFER, or NO-GO. confidence starts with High, Medium, or Low, then a short reason."""


_LOOKUP_PATTERNS = (
    r"\bwhat did we decide\b",
    r"\bopportunities did we reject\b",
    r"\bwhich decisions are conditional\b",
    r"\bconditions remain\b",
    r"\brevisit our assessment\b",
)

_OPERATIONAL_PATTERNS = (
    r"\b(draft|write|send|prepare|schedule)\b.{0,48}\b(email|e-mail|note|message|calendar|meeting|linkedin|post)\b",
    r"\bfollow-up email\b",
    r"\bwhat'?s urgent\b",
    r"\bwhat is urgent\b",
    r"\binbox\b",
    r"\bcheck email\b",
)

_INFORMATIONAL_PATTERNS = (
    r"^(tell me about|what is|what's|who is|explain|describe)\b",
)

_STRATEGIC_PATTERNS = (
    r"\bassess\b",
    r"\bevaluate\b",
    r"\bshould (i|we|idpetech)\b",
    r"\bworth\b.{0,24}\b(my|our|idpetech)\b",
    r"\bworth (our|my|idpetech|the) time\b",
    r"\bworth entering\b",
    r"\breview the quarter\b",
    r"\bcommercial potential\b",
    r"\bstrategic opinion\b",
    r"\bchallenge my\b",
    r"\breassess\b",
    r"\bpursue\b",
    r"\bceo advisor\b",
    r"\bceo review\b",
    r"\bceo assessment\b",
    r"\bquarterly strategic review\b",
    r"\bas a ceo\b",
    r"\bas the ceo\b",
    r"^ceo:",
)


def classify_request(query: str) -> str:
    """strategic, decision_lookup, operational, informational, or ambiguous."""
    text = (query or "").strip().lower()
    if any(re.search(pattern, text) for pattern in _LOOKUP_PATTERNS):
        return "decision_lookup"
    operational = any(re.search(pattern, text) for pattern in _OPERATIONAL_PATTERNS)
    strategic = any(re.search(pattern, text) for pattern in _STRATEGIC_PATTERNS)
    if operational and strategic:
        explicit = re.search(r"\b(ceo advisor|ceo assessment|should (i|we|idpetech)|reassess)\b", text)
        return "strategic" if explicit else "operational"
    if operational:
        return "operational"
    if strategic:
        return "strategic"
    if any(re.search(pattern, text) for pattern in _INFORMATIONAL_PATTERNS):
        return "informational"
    return "ambiguous"


def is_ceo_request(query: str) -> bool:
    """True when the desk must answer with the CEO skill and not the chat model."""
    return classify_request(query) == "strategic"


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
        started = time.perf_counter()
        payload = task.get("payload") or {}
        question = str(payload.get("question") or "Give me a CEO assessment of the business as it stands.").strip()
        db_path = task.get("db_path")
        subject = _subject(question)
        logger.info("ceo_advisor start subject=%s", subject[:80])
        if not db_path:
            return {"advisory": True, "executed": False, "error": "CEO Advisor needs the desk database."}
        research = gather_research(question)
        logger.info(
            "ceo_advisor research status=%s snippets=%s",
            research.get("status"),
            len(research.get("snippets") or []),
        )
        if research.get("required") and research.get("status") != "ok":
            result = _defer_for_research(question, research)
            return _finish(db_path, question, result, started)
        if not os.getenv("OPENAI_API_KEY"):
            return {
                "advisory": True,
                "executed": False,
                "error": "CEO Advisor needs the model. Set OPENAI_API_KEY.",
            }
        context = build_context(
            db_path,
            task.get("profile_path") or DEFAULT_PROFILE_PATH,
            question,
            research,
        )
        try:
            raw = _complete(question, context)
            parsed = _parse_model_json(raw)
            if not parsed:
                logger.warning("ceo_advisor structured output invalid; asking once more")
                raw = _complete(
                    question + "\n\nThe previous reply was not a valid JSON decision. Return only the JSON object.",
                    context,
                )
                parsed = _parse_model_json(raw)
        except Exception as exc:
            logger.warning("ceo_advisor model failed: %s", exc)
            return {"advisory": True, "executed": False, "error": f"CEO Advisor could not complete: {exc}"}
        if not parsed:
            return {
                "advisory": True,
                "executed": False,
                "error": "CEO Advisor did not reach a decision.",
                "assessment": raw,
                "researched": research.get("status") == "ok",
                "research_note": research.get("note", ""),
            }
        result = _result_from_model(question, parsed, research)
        return _finish(db_path, question, result, started)


def research_required(question: str) -> bool:
    """Look the subject up when the question depends on an outside party or market."""
    lowered = question.lower()
    if any(marker in lowered for marker in _INTERNAL_MARKERS) and not _names_outside_party(question):
        return False
    if _names_outside_party(question):
        return True
    return any(
        word in lowered
        for word in ("market", "opportunit", "business model", "competitor", "application", "industry")
    )


def research_queries(question: str) -> list[str]:
    """Search the subject. Do not search IDPETECH's ICP or its current goals."""
    subject = _subject(question)
    if not subject:
        return []
    return [
        f"{subject} official website",
        f"{subject} products customers pricing business model",
        f"{subject} competitors customers partnerships",
    ]


def gather_research(question: str) -> dict[str, Any]:
    """Retrieve public snippets, or say plainly that the lookup did not happen."""
    if not research_required(question):
        return {
            "required": False,
            "status": "not_required",
            "research_status": "NOT_RUN",
            "note": "No external subject. A web lookup was not required.",
            "snippets": [],
        }
    if not os.getenv("TAVILY_API_KEY"):
        return {
            "required": True,
            "status": "unavailable",
            "research_status": "NOT_RUN",
            "note": "Research was not performed. TAVILY_API_KEY is not set.",
            "snippets": [],
        }
    snippets: list[dict[str, str]] = []
    seen: set[str] = set()
    errors: list[str] = []
    subject = _subject(question)
    for query in research_queries(question):
        try:
            data = tavily_search(query, max_results=4)
        except Exception as exc:
            errors.append(str(exc))
            continue
        for item in data.get("results") or []:
            url = str(item.get("url") or "")
            if url in seen:
                continue
            seen.add(url)
            snippets.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": url,
                    "content": str(item.get("content") or "")[:500],
                    "source_class": _source_class(subject, url),
                }
            )
    if not snippets:
        detail = errors[0] if errors else "the search returned nothing"
        return {
            "required": True,
            "status": "failed",
            "research_status": "NOT_RUN",
            "note": f"Research was not performed. {detail}",
            "snippets": [],
        }
    snippets.sort(key=lambda item: item["source_class"] != "possible_primary")
    kept = snippets[:8]
    primary = any(item["source_class"] == "possible_primary" for item in kept)
    note = (
        f"Retrieved {len(kept)} search snippets. "
        "These are excerpts, not full pages. Claims in them are REPORTED, not verified by reading the page."
    )
    if not primary:
        note += " No primary-source page was identified."
    if errors:
        note += f" Some searches failed: {errors[0]}"
    return {
        "required": True,
        "status": "ok",
        "research_status": "COMPLETE" if primary and not errors else "PARTIAL",
        "note": note,
        "snippets": kept,
    }


def build_context(db_path: str, profile_path, question: str, research: dict[str, Any]) -> str:
    """Four labeled categories. Operational work is included only for an operational question."""
    mandate, priorities, operations = _split_profile(profile_path)
    blocks = [
        "A. Business identity. Source: principal profile, stated by the principal. This describes IDPETECH, not the subject. User-stated, not a verified market fact.",
        mandate or "No longer-term business identity is on file. Do not treat a quarterly objective as the business mandate.",
        "",
        "B. Business intelligence. Source: a lookup just performed for this question. This is the subject, not IDPETECH.",
        _research_block(research),
        "",
        "C. Current priorities. Source: the desk. Opportunity cost and resource choices. Not facts about the subject, and not the definition of the business.",
        _priority_block(db_path, priorities, question) if _wants_priorities(question) else "Omitted. The quarterly objective is not the test for this request.",
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
    saved = add_commitment(db_path, title, decision_id=str(result.get("decision_id") or ""))
    if saved.get("status") != "ok":
        return saved
    if saved.get("duplicate"):
        message = "That action is already tracked. Tracking does not send, spend, or publish."
    else:
        message = f"Tracked: {title}. Tracking does not send, spend, or publish."
    return {
        "status": "ok",
        "title": title,
        "message": message,
        "commitment_id": saved.get("commitment_id"),
        "duplicate": bool(saved.get("duplicate")),
    }


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
        mandate_lines.append(
            "Current stated target customer, not a rule for every opportunity: " + icp
        )
    for rule in _string_list(data.get("will_not")):
        if _is_operational(rule):
            operation_lines.append("Operating constraint: " + rule)
        else:
            mandate_lines.append("Commercial constraint: " + rule)
    return "\n".join(mandate_lines), "\n".join(priority_lines), "\n".join(operation_lines)


def _priority_block(db_path: str, profile_priorities: str, question: str) -> str:
    lines = [profile_priorities] if profile_priorities else []
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
            "Companies named on the outreach seed list. A seed row is not a qualified prospect and is not evidence of fit: "
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
        lines.append(
            f"- [{item.get('source_class', 'independent')}] {item['title']} ({item['url']}): {item['content']}"
        )
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


def _wants_priorities(question: str) -> bool:
    lowered = question.lower()
    return any(
        word in lowered
        for word in (
            "priorit",
            "quarter",
            "pursue",
            "worth",
            "opportunit",
            "invest",
            "spend",
            "customer",
            "partner",
            "prospect",
        )
    )


def _plain(text: str) -> str:
    return re.sub(r"\*+", "", text)


def _text_field(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _list_field(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _rationale_ok(text: str) -> bool:
    """A rationale has to say the reason. A label grid is not a reason."""
    body = text.strip()
    if len(body) < 8:
        return False
    if body.lower() in {"unknown", "reported", "assumed", "verified", "none", "none stated."}:
        return False
    labels = re.findall(
        r"(strategically interesting|commercially real|deliverable by idpetech|worth the resource commitment)"
        r"\s*:\s*(unknown|reported|assumed|verified)\b",
        body,
        re.I,
    )
    return len(labels) < 2


def _parse_model_json(text: str) -> dict[str, Any] | None:
    """Read one JSON decision. Prose and a missing decision are rejected."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    decision = re.sub(r"\s+", " ", str(data.get("decision") or "").strip().upper())
    matched = ""
    for name in ("CONDITIONAL GO", "NO-GO", "DEFER", "GO"):
        if decision == name:
            matched = name
            break
    if not matched:
        return None
    strategic = _text_field(data.get("strategic_rationale"))
    commercial = _text_field(data.get("commercial_rationale"))
    if not _rationale_ok(strategic) or not _rationale_ok(commercial):
        return None
    confidence_raw = _text_field(data.get("confidence")) or "Low"
    return {
        "assessment": _text_field(data.get("assessment")),
        "decision": matched,
        "strategic_rationale": strategic,
        "commercial_rationale": commercial,
        "evidence": _list_field(data.get("evidence")),
        "unknowns": _list_field(data.get("unknowns")),
        "assumptions": _list_field(data.get("assumptions")),
        "conditions": _list_field(data.get("conditions")),
        "resource_commitment": _text_field(data.get("resource_commitment")),
        "opportunity_cost": _text_field(data.get("opportunity_cost")),
        "next_action": _text_field(data.get("next_action"))[:240],
        "confidence": confidence_raw,
    }


def _result_from_model(question: str, parsed: dict[str, Any], research: dict[str, Any]) -> dict[str, Any]:
    sources = [item["url"] for item in research.get("snippets") or [] if item.get("url")]
    action = str(parsed.get("next_action") or "")[:240]
    result = {
        "advisory": True,
        "executed": False,
        "question": question,
        "subject": _subject(question),
        "assessment": str(parsed.get("assessment") or ""),
        "decision": parsed.get("decision") or "",
        "strategic_rationale": parsed.get("strategic_rationale") or "",
        "commercial_rationale": parsed.get("commercial_rationale") or "",
        "evidence": parsed.get("evidence") or [],
        "unknowns": parsed.get("unknowns") or [],
        "assumptions": parsed.get("assumptions") or [],
        "conditions": parsed.get("conditions") or [],
        "resource_commitment": parsed.get("resource_commitment") or "",
        "opportunity_cost": parsed.get("opportunity_cost") or "",
        "next_step": action,
        "next_action": action,
        "confidence": parsed.get("confidence") or "Low",
        "sources": sources,
        "research_status": research.get("research_status") or "NOT_RUN",
        "research_note": research.get("note", ""),
        "researched": research.get("status") == "ok",
    }
    result["display"] = _display(result)
    return result


def _complete(question: str, context: str) -> str:
    response = OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        response_format={"type": "json_object"},
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
                    "Do not turn the answer into a study or a campaign. Return only the JSON object."
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


def _subject(question: str) -> str:
    body = re.sub(r"^\W*\w+", "", (question or "").strip())
    names = re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,3}", body)
    ignored = {"idpetech", "ceo", "i", "go", "no"}
    kept = [name for name in names if name.lower() not in ignored]
    if kept:
        return kept[0][:120]
    cleaned = re.sub(r"(?i)\b(for idpetech|idpetech)\b", " ", question or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?.")
    return cleaned[:120]


def _source_class(subject: str, url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    compact_subject = re.sub(r"[^a-z0-9]", "", subject.lower())
    compact_host = re.sub(r"[^a-z0-9]", "", host)
    if compact_subject and len(compact_subject) > 4 and compact_subject in compact_host:
        return "possible_primary"
    token = re.sub(r"[^a-z0-9]", "", (subject.split() or [""])[0].lower())
    if len(token) > 4 and token in host:
        return "possible_primary"
    return "independent"


def _defer_for_research(question: str, research: dict[str, Any]) -> dict[str, Any]:
    note = research.get("note") or "Research was not performed."
    result = {
        "advisory": True,
        "executed": False,
        "question": question,
        "subject": _subject(question),
        "assessment": note,
        "decision": "DEFER",
        "strategic_rationale": "The subject was not looked up, so there is no basis for a fit judgment.",
        "commercial_rationale": "No commercial evidence was retrieved.",
        "evidence": [],
        "unknowns": [note],
        "assumptions": [],
        "conditions": ["Research has to run before this can be decided."],
        "resource_commitment": "None until the subject is looked up.",
        "opportunity_cost": "None. No work was started.",
        "next_step": "Stop. Do not pursue this until the lookup can run.",
        "next_action": "Stop. Do not pursue this until the lookup can run.",
        "confidence": "LOW",
        "sources": [],
        "research_status": "NOT_RUN",
        "research_note": note,
        "researched": False,
    }
    result["display"] = _display(result)
    return result


def _display(result: dict[str, Any]) -> str:
    def line(label: str, value: object) -> str:
        if isinstance(value, list):
            text = "; ".join(str(item) for item in value if str(item).strip()) or "None stated."
        else:
            text = str(value or "None stated.")
        return f"{label}: {text}"

    opening = str(result.get("summary") if result.get("summary") is not None else result.get("assessment") or "").strip()
    parts = [
        opening,
        "",
        line("Decision", result.get("decision")),
        line("Strategic rationale", result.get("strategic_rationale")),
        line("Commercial rationale", result.get("commercial_rationale")),
        line("Evidence", result.get("evidence")),
        line("Unknowns", result.get("unknowns")),
        line("Assumptions", result.get("assumptions")),
        line("Conditions", result.get("conditions")),
        line("Resource commitment", result.get("resource_commitment")),
        line("Opportunity cost", result.get("opportunity_cost")),
        line("Next action", result.get("next_action") or result.get("next_step")),
        line("Confidence", result.get("confidence")),
    ]
    sources = result.get("sources") or []
    if sources:
        parts.append("Sources:")
        parts.extend(f"- {url}" for url in sources)
    if result.get("research_note"):
        parts.append("")
        parts.append(str(result["research_note"]))
    skill = _suggested_skill(str(result.get("next_action") or result.get("next_step") or ""))
    if skill:
        parts.append(
            f"Suggested existing skill, not run: {skill}. "
            "Ask the desk to prepare it if you want that draft. That does not send, spend, or publish."
        )
    parts.append("")
    parts.append(
        "This is advice. Nothing was sent, spent, or saved. "
        "Tracking the next action does not authorize sending, spending, or publishing."
    )
    return "\n".join(parts).strip()


def _suggested_skill(action: str) -> str:
    """Name an existing skill. This does not call it."""
    text = action.lower()
    if re.search(r"\b(email|e-mail|outreach|note|message)\b", text):
        return "outreach_draft"
    if re.search(r"\b(agenda|calendar|meeting)\b", text):
        return "calendar_prep"
    if re.search(r"\b(linkedin|blog|post)\b", text):
        return "blogger"
    if re.search(r"\b(research|look up)\b", text):
        return "icp_prospector"
    return ""


def _finish(db_path: str, question: str, result: dict[str, Any], started: float) -> dict[str, Any]:
    saved = save_decision(db_path, question, result)
    elapsed = int((time.perf_counter() - started) * 1000)
    if saved.get("status") == "ok":
        result["decision_id"] = saved.get("decision_id")
        logger.info(
            "ceo_advisor saved decision=%s id=%s ms=%s",
            result.get("decision"),
            result.get("decision_id"),
            elapsed,
        )
    else:
        result["persistence_warning"] = saved.get("message") or "The assessment was not saved."
        result["display"] = _display(result) + "\n\nWarning: " + result["persistence_warning"]
        logger.warning("ceo_advisor persistence failed ms=%s", elapsed)
    return result


DECISIONS_SQL = """
CREATE TABLE IF NOT EXISTS strategic_decisions (
    decision_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    strategic_rationale TEXT NOT NULL DEFAULT '',
    commercial_rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    unknowns_json TEXT NOT NULL DEFAULT '[]',
    assumptions_json TEXT NOT NULL DEFAULT '[]',
    conditions_json TEXT NOT NULL DEFAULT '[]',
    resource_commitment TEXT NOT NULL DEFAULT '',
    opportunity_cost TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    research_status TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    reviewed_at TEXT NOT NULL DEFAULT '',
    parent_decision_id TEXT NOT NULL DEFAULT ''
)
"""


def ensure_decisions(db_path: str) -> None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        with conn:
            conn.execute(DECISIONS_SQL)
    finally:
        conn.close()


def save_decision(db_path: str, question: str, result: dict[str, Any]) -> dict[str, Any]:
    """Store one assessment. A reassessment links to the previous record and does not replace it."""
    try:
        ensure_decisions(db_path)
        subject = str(result.get("subject") or _subject(question) or question)[:180]
        key = company_key(subject)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        parent = ""
        if re.search(r"\b(reassess|revisit)\b", question, re.I):
            prior = _latest_decision(db_path, key)
            parent = str(prior.get("decision_id") or "") if prior else ""
        decision_id = str(uuid.uuid4())
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO strategic_decisions (
                        decision_id, subject, subject_key, decision, strategic_rationale,
                        commercial_rationale, evidence_json, unknowns_json, assumptions_json,
                        conditions_json, resource_commitment, opportunity_cost, next_action,
                        confidence, sources_json, research_status, status, created_at,
                        updated_at, reviewed_at, parent_decision_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, '', ?)
                    """,
                    (
                        decision_id,
                        subject,
                        key,
                        result.get("decision") or "",
                        result.get("strategic_rationale") or "",
                        result.get("commercial_rationale") or "",
                        json.dumps(result.get("evidence") or []),
                        json.dumps(result.get("unknowns") or []),
                        json.dumps(result.get("assumptions") or []),
                        json.dumps(result.get("conditions") or []),
                        result.get("resource_commitment") or "",
                        result.get("opportunity_cost") or "",
                        result.get("next_action") or result.get("next_step") or "",
                        result.get("confidence") or "",
                        json.dumps(result.get("sources") or []),
                        result.get("research_status") or "",
                        now,
                        now,
                        parent,
                    ),
                )
        finally:
            conn.close()
        return {"status": "ok", "decision_id": decision_id, "parent_decision_id": parent}
    except sqlite3.Error as exc:
        return {"status": "error", "message": f"The assessment was not saved. {exc}"}


def _latest_decision(db_path: str, subject_key: str) -> dict[str, Any] | None:
    ensure_decisions(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT * FROM strategic_decisions
            WHERE subject_key = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (subject_key,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def answer_decision_lookup(db_path: str, query: str) -> str:
    """Read stored decisions. This does not run a new assessment."""
    try:
        ensure_decisions(db_path)
    except sqlite3.Error as exc:
        return f"Previous decision not found. {exc}"
    lowered = query.lower()
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        if "reject" in lowered:
            rows = conn.execute(
                "SELECT subject, decision, next_action FROM strategic_decisions WHERE decision = 'NO-GO' ORDER BY created_at DESC LIMIT 8"
            ).fetchall()
        elif "conditional" in lowered or "conditions remain" in lowered:
            rows = conn.execute(
                """
                SELECT subject, decision, conditions_json, next_action FROM strategic_decisions
                WHERE decision = 'CONDITIONAL GO' ORDER BY created_at DESC LIMIT 8
                """
            ).fetchall()
        else:
            key = company_key(_subject(query))
            rows = conn.execute(
                """
                SELECT subject, decision, strategic_rationale, conditions_json, next_action, created_at
                FROM strategic_decisions WHERE subject_key = ? ORDER BY created_at DESC LIMIT 5
                """,
                (key,),
            ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "No stored decision matches that request."
    lines = []
    for row in rows:
        item = dict(row)
        lines.append(f"{item.get('subject')}: {item.get('decision')}. Next action: {item.get('next_action') or 'none'}.")
        if item.get("conditions_json"):
            lines.append("Conditions: " + item["conditions_json"])
    lines.append("This is the stored advice. It is not a new decision.")
    return "\n".join(lines)
