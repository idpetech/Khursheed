"""Classify, score, and present discoveries already stored for the morning brief.

Scoring is a fixed set of weights over stored text. It does not call a model,
does not fetch links, and does not write a commitment. Deduped lines are a
view: the skill runs and loops they came from stay in place.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

from runtime import resolve_db_path


CLASSES = ("engagement", "prospect", "partner", "competitor", "research", "unknown")

WEIGHTS = {
    "experience_alignment": 30,
    "commercial_advisory_fit": 25,
    "engagement_compatibility": 20,
    "evidence_credibility": 15,
    "geographic_market_fit": 10,
}

_EXPERIENCE = (
    "wms",
    "warehouse",
    "supply chain",
    "supply-chain",
    "erp",
    "sap",
)
_ADVISORY = (
    "fractional cto",
    "fractional advisor",
    "strategic advisory",
    "enterprise architecture",
    "architecture decision",
    "enterprise ai",
    "practical ai",
    "practical enterprise",
)
_MARKET = ("b2b saas", "b2b", "fintech", "healthtech", "saas")
_ENGAGEMENT_WORDS = (
    "fractional",
    "interim",
    "part-time",
    "part time",
    "advisory",
    "advisor",
    "consulting",
    "consultant",
    "retainer",
)
_FULL_TIME = re.compile(r"\b(full[\s-]?time|daily availability|day-to-day|operational ownership)\b")
_NOT_FULL_TIME = re.compile(r"\b(not|no|without)\s+(a\s+)?full[\s-]?time\b")
_SERVICE = (
    "our services",
    "we provide",
    "our fractional",
    "book a call",
    "how we help",
    "we help companies",
)
_PARTNER = (
    "marketplace",
    "referral partner",
    "partner program",
    "directory of",
    "talent network",
    "channel partner",
)
_NEED = (
    "hiring",
    "no cto",
    "without a cto",
    "looking for",
    "advisory",
    "fractional",
    "exploring",
)
_GENERIC_COMPANIES = {
    "cto",
    "chief technology officer",
    "unknown",
    "role",
    "lead",
    "company",
    "remote",
    "hybrid",
    "united states",
    "usa",
    "florida",
}
_GENERIC_TITLES = {
    "fractional cto",
    "cto",
    "chief technology officer",
    "interim cto",
    "part time cto",
    "role",
    "lead",
    "unknown",
}
_BOARD_HOSTS = (
    "indeed.com",
    "ziprecruiter.com",
    "glassdoor.com",
    "youtube.com",
    "youtu.be",
    "jobleads.com",
    "recruitfractional.com",
    "gofractional.com",
    "ctodirectory.com",
    "arc.dev",
    "upwork.com",
    "findyourcto.com",
)
_JOB_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "linkedin.com/jobs")
_DIRECTORY_TITLES = (
    "ctos in",
    "best freelance",
    "for hire",
    "now hiring",
    "hiring now",
    "apply today",
    "jobs in",
    "great pay",
)
_BAD_COMPANY = {
    "indeed",
    "linkedin",
    "linkedin jobs",
    "ziprecruiter",
    "jobleads",
    "united states",
    "usa",
    "remote",
    "florida",
    "jobs",
    "apply today",
    "find your cto",
}
_SEEN_KEY = "brief_seen"


def normalize_url(url: str) -> str:
    """Host and path, without a scheme, www, fragment, or utm query."""
    text = (url or "").strip()
    if not text:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = "https://" + text
    parts = urlparse(text)
    host = parts.netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    if host.startswith("www."):
        host = host[4:]
    if host.endswith(":80"):
        host = host[:-3]
    if host.endswith(":443"):
        host = host[:-4]
    path = re.sub(r"/+$", "", parts.path or "")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not key.lower().startswith("utm_")
    ]
    query.sort()
    if not host:
        return ""
    return urlunparse(("", host, path, "", urlencode(query), ""))


def normalize_name(text: str) -> str:
    """Lowercase name with legal suffixes and punctuation removed."""
    lowered = (text or "").lower().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    suffixes = {"inc", "llc", "ltd", "corp", "corporation", "company", "co"}
    parts = [part for part in lowered.split() if part and part not in suffixes]
    return " ".join(parts).strip()


def companies_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) < 5:
        return False
    return long.startswith(short + " ")


def company_key(name: str) -> str:
    key = normalize_name(name)
    if key in _GENERIC_COMPANIES or len(key) < 3:
        return ""
    return key


def title_key(title: str) -> str:
    key = normalize_name(title)
    if key in _GENERIC_TITLES or len(key) < 8:
        return ""
    return key


def prepare_items(runs: list[dict[str, Any]], loops: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Collect, dedupe, classify, and score. Rows passed in are not modified."""
    collected = collect_discovered(runs, loops or [])
    merged = dedupe_items(collected)
    return [score_item(item) for item in merged]


def collect_discovered(runs: list[dict[str, Any]], loops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for run in runs:
        payload = _parse_result(run.get("result_json"))
        found = run.get("executed_at") or ""
        skill = str(run.get("skill_name") or "")
        if skill == "cto_radar":
            for row in payload.get("opportunities") or []:
                if isinstance(row, dict):
                    items.append(_from_role(row, skill, found))
        elif skill == "lead_scout":
            for query in payload.get("queries") or []:
                if not isinstance(query, dict):
                    continue
                for row in query.get("leads") or []:
                    if isinstance(row, dict):
                        items.append(_from_role(row, skill, found))
        elif skill == "icp_prospector":
            for row in payload.get("top_companies") or []:
                if isinstance(row, dict):
                    items.append(_from_company(row, skill, found, model_name=False))
        elif skill == "icp_finder":
            for row in payload.get("candidates") or []:
                if isinstance(row, dict):
                    items.append(_from_company(row, skill, found, model_name=True))
    for loop in loops:
        items.append(_from_loop(loop))
    return [item for item in items if item.get("title") or item.get("company")]


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge a presentation list. The input list is left as it was."""
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    url_index: dict[str, int] = {}
    title_index: dict[str, int] = {}
    company_index: dict[str, int] = {}
    for index, item in enumerate(items):
        url = item.get("url_key") or ""
        if url:
            if url in url_index:
                union(index, url_index[url])
            else:
                url_index[url] = index
        titled = item.get("title_key") or ""
        if titled:
            if titled in title_index:
                union(index, title_index[titled])
            else:
                title_index[titled] = index
        company = item.get("company_key") or ""
        if company:
            matched = ""
            for existing in company_index:
                if companies_match(existing, company):
                    matched = existing
                    break
            if matched:
                union(index, company_index[matched])
            else:
                company_index[company] = index
    groups: dict[int, list[dict[str, Any]]] = {}
    for index, item in enumerate(items):
        groups.setdefault(find(index), []).append(item)
    return [_merge_group(group) for group in groups.values()]


def score_item(item: dict[str, Any]) -> dict[str, Any]:
    """Add class, 0-100 score, factor points, band, and confidence."""
    scored = dict(item)
    text = _blob(scored)
    scored["classification"] = classify_item(scored)
    scored["generic"] = _generic_noise(scored)
    scored["job_listing"] = _is_job_listing(scored)
    factors = {
        "experience_alignment": _experience_points(text),
        "commercial_advisory_fit": _commercial_points(text),
        "engagement_compatibility": _engagement_points(text),
        "evidence_credibility": _evidence_points(scored),
        "geographic_market_fit": _geo_points(text),
    }
    scored["factors"] = factors
    scored["score"] = int(sum(factors.values()))
    scored["band"] = band_for(scored["score"])
    scored["confidence"] = _confidence(scored)
    scored["icp_only"] = scored["classification"] == "prospect" and not _stated_need(text)
    scored["item_key"] = _item_key(scored)
    scored["evidence"] = evidence_hash(scored)
    scored["why"] = _why(scored, factors)
    scored["concerns"] = _concerns(scored)
    scored["next_action"] = _next_action(scored)
    return scored


def classify_item(item: dict[str, Any]) -> str:
    """One class. Thin stored evidence stays unknown."""
    if _thin(item):
        return "unknown"
    if _generic_noise(item) or _article(item):
        return "research"
    if _is_job_listing(item) and not _service_page(item):
        return "engagement"
    if _service_page(item):
        return "competitor"
    if _partner_page(item):
        return "partner"
    kind = item.get("record_kind") or ""
    if kind == "company" or (item.get("company") and not _engagement_language(_blob(item))):
        if item.get("company") and (item.get("industry") or item.get("funding_stage") or _stated_need(_blob(item))):
            return "prospect"
    if _engagement_language(_blob(item)):
        return "engagement"
    if kind == "company" and item.get("company"):
        return "prospect" if (item.get("industry") or item.get("funding_stage")) else "unknown"
    return "unknown"


def band_for(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def evidence_hash(item: dict[str, Any]) -> str:
    blob = "|".join(
        [
            str(item.get("classification") or ""),
            normalize_name(str(item.get("title") or "")),
            item.get("url_key") or normalize_url(str(item.get("url") or "")),
            normalize_name(str(item.get("snippet") or ""))[:240],
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def render_item(item: dict[str, Any]) -> str:
    """One compact block. Links are described as unverified."""
    lines = [
        (
            f"{item.get('title') or item.get('company') or 'Untitled'}"
            f" · {item.get('classification')}"
            f" · {item.get('score')} {item.get('band')}"
            f" · confidence {item.get('confidence')}"
        ),
        f"Why: {item.get('why') or ''}",
        "Factors: "
        + ", ".join(f"{name} {item.get('factors', {}).get(name, 0)}/{WEIGHTS[name]}" for name in WEIGHTS),
    ]
    concerns = item.get("concerns") or []
    if concerns:
        lines.append("Concern: " + " ".join(str(part) for part in concerns))
    lines.append(f"Next: {item.get('next_action') or 'No action is justified.'}")
    if item.get("url"):
        lines.append(f"Link: {item['url']}")
    sources = ", ".join(item.get("sources") or []) or "not stored"
    discovered = ", ".join(item.get("discovered") or []) or "not stored"
    lines.append(f"Sources: {sources}. Discovered: {discovered}.")
    return "\n".join(lines)


def section_blocks(items: list[dict[str, Any]], paused: bool, prospect_note: str = "") -> list[str]:
    """Markdown sections for the daily brief. Paused research hides new names."""
    if paused:
        return [
            "## Research and Watchlist",
            "_Research is waiting until the open role has a date._",
            "",
        ]
    blocks = [
        "## Best Engagement Opportunities",
        _format_engagements(items),
        "",
        "## Strategic Prospects",
        _format_prospects(items, prospect_note),
        "",
        "## Partners and Channels",
        _format_partners(items),
        "",
        "## Research and Watchlist",
        _format_watchlist(items),
        "",
    ]
    return blocks


def focus_details(
    items: list[dict[str, Any]],
    focus_lines: list[str],
    outstanding: int,
    deadlines: str,
    recommendation: str,
    name_findings: bool = True,
) -> list[str]:
    """Morning lines and one recommendation. Counts stay in brief_counts."""
    del items, outstanding, deadlines, name_findings
    lines = [f"- {line}" for line in focus_lines]
    if recommendation:
        lines.append(f"- Recommendation: {recommendation}")
    return lines


def recommendation_sentence(focus_lines: list[str], db_path: str | Path, today: date | None = None) -> str:
    """One recommendation. Unresolved alerts and bills come before a clear day."""
    for line in focus_lines:
        if str(line).startswith("Suggestion, not a commitment:"):
            return str(line)
    counts = brief_counts(db_path)
    if counts["priority_alerts"] or counts["pending_bills"]:
        return "Review the unresolved alerts and bills. Their current status is unverified."
    if counts["pending_approvals"] or counts["open_commitments"]:
        return "An approval or open commitment is still waiting."
    hint = next_suggestion(db_path, today)
    if hint.get("status") == "repeat":
        return "No new recommendation without new evidence."
    return (
        "No action is justified because no unresolved alert, bill, approval, "
        "or open commitment is stored."
    )


def next_suggestion(db_path: str | Path, today: date | None = None) -> dict[str, str]:
    """A high-priority item with no follow-up. Does not write a commitment."""
    try:
        items = _load_scored(db_path, today)
    except Exception:
        return {"status": "none", "line": "", "key": "", "evidence": ""}
    candidate = _best_unfollowed(db_path, items, high_only=True)
    if candidate is None:
        return {"status": "none", "line": "", "key": "", "evidence": ""}
    seen = _seen_map(db_path)
    evidence = str(candidate.get("evidence") or "")
    key = str(candidate.get("item_key") or "")
    if seen.get(key) == evidence:
        return {"status": "repeat", "line": "", "key": key, "evidence": evidence}
    title = candidate.get("title") or "Item"
    return {
        "status": "new",
        "line": f"Suggestion, not a commitment: {title}.",
        "key": key,
        "evidence": evidence,
    }


def remember_suggestion(db_path: str | Path, item_key: str, evidence: str) -> None:
    if not item_key or not evidence:
        return
    seen = _seen_map(db_path)
    seen[item_key] = evidence
    _write_seen(db_path, seen)


def format_open_commitments(rows: list[dict[str, Any]], today: date) -> str:
    """Open and blocked commitments only. Done and cancelled stay off."""
    lines: list[str] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status in {"done", "cancelled"}:
            continue
        if status not in {"open", "blocked"}:
            continue
        label = str(row.get("title") or "Commitment")
        if status == "blocked":
            label += " (blocked)"
        due = _parse_day(str(row.get("due_on") or ""))
        if due is not None and due < today:
            label += f" — past due {due.isoformat()}"
        elif due is not None:
            label += f" — due {due.isoformat()}"
        lines.append(f"- {label}")
    if not lines:
        return "_No open commitments._\n\n_A saved search page is not a commitment._"
    return "\n".join(lines) + "\n\n_A saved search page is not a commitment._"


def deadline_phrase(rows: list[dict[str, Any]], today: date) -> str:
    due_bits: list[str] = []
    for row in rows:
        status = str(row.get("status") or "")
        if status not in {"open", "blocked"}:
            continue
        due = _parse_day(str(row.get("due_on") or ""))
        if due is None:
            continue
        title = str(row.get("title") or "Commitment")
        if due < today:
            due_bits.append(f"{title}, past due {due.isoformat()}")
        else:
            due_bits.append(f"{title}, due {due.isoformat()}")
    if not due_bits:
        return "none stored."
    return "; ".join(due_bits[:3]) + "."


_ALERT_KINDS = {"mail_notice", "renewal_notice", "alert"}
_APPROVAL_KINDS = {"role_candidate", "skill_request", "icp_candidate"}
_DRAFT_KINDS = {"linkedin_post_draft", "outreach_draft", "brief_item"}
_ACTION_START = re.compile(
    r"^(call|email|e-mail|send|reply|pay|review|verify|follow up|schedule|meet|write|chase|file|confirm)\b",
    re.I,
)
_NO_ACTION = (
    "No action is justified because no unresolved alert, bill, approval, "
    "or open commitment is stored."
)
_CONTINUE_RESEARCH = (
    "Continue fractional CTO research only when a specific, credible opportunity appears."
)
_UNCONFIRMED = "No confirmed high-priority engagement identified."
_QUALIFIED = "No qualified fractional CTO engagement has yet been established."


def outstanding_count(db_path: str | Path) -> int:
    """Open or blocked commitments only. Alerts, bills, and approvals are separate."""
    return brief_counts(db_path)["open_commitments"]


_EMAIL_CLASSES = (
    "action_required",
    "financial_obligation",
    "financial_information",
    "important_document",
    "account_notification",
    "promotional",
    "informational",
)
_PROMO_MARKERS = (
    "coupon",
    "discount",
    "promo",
    "% off",
    "flash sale",
    "shop now",
    "shop the",
    "deal",
    "rewards",
    "credits to spend",
    "you earned",
    "sale ends",
)
_ACTION_MARKERS = (
    "deactivat",
    "will be cancel",
    "cancellation",
    "subscription will end",
    "payment failed",
    "payment failure",
    "account will be closed",
    "suspended",
    "action required",
    "response required",
    "please respond",
    "must respond",
    "must confirm",
    "confirm by",
    "reply by",
    "respond by",
    "return by",
    "please sign",
    "restore required",
    "coverage lapse",
    "lapses",
)
_WEAK_SUBJECT_WORDS = ("statement", "documents", "credits", "available", "important")


def classify_email(action: dict[str, Any]) -> str:
    """Check 1 on sender, subject, title, and snippet. Context cannot change this class."""
    from priority_inbox import BILL_KINDS

    if str(action.get("action_type") or "") in BILL_KINDS:
        return "financial_obligation"
    text = _message_text(action)
    if _is_promotional(text):
        return "promotional"
    if _account_harm(text) or _request_and_deadline(text):
        return "action_required"
    if _financial_information_email(text):
        return "financial_information"
    if _account_notification_email(text):
        return "account_notification"
    if _important_document_email(text):
        return "important_document"
    if _financial_obligation_email(text):
        return "financial_obligation"
    return "informational"


def verification_justified(action: dict[str, Any]) -> bool:
    """A sale stops first. Harm, or a request with a deadline, is the only verify-or-pay case."""
    from priority_inbox import BILL_KINDS

    if str(action.get("action_type") or "") in BILL_KINDS:
        return False
    text = _message_text(action)
    if _is_promotional(text):
        return False
    return _account_harm(text) or _request_and_deadline(text)


def pending_category(action: dict[str, Any]) -> str:
    """One category for a waiting row. A row is never an alert and a bill."""
    from priority_inbox import BILL_KINDS

    kind = str(action.get("action_type") or "")
    if kind in BILL_KINDS:
        return "bill"
    if kind in _APPROVAL_KINDS:
        return "approval"
    if kind in _DRAFT_KINDS:
        return "draft"
    if kind in _ALERT_KINDS:
        if classify_email(action) == "action_required":
            return "alert"
        return classify_email(action)
    return "other"


def brief_counts(db_path: str | Path) -> dict[str, int]:
    """Separate counts from stored rows. Research and drafts are not included."""
    counts = {
        "priority_alerts": 0,
        "pending_bills": 0,
        "pending_approvals": 0,
        "open_commitments": 0,
    }
    for action in _pending_rows(db_path):
        category = pending_category(action)
        if category == "alert":
            counts["priority_alerts"] += 1
        elif category == "bill":
            counts["pending_bills"] += 1
        elif category == "approval":
            counts["pending_approvals"] += 1
    try:
        from desk_work import list_commitments

        counts["open_commitments"] = len(list_commitments(db_path, ("open", "blocked")))
    except Exception:
        counts["open_commitments"] = 0
    return counts


def loop_is_explicit_action(loop: dict[str, Any]) -> bool:
    """A saved search, video, marketplace, or untitled draft is not an open loop."""
    from open_loops import loop_url

    title = str(loop.get("title") or "").strip()
    url = loop_url(loop)
    blob = f"{title} {loop.get('detail') or ''} {url}"
    if _is_research_url(url) or _is_research_text(blob):
        return False
    if _ACTION_START.match(title):
        return True
    due = str(loop.get("due_at") or "").strip()
    return bool(due and title and not _is_research_text(title))


def settle_priority_alert(db_path: str | Path, action_id: str, *, dismissed: bool = False) -> dict[str, Any]:
    """Mark one alert resolved or dismissed. The row stays in pending_actions."""
    status = "rejected" if dismissed else "acknowledged"
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return {"status": "error", "message": "That alert is not stored."}
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT action_id FROM pending_actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "That alert is not stored."}
        with conn:
            conn.execute(
                """
                UPDATE pending_actions
                SET status = ?, reviewed_by = 'desk', reviewed_at = ?
                WHERE action_id = ?
                """,
                (status, now, action_id),
            )
    except sqlite3.Error:
        return {"status": "error", "message": "Could not update that alert."}
    finally:
        conn.close()
    remember_suggestion(db_path, f"alert:{action_id}", status)
    word = "Dismissed." if dismissed else "Resolved."
    return {"status": "ok", "message": word}


def build_daily_brief(
    db_path: str | Path,
    runs: list[dict[str, Any]],
    loops: list[dict[str, Any]],
    focus_lines: list[str],
    pause_research: bool,
    today: date,
    research_note: str = "",
    prospect_note: str = "",
) -> str:
    """The morning note: five sections, each item in one category."""
    items = prepare_items(runs, loops)
    pending = _pending_rows(db_path)
    alerts = [row for row in pending if pending_category(row) == "alert"]
    bills = [row for row in pending if pending_category(row) == "bill"]
    approvals = [row for row in pending if pending_category(row) == "approval"]
    other_mail = [
        row
        for row in pending
        if str(row.get("action_type") or "") in _ALERT_KINDS and pending_category(row) != "alert"
    ]
    explicit = [loop for loop in loops if loop_is_explicit_action(loop)]
    counts = brief_counts(db_path)
    suggestions = [
        str(line).strip()
        for line in focus_lines
        if str(line).startswith("Suggestion, not a commitment:")
    ]
    market = _market_items(items, explicit)
    focus = _focus_prose(
        focus_lines,
        alerts,
        bills,
        approvals,
        explicit,
        items,
        counts,
        today,
        pause_research,
    )
    attention = _attention_lines(alerts, bills, other_mail, today)
    research = _research_body(items, explicit, pause_research, prospect_note, research_note, market)
    commitments = _commitments_body(db_path, today)
    actions = _recommended_lines(
        db_path,
        alerts,
        bills,
        approvals,
        explicit,
        suggestions,
        market,
        items,
        today,
    )
    sections = [
        ("Executive Focus", focus),
        ("Priority Attention", attention),
        ("Research and Opportunities", research),
        ("Open Commitments", commitments),
        ("Recommended Actions", "\n".join(actions)),
    ]
    title = f"# Executive Brief — {_spoken(today)}, {today.year}"
    blocks = [title, ""]
    for heading, body in sections:
        text = (body or "").strip()
        if heading == "Open Commitments":
            blocks.extend([f"## {heading}", text or "None.", ""])
        elif text:
            blocks.extend([f"## {heading}", text, ""])
    return "\n".join(blocks).rstrip() + "\n"


def _pending_rows(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return []
    try:
        from priority_inbox import list_open_priority_actions

        return list_open_priority_actions(min_priority=0, db_path=str(resolved))
    except Exception:
        return []


def _stored_payload(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("payload_json") or action.get("payload") or {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        try:
            import ast

            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _spoken(day: date) -> str:
    return f"{day.strftime('%B')} {day.day}"


def _spoken_from_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) >= 10:
        day = _parse_day(text[:10])
        if day is not None:
            return _spoken(day)
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    if parsed is None:
        return ""
    return _spoken(parsed.date())


def _due_date(action: dict[str, Any]) -> date | None:
    payload = _stored_payload(action)
    return _parse_day(str(payload.get("due_date") or "")[:10])


def _money(amount: Any, currency: Any) -> str:
    if amount in (None, ""):
        return ""
    if isinstance(amount, float):
        text = f"{amount:.2f}"
    else:
        text = str(amount).strip()
    if not text:
        return ""
    code = str(currency or "").strip().upper()
    if code in {"USD", "US$", "$"}:
        return text if text.startswith("$") else f"${text}"
    if code:
        return f"{text} {code}"
    return text


def _bill_name(action: dict[str, Any]) -> str:
    payload = _stored_payload(action)
    vendor = str(payload.get("vendor") or "").strip()
    if vendor:
        return vendor
    title = str(action.get("title") or "Bill").strip()
    kind = str(action.get("action_type") or "")
    prefix = f"{kind}:"
    if kind and title.lower().startswith(prefix.lower()):
        title = title[len(prefix) :].strip()
    return title or "Bill"


def _alert_name(action: dict[str, Any]) -> str:
    from executive_summary import mail_origin

    payload = _stored_payload(action)
    vendor = str(payload.get("vendor") or "").strip()
    if vendor:
        return vendor
    origin = mail_origin(action)
    sender = origin.get("sender") or ""
    display = sender.split("<", 1)[0].strip().strip('"')
    if display and "@" not in display:
        return display
    title = str(action.get("title") or "Alert").strip()
    return title or "Alert"


def _alert_key(action: dict[str, Any]) -> str:
    identity = action.get("action_id") or action.get("source_key") or action.get("title") or "alert"
    return f"alert:{identity}"


def _alert_evidence(action: dict[str, Any]) -> str:
    from executive_summary import mail_origin

    origin = mail_origin(action)
    blob = "|".join(
        [
            str(action.get("action_id") or ""),
            origin.get("subject") or "",
            origin.get("sent") or "",
            origin.get("sender") or "",
            str(action.get("title") or ""),
        ]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _alert_already_recommended(db_path: str | Path, action: dict[str, Any]) -> bool:
    return _seen_map(db_path).get(_alert_key(action)) == _alert_evidence(action)


def _message_text(action: dict[str, Any]) -> str:
    """Sender, subject, title, and snippet. One string. Description and body are not used."""
    payload = _stored_payload(action)
    parts = [
        payload.get("from") or payload.get("sender"),
        payload.get("subject"),
        action.get("title"),
        payload.get("snippet"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _email_text(action: dict[str, Any]) -> str:
    return _message_text(action)


def _is_promotional(text: str) -> bool:
    """A sale, reward, or discount stops here. A deadline on that offer is still promotional."""
    return bool(
        re.search(
            r"\b(discount|discounts|reward|rewards|coupon|coupons|promo|promotion|promotional|deal|deals|sale|sales)\b"
            r"|% off|flash sale|shop now|shop the",
            text,
        )
    )


def _account_harm(text: str) -> bool:
    """Deactivation, suspension, a failed payment, or a lapse. A request verb is not required."""
    if "deactivat" in text or re.search(r"\bsuspend", text) or re.search(r"\blapse", text):
        return True
    return any(phrase in text for phrase in ("payment failed", "payment failure", "failed payment"))


def _request_and_deadline(text: str) -> bool:
    """Both a request and a deadline. Either one alone is not an action."""
    if not re.search(r"\b(reply|pay|renew|update|confirm)\b", text):
        return False
    return _stated_deadline(text) != ""


def _financial_obligation_email(text: str) -> bool:
    return any(marker in text for marker in ("amount due", "payment due", "past due", "pay by", "balance due"))


def _financial_information_email(text: str) -> bool:
    return any(
        marker in text
        for marker in ("statement", "e-statement", "estatement", "bank statement", "monthly statement")
    )


def _important_document_email(text: str) -> bool:
    if any(
        marker in text
        for marker in (
            "insurance document",
            "policy document",
            "documents are",
            "your documents",
            "document notification",
            "documents notification",
            "documents are ready",
        )
    ):
        return True
    return "document" in text


def _account_notification_email(text: str) -> bool:
    if "credit" in text:
        return True
    return any(marker in text for marker in ("account notification", "account update", "password", "profile"))


def _verify_sentence(action: dict[str, Any]) -> str:
    """Recommend verify or pay. Do not say the harm has already happened."""
    name = _alert_name(action)
    text = _message_text(action)
    if "deactivat" in text or ("subscription" in text and _account_harm(text)):
        return (
            f"Verify {name} subscription status. "
            "Reason: the stored message is a subscription deactivation warning, "
            "and current status is unverified."
        )
    if re.search(r"\bsuspend", text):
        return (
            f"Verify {name}. Reason: the stored message mentions suspension, "
            "and current status is unverified."
        )
    if re.search(r"\blapse", text):
        return (
            f"Verify {name}. Reason: the stored message mentions a lapse, "
            "and current status is unverified."
        )
    if any(phrase in text for phrase in ("payment failed", "payment failure", "failed payment")):
        return (
            f"Pay {name}. Reason: the stored message mentions a failed payment, "
            "and current status is unverified."
        )
    when = _stated_deadline(text) or "the stated date"
    if re.search(r"\bpay\b", text):
        return f"Pay {name} by {when}. Reason: the message asks for payment by that date."
    verb = "respond"
    match = re.search(r"\b(reply|renew|update|confirm)\b", text)
    if match:
        verb = match.group(1)
    return (
        f"Verify {name}. Reason: the message asks to {verb} by {when}, "
        "and current status is unverified."
    )


def _bill_focus_sentence(action: dict[str, Any], today: date) -> str:
    name = _bill_name(action)
    due = _due_date(action)
    if due is not None and due > today:
        return f"Review the upcoming {name} bill."
    if due is not None:
        return f"Review the {name} bill due {_spoken(due)}. Payment status unverified."
    return f"Review the {name} bill. Payment status unverified."


def _bill_recommendation(action: dict[str, Any], today: date) -> str:
    name = _bill_name(action)
    due = _due_date(action)
    if due is not None and due > today:
        return f"Review {name} bill before {_spoken(due)}."
    if due is not None:
        return f"Review the {name} bill due {_spoken(due)}. Payment status unverified."
    return f"Review {name}. Payment status unverified."


def _loop_line(loop: dict[str, Any]) -> str:
    title = str(loop.get("title") or "Follow up").strip()
    due = str(loop.get("due_at") or "").strip()
    if due:
        stamp = due[:10] if _parse_day(due[:10]) else due
        return f"{title}, due {stamp}."
    return f"{title}."


def _morning_requests(focus_lines: list[str]) -> list[str]:
    kept: list[str] = []
    for raw in focus_lines:
        text = str(raw).strip()
        if not text or text.startswith("No kept role yet"):
            continue
        if text.startswith("Pay or close"):
            continue
        if text.startswith("Suggestion, not a commitment:"):
            continue
        kept.append(text if text.endswith(".") else f"{text}.")
    return kept


def _focus_prose(
    focus_lines: list[str],
    alerts: list[dict[str, Any]],
    bills: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    explicit: list[dict[str, Any]],
    items: list[dict[str, Any]],
    counts: dict[str, int],
    today: date,
    pause_research: bool,
) -> str:
    alerts_sorted = sorted(
        alerts,
        key=lambda row: (
            -int(row.get("priority") or 0),
            0 if "deactivat" in _email_text(row) else 1,
            str(row.get("title") or ""),
        ),
    )
    bills_sorted = sorted(bills, key=lambda row: (_due_date(row) or date.max, _bill_name(row)))
    sentences = _morning_requests(focus_lines)
    if alerts_sorted:
        sentences.append(f"Most important: {_verify_sentence(alerts_sorted[0])}")
    if bills_sorted:
        upcoming = next((bill for bill in bills_sorted if (_due_date(bill) or date.min) > today), bills_sorted[0])
        sentences.append(f"Upcoming financial obligations: {_bill_focus_sentence(upcoming, today)}")
    else:
        sentences.append("Upcoming financial obligations: None.")
    sentences.append(_approval_summary(approvals, today))
    if counts["open_commitments"]:
        sentences.append(f"Outstanding commitments: {counts['open_commitments']}.")
    else:
        sentences.append("Outstanding commitments: None.")
    has_suggestion = any(str(line).startswith("Suggestion, not a commitment:") for line in focus_lines)
    qualified = not pause_research and not any(_is_high_engagement(item) for item in items) and not has_suggestion
    actionable = bool(alerts or bills or counts["open_commitments"] or has_suggestion or explicit or approvals)
    if not actionable:
        sentences.append(_NO_ACTION)
    elif qualified and (alerts or bills or items or explicit):
        sentences.append(_QUALIFIED)
    counts_line = (
        f"Priority alerts: {counts['priority_alerts']}. "
        f"Pending bills: {counts['pending_bills']}. "
        f"Pending approvals: {counts['pending_approvals']}. "
        f"Outstanding commitments: {counts['open_commitments']}."
    )
    prose = "\n".join(sentences).strip()
    if "No action is justified" in prose and (alerts or bills):
        prose = "\n".join(line for line in sentences if not line.startswith("No action is justified")).strip()
    return "\n".join(part for part in (prose, counts_line) if part)


def _approval_summary(approvals: list[dict[str, Any]], today: date) -> str:
    """Compact view of waiting rows. Nothing here is approved or deleted."""
    if not approvals:
        return "Pending approvals: 0."
    counts: dict[str, int] = {}
    oldest: date | None = None
    stale = 0
    for row in approvals:
        kind = str(row.get("action_type") or "other")
        counts[kind] = counts.get(kind, 0) + 1
        created = _parse_day(str(row.get("created_at") or "")[:10])
        if created is not None and (oldest is None or created < oldest):
            oldest = created
        if created is not None and (today - created).days >= 14:
            stale += 1
    breakdown = ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
    oldest_bit = f" Oldest pending {_spoken(oldest)}." if oldest is not None else ""
    titles = [str(row.get("title") or "Item").strip() or "Item" for row in approvals[:5]]
    extra = len(approvals) - len(titles)
    waiting = "; ".join(titles)
    if extra:
        waiting = f"{waiting}; and {extra} more"
    return (
        f"Pending approvals: {len(approvals)}. {breakdown}.{oldest_bit} "
        f"Awaiting the owner: {waiting}. Stale and may need review: {stale}."
    )


def _attention_lines(
    alerts: list[dict[str, Any]],
    bills: list[dict[str, Any]],
    other_mail: list[dict[str, Any]],
    today: date,
) -> str:
    lines = [_alert_attention(alert) for alert in sorted(alerts, key=lambda row: -int(row.get("priority") or 0))]
    lines.extend(_bill_attention(bill, today) for bill in bills)
    lines.extend(_mail_notice_line(row) for row in other_mail)
    return "\n".join(lines)


def _alert_attention(action: dict[str, Any]) -> str:
    from executive_summary import mail_origin

    origin = mail_origin(action)
    name = _alert_name(action)
    subject = origin.get("subject") or ""
    if subject and subject.lower() != name.lower():
        bits = [f"{name}: {subject}."]
    else:
        bits = [f"{name}."]
    sent = origin.get("sent") or ""
    if sent:
        shown = _spoken_from_text(sent) or sent
        bits.append(f"Original email received {shown}.")
    sender = origin.get("sender") or ""
    if sender:
        bits.append(f"From {sender}.")
    if subject and subject.lower() == name.lower():
        pass
    elif not subject and action.get("title") and str(action.get("title")).lower() != name.lower():
        bits.insert(1, f"Subject: {action.get('title')}.")
    if verification_justified(action):
        bits.append(_action_facts(action))
        bits.append("Current status unverified, requiring verification.")
    else:
        bits.append(f"Class {classify_email(action)}. No response is requested.")
    return " ".join(bits)


def _action_facts(action: dict[str, Any]) -> str:
    """State the request the message actually makes. Do not invent a deadline."""
    text = _email_text(action)
    if "deactivat" in text or ("subscription" in text and "cancel" in text):
        asked = "verify subscription status"
        why = "the stored message is a subscription deactivation warning"
        consequence = "deactivation is the stated risk"
    elif "payment fail" in text:
        asked = "review the failed payment"
        why = "the stored message reports a payment failure"
        consequence = "payment failure is the stated risk"
    elif any(marker in text for marker in ("please respond", "must respond", "response required", "action required")):
        asked = "respond to the request"
        why = "the stored message asks for a response"
        consequence = "a required response is stated"
    elif "failed" in text:
        asked = "review the reported failure"
        why = "the stored message reports a failure"
        consequence = ""
    else:
        asked = "review the stated request"
        why = "the stored message states an explicit request"
        consequence = ""
    deadline = _stated_deadline(text)
    parts = [f"Action: {asked}.", f"Why: {why}."]
    if deadline:
        parts.append(f"Deadline: {deadline}.")
    if consequence:
        parts.append(f"Consequence: {consequence}.")
    parts.append("Status: unverified.")
    return " ".join(parts)


def _stated_deadline(text: str) -> str:
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if match:
        day = _parse_day(match.group(1))
        if day is not None:
            return _spoken(day)
    match = re.search(r"\b(?:by|before)\s+([a-z]+ \d{1,2}(?:, \d{4})?)\b", text)
    if match:
        return match.group(1)
    match = re.search(
        r"\b(?:by|before)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\b",
        text,
    )
    if match:
        return match.group(1)
    return ""


def _mail_notice_line(action: dict[str, Any]) -> str:
    """Keep a non-action message visible without turning it into an alert."""
    from executive_summary import mail_origin

    origin = mail_origin(action)
    name = _alert_name(action)
    subject = origin.get("subject") or str(action.get("title") or "Message")
    kind = classify_email(action)
    bits = [f"{name}: {subject}. Class {kind}."]
    sent = origin.get("sent") or ""
    if sent:
        bits.append(f"Original email received {_spoken_from_text(sent) or sent}.")
    sender = origin.get("sender") or ""
    if sender:
        bits.append(f"From {sender}.")
    bits.append("No action is requested.")
    return " ".join(bits)


def _bill_attention(action: dict[str, Any], today: date) -> str:
    payload = _stored_payload(action)
    name = _bill_name(action)
    money = _money(payload.get("amount"), payload.get("currency"))
    due = _due_date(action)
    spoken = _spoken(due) if due else ""
    if money and spoken:
        line = f"{name}: {money} due {spoken}."
    elif spoken:
        line = f"{name}: due {spoken}."
    elif money:
        line = f"{name}: {money}."
    else:
        line = f"{name}."
    extra: list[str] = []
    if due is not None and due <= today and action.get("action_type") == "overdue_payment":
        extra.append("Stored as overdue.")
    sent = str(payload.get("sent_at") or payload.get("date") or "").strip()
    if sent:
        extra.append(f"Original email received {_spoken_from_text(sent) or sent}.")
    sender = str(payload.get("from") or payload.get("sender") or "").strip()
    if sender:
        extra.append(f"From {sender}.")
    subject = str(payload.get("subject") or "").strip()
    if subject and subject.lower() not in line.lower():
        extra.append(f"Subject: {subject}.")
    extra.append("Payment status unverified.")
    return " ".join([line, *extra])


def _research_body(
    items: list[dict[str, Any]],
    explicit: list[dict[str, Any]],
    paused: bool,
    prospect_note: str,
    research_note: str,
    market: list[dict[str, Any]],
) -> str:
    if paused:
        return "Research is waiting until the open role has a date."
    explicit_titles = {normalize_name(str(loop.get("title") or "")) for loop in explicit}
    visible = []
    for item in items:
        title = normalize_name(str(item.get("title") or ""))
        if title and title in explicit_titles and item.get("record_kind") == "loop":
            continue
        visible.append(item)
    visible.sort(key=lambda item: (-_research_rank(item), str(item.get("title") or "")))
    if not visible and not prospect_note and not research_note:
        return ""
    market_ids = {id(item) for item in market}
    lines: list[str] = []
    if len(market) >= 2:
        lines.append("Fractional CTO market: Multiple search results, consolidated into one research topic.")
    elif len(market) == 1:
        title = market[0].get("title") or "Search result"
        lines.append(f"Fractional CTO market: {title}. Kept as research, not an outstanding action.")
    seen: set[str] = set()
    for item in visible:
        if id(item) in market_ids:
            continue
        title = str(item.get("title") or item.get("company") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        if _is_high_engagement(item):
            lines.append(f"{title}. Link not verified. Not a confirmed engagement.")
        else:
            lines.append(f"- {title}")
    if prospect_note:
        lines.append(prospect_note)
    if research_note:
        lines.append(research_note)
    if visible:
        lines.append(_UNCONFIRMED)
    return "\n".join(lines)


def _market_items(items: list[dict[str, Any]], explicit: list[dict[str, Any]]) -> list[dict[str, Any]]:
    explicit_titles = {normalize_name(str(loop.get("title") or "")) for loop in explicit}
    chosen = []
    for item in items:
        title = normalize_name(str(item.get("title") or ""))
        if title and title in explicit_titles and item.get("record_kind") == "loop":
            continue
        if _is_market_item(item):
            chosen.append(item)
    return chosen


def rank_research_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order by the profile. The stored class is not changed."""
    ranked = [dict(item) for item in items]
    ranked.sort(key=lambda item: (-_research_rank(item), str(item.get("title") or "")))
    return ranked


def _profile_blob() -> str:
    path = Path(__file__).resolve().parent / "config" / "principal.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    goals = data.get("goals") or []
    parts = [str(data.get("icp") or "")]
    if isinstance(goals, list):
        parts.extend(str(goal) for goal in goals)
    return " ".join(parts).lower()


def _research_rank(item: dict[str, Any]) -> int:
    """Fit only. A generic job stays behind fractional CTO and seed-to-series-B advisory."""
    text = _blob(item)
    profile = _profile_blob()
    score = 0
    profile_wants_cto = "fractional" in profile or "cto" in profile
    profile_wants_stage = "seed" in profile or "series b" in profile
    if profile_wants_cto and "fractional" in text and "cto" in text:
        score += 3
    if profile_wants_stage and "advisory" in text and any(
        token in text for token in ("seed", "series a", "series b")
    ):
        score += 2
    if score == 0 and _is_job_listing(item):
        score -= 1
    return score


def _is_high_engagement(item: dict[str, Any]) -> bool:
    return bool(
        item.get("classification") == "engagement"
        and not item.get("generic")
        and item.get("band") in {"high", "medium"}
        and not _is_research_url(str(item.get("url") or ""))
    )


def _is_market_item(item: dict[str, Any]) -> bool:
    if _is_high_engagement(item):
        return False
    url = str(item.get("url") or "")
    text = f"{_blob(item)} {url}".lower()
    if _is_research_url(url) or "youtube" in text or "marketplace" in text:
        return True
    if item.get("generic") or item.get("classification") in {"research", "competitor"}:
        if any(token in text for token in ("fractional", "cto", "youtube", "marketplace", "job")):
            return True
    return False


def _is_research_url(url: str) -> bool:
    lowered = (url or "").lower()
    if not lowered:
        return False
    if any(host in lowered for host in _BOARD_HOSTS):
        return True
    if any(host in lowered for host in ("youtube.com", "youtu.be", "indeed.com", "linkedin.com/jobs", "upwork.com")):
        return True
    if "marketplace" in lowered or "/search" in lowered:
        return True
    return False


def _is_research_text(text: str) -> bool:
    lowered = (text or "").lower()
    if any(token in lowered for token in ("youtube", "marketplace", "saved search")):
        return True
    if "now hiring" in lowered and "job" in lowered:
        return True
    if re.search(r"\b\d+\+?\s+\w+\s+jobs\b", lowered):
        return True
    if "jobs" in lowered and any(token in lowered for token in ("fractional", "cto", "indeed", "linkedin")):
        return True
    return False


def _commitments_body(db_path: str | Path, today: date) -> str:
    try:
        from desk_work import list_commitments

        rows = list_commitments(db_path, ("open", "blocked"))
    except Exception:
        rows = []
    if not rows:
        return "None."
    return format_open_commitments(rows, today)


def _recommended_lines(
    db_path: str | Path,
    alerts: list[dict[str, Any]],
    bills: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    explicit: list[dict[str, Any]],
    suggestions: list[str],
    market: list[dict[str, Any]],
    items: list[dict[str, Any]],
    today: date,
) -> list[str]:
    ranked: list[tuple[int, str, dict[str, Any] | None]] = []
    for alert in alerts:
        if not verification_justified(alert) or _alert_already_recommended(db_path, alert):
            continue
        score = 300 if int(alert.get("priority") or 0) >= 3 else 200 if int(alert.get("priority") or 0) >= 2 else 160
        ranked.append((score, _verify_sentence(alert), alert))
    for bill in bills:
        due = _due_date(bill)
        if due is None:
            continue
        if due <= today:
            score = 180
        elif (due - today).days <= 14:
            score = 150
        else:
            score = 100
        ranked.append((score, _bill_recommendation(bill, today), None))
    for loop in explicit:
        due = _parse_day(str(loop.get("due_at") or "")[:10])
        if due is None and not _ACTION_START.match(str(loop.get("title") or "").strip()):
            continue
        score = 140 if due is not None and due <= today else 40
        ranked.append((score, _loop_line(loop), None))
    for line in suggestions:
        ranked.append((60, line if line.endswith(".") else f"{line}.", None))
    concrete = any(_is_high_engagement(item) for item in items) or bool(suggestions)
    if market and not concrete:
        ranked.append((10, _CONTINUE_RESEARCH, None))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[str] = []
    seen: set[str] = set()
    included: list[dict[str, Any]] = []
    for _score, line, alert in ranked:
        if line in seen:
            continue
        seen.add(line)
        chosen.append(line)
        if alert is not None:
            included.append(alert)
        if len(chosen) == 3:
            break
    for alert in included:
        try:
            remember_suggestion(db_path, _alert_key(alert), _alert_evidence(alert))
        except Exception:
            continue
    if not chosen:
        return [
            "No recommendation is justified because no explicit action, financial deadline, "
            "or cancellation risk is stored."
        ]
    return chosen


def desk_recommendations(db_path: str | Path, today: date | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Items the owner can open, review, dismiss, or approve. Empty when none qualify."""
    try:
        items = _load_scored(db_path, today)
    except Exception:
        return []
    chosen = []
    for item in sorted(items, key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or ""))):
        if not _actionable(item):
            continue
        if _is_closed(db_path, item):
            continue
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen


def approve_brief_commitment(
    db_path: str | Path,
    item_key: str,
    title: str,
    due_on: str = "",
) -> dict[str, Any]:
    """Save a commitment only when the owner approves. Discovery does not call this."""
    key = (item_key or "").strip()
    text = (title or "").strip()
    if not key or not text:
        return {"status": "error", "message": "A recommendation needs a name before it can be tracked."}
    from desk_work import add_commitment

    result = add_commitment(db_path, text, due_on, decision_id=key)
    if result.get("status") != "ok":
        return result
    _set_brief_status(db_path, key, text, "acknowledged", {"item_key": key, "title": text})
    return result


def mark_brief_reviewed(db_path: str | Path, item_key: str, title: str, url: str = "") -> dict[str, Any]:
    """Record a review on pending_actions. Does not create a commitment."""
    key = (item_key or "").strip()
    if not key:
        return {"status": "error", "message": "That item is missing."}
    _set_brief_status(
        db_path,
        key,
        title or "Brief item",
        "acknowledged",
        {"item_key": key, "title": title, "url": url, "link_verified": False},
    )
    return {"status": "ok", "message": "Marked reviewed."}


def dismiss_brief_item(db_path: str | Path, item_key: str, title: str, url: str = "") -> dict[str, Any]:
    """Hide an item from the next recommendation list. The source rows stay."""
    key = (item_key or "").strip()
    if not key:
        return {"status": "error", "message": "That item is missing."}
    _set_brief_status(
        db_path,
        key,
        title or "Brief item",
        "rejected",
        {"item_key": key, "title": title, "url": url, "link_verified": False},
    )
    return {"status": "ok", "message": "Dismissed."}


def _from_role(row: dict[str, Any], skill: str, found: str) -> dict[str, Any]:
    title = str(row.get("title") or "").strip()
    url = str(row.get("url") or "").strip()
    company = str(row.get("company") or row.get("company_name") or "").strip()
    if not company:
        company = _company_from_title(title)
    return _base_item(
        title=title or company,
        url=url,
        snippet=str(row.get("snippet") or row.get("content") or ""),
        company=company,
        skill=skill,
        found=found,
        record_kind="role",
        location=str(row.get("location") or ""),
        work_mode=str(row.get("work_mode") or ""),
        industry=str(row.get("industry") or ""),
        funding_stage=str(row.get("funding_stage") or ""),
        rationale=str(row.get("rationale") or row.get("why") or ""),
        name_unverified=False,
    )


def _from_company(row: dict[str, Any], skill: str, found: str, model_name: bool) -> dict[str, Any]:
    company = str(row.get("company_name") or row.get("name") or "").strip()
    url = str(row.get("website") or row.get("url") or "").strip()
    return _base_item(
        title=company,
        url=url,
        snippet=str(row.get("snippet") or row.get("why") or row.get("rationale") or ""),
        company=company,
        skill=skill,
        found=found,
        record_kind="company",
        location="",
        work_mode="",
        industry=str(row.get("industry") or ""),
        funding_stage=str(row.get("funding_stage") or ""),
        rationale=str(row.get("why") or row.get("rationale") or ""),
        name_unverified=model_name,
    )


def _from_loop(loop: dict[str, Any]) -> dict[str, Any]:
    from open_loops import loop_url

    title = str(loop.get("title") or "").strip()
    url = loop_url(loop)
    company = _company_from_title(title)
    return _base_item(
        title=title,
        url=url,
        snippet=str(loop.get("detail") or ""),
        company=company,
        skill=str(loop.get("source") or "open_loop"),
        found=str(loop.get("created_at") or ""),
        record_kind="loop",
        location="",
        work_mode="",
        industry="",
        funding_stage="",
        rationale="",
        name_unverified=False,
    )


def _base_item(
    title: str,
    url: str,
    snippet: str,
    company: str,
    skill: str,
    found: str,
    record_kind: str,
    location: str,
    work_mode: str,
    industry: str,
    funding_stage: str,
    rationale: str,
    name_unverified: bool,
) -> dict[str, Any]:
    stamp = _stamp(found, skill)
    return {
        "title": title.strip(),
        "url": url.strip(),
        "url_key": normalize_url(url),
        "snippet": " ".join(snippet.split()),
        "company": company.strip(),
        "company_key": company_key(company),
        "title_key": title_key(title),
        "sources": [skill] if skill else [],
        "discovered": [stamp] if stamp else [],
        "record_kind": record_kind,
        "location": location,
        "work_mode": work_mode,
        "industry": industry,
        "funding_stage": funding_stage,
        "rationale": rationale.strip(),
        "name_unverified": name_unverified,
        "link_verified": False,
        "raw_count": 1,
    }


def _merge_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(group[0])
    urls: list[str] = []
    sources: list[str] = []
    discovered: list[str] = []
    snippets: list[str] = []
    companies: list[str] = []
    rationales: list[str] = []
    for item in group:
        if item.get("url") and item["url"] not in urls:
            urls.append(item["url"])
        for source in item.get("sources") or []:
            if source and source not in sources:
                sources.append(source)
        for stamp in item.get("discovered") or []:
            if stamp and stamp not in discovered:
                discovered.append(stamp)
        if item.get("snippet"):
            snippets.append(item["snippet"])
        if item.get("company"):
            companies.append(item["company"])
        if item.get("rationale"):
            rationales.append(item["rationale"])
        if item.get("industry") and not merged.get("industry"):
            merged["industry"] = item["industry"]
        if item.get("funding_stage") and not merged.get("funding_stage"):
            merged["funding_stage"] = item["funding_stage"]
        if item.get("name_unverified"):
            merged["name_unverified"] = True
        if item.get("record_kind") == "role":
            merged["record_kind"] = "role"
    if companies:
        merged["company"] = max(companies, key=len)
        merged["company_key"] = company_key(merged["company"])
    merged["url"] = urls[0] if urls else ""
    merged["url_key"] = normalize_url(merged["url"])
    merged["snippet"] = max(snippets, key=len) if snippets else ""
    merged["sources"] = sources
    merged["discovered"] = discovered
    merged["rationale"] = max(rationales, key=len) if rationales else ""
    merged["raw_count"] = len(group)
    merged["link_verified"] = False
    if not merged.get("title"):
        merged["title"] = merged.get("company") or "Untitled"
    merged["title_key"] = title_key(str(merged.get("title") or ""))
    return merged


def _item_key(item: dict[str, Any]) -> str:
    if item.get("company_key"):
        return "company:" + str(item["company_key"])
    if item.get("url_key"):
        return "url:" + str(item["url_key"])
    if item.get("title_key"):
        return "title:" + str(item["title_key"])
    return "title:" + normalize_name(str(item.get("title") or "item"))[:80]


def _blob(item: dict[str, Any]) -> str:
    parts = [
        item.get("title") or "",
        item.get("snippet") or "",
        item.get("company") or "",
        item.get("location") or "",
        item.get("work_mode") or "",
        item.get("industry") or "",
        item.get("funding_stage") or "",
        item.get("rationale") or "",
    ]
    return " ".join(str(part) for part in parts).lower()


def _thin(item: dict[str, Any]) -> bool:
    return len(str(item.get("snippet") or "").strip()) < 40


def _generic_noise(item: dict[str, Any]) -> bool:
    url = str(item.get("url") or "").lower()
    title = str(item.get("title") or "").lower()
    if "linkedin.com" in url and " at " in title and "jobs in" not in title:
        return False
    if any(host in url for host in _BOARD_HOSTS):
        return True
    if "linkedin.com" in url and "jobs" in title:
        return True
    if any(phrase in title for phrase in _DIRECTORY_TITLES):
        return True
    if re.search(r"\b\d+\+?\s+\w+", title):
        return True
    if "now hiring" in title and "jobs" in title:
        return True
    return False


def _article(item: dict[str, Any]) -> bool:
    text = _blob(item)
    return any(phrase in text for phrase in ("what is a ", "podcast", "blog post", "white paper", "youtube"))


def _is_job_listing(item: dict[str, Any]) -> bool:
    url = str(item.get("url") or "").lower()
    text = _blob(item)
    if any(host in url for host in _JOB_HOSTS):
        return True
    if any(piece in url for piece in ("/jobs", "/job/", "/careers", "/roles/")):
        return True
    if _FULL_TIME.search(text) and not _NOT_FULL_TIME.search(text):
        return True
    if any(phrase in text for phrase in ("now hiring", "job description", "apply now", "job posting")):
        return True
    return False


def _service_page(item: dict[str, Any]) -> bool:
    if _is_job_listing(item):
        return False
    text = _blob(item)
    title = str(item.get("title") or "").lower()
    if any(phrase in text for phrase in _SERVICE):
        return True
    if "services" in title and any(word in title for word in ("cto", "consulting", "advisory", "warehouse")):
        return True
    if re.search(r"fractional cto in\b", title) and " at " not in title and "hiring" not in title:
        return True
    return False


def _partner_page(item: dict[str, Any]) -> bool:
    text = _blob(item)
    return any(phrase in text for phrase in _PARTNER)


def _engagement_language(text: str) -> bool:
    return any(word in text for word in _ENGAGEMENT_WORDS)


def _stated_need(text: str) -> bool:
    return any(word in text for word in _NEED)


def _experience_points(text: str) -> int:
    points = 0
    if any(word in text for word in _EXPERIENCE):
        points += 12
    if any(word in text for word in _ADVISORY):
        points += 10
    if any(word in text for word in _MARKET):
        points += 8
    if points == 0 and "software" in text:
        points = 6
    return min(points, WEIGHTS["experience_alignment"])


def _commercial_points(text: str) -> int:
    if _FULL_TIME.search(text) and not _NOT_FULL_TIME.search(text):
        return 6
    points = 0
    if any(word in text for word in ("fractional", "advisory", "advisor", "consulting", "consultant", "retainer")):
        points += 18
    if any(word in text for word in ("b2b", "enterprise", "saas")):
        points += 7
    if points == 0:
        points = 8
    return min(points, WEIGHTS["commercial_advisory_fit"])


def _engagement_points(text: str) -> int:
    if _FULL_TIME.search(text) and not _NOT_FULL_TIME.search(text):
        return 4
    if "on-site only" in text or "onsite only" in text:
        return 2
    points = 0
    if any(word in text for word in ("fractional", "part-time", "part time", "interim", "consulting", "advisory", "retainer")):
        points += 14
    if "remote" in text or "hybrid" in text:
        points += 6
    return min(points, WEIGHTS["engagement_compatibility"])


def _evidence_points(item: dict[str, Any]) -> int:
    points = 0
    snippet = str(item.get("snippet") or "")
    if item.get("url"):
        points += 6
    if len(snippet) >= 80:
        points += 5
    elif len(snippet) >= 40:
        points += 3
    if item.get("company") and not item.get("name_unverified"):
        points += 2
    if item.get("discovered"):
        points += 2
    if not item.get("link_verified"):
        points = min(points, 12)
    if item.get("name_unverified") and len(snippet) < 40:
        points = min(points, 4)
    return min(points, WEIGHTS["evidence_credibility"])


def _geo_points(text: str) -> int:
    points = 0
    if any(word in text for word in ("united states", "u.s.", "usa", "jacksonville", "florida")):
        points += 7
    elif "remote" in text:
        points += 5
    else:
        points += 3
    if any(word in text for word in ("b2b", "saas", "enterprise")):
        points += 3
    return min(points, WEIGHTS["geographic_market_fit"])


def _confidence(item: dict[str, Any]) -> int:
    snippet = str(item.get("snippet") or "")
    confidence = 30
    if len(snippet) >= 80:
        confidence += 20
    elif snippet:
        confidence += 8
    else:
        confidence -= 12
    if item.get("url"):
        confidence += 12
    else:
        confidence -= 8
    if item.get("company") and not item.get("name_unverified"):
        confidence += 10
    if item.get("name_unverified"):
        confidence -= 15
    if len(item.get("sources") or []) > 1:
        confidence += 8
    if item.get("classification") == "unknown":
        confidence -= 10
    if not item.get("link_verified"):
        confidence = min(confidence, 70)
    return max(5, min(confidence, 70))


def _why(item: dict[str, Any], factors: dict[str, int]) -> str:
    parts: list[str] = []
    if factors["experience_alignment"] >= 20:
        parts.append("Stored text overlaps enterprise technology, WMS, or advisory work.")
    elif factors["experience_alignment"] >= 10:
        parts.append("Some stored text overlaps the advisory profile.")
    else:
        parts.append("Little stored overlap with technology leadership advisory.")
    if factors["commercial_advisory_fit"] >= 18:
        parts.append("The commercial shape looks like advisory or consulting.")
    elif factors["commercial_advisory_fit"] <= 6:
        parts.append("The commercial shape looks like a full-time operating role.")
    if factors["engagement_compatibility"] <= 5:
        parts.append("Engagement fit is low because the text asks for full-time or daily work.")
    elif factors["engagement_compatibility"] >= 14:
        parts.append("Engagement fit comes from fractional, advisory, or remote wording.")
    if item.get("icp_only"):
        parts.append("ICP match only. Not a qualified lead.")
    elif item.get("classification") == "prospect" and _stated_need(_blob(item)):
        parts.append("A stored need makes this a plausible prospect, still not a qualified lead.")
    rationale = str(item.get("rationale") or "").strip()
    if rationale:
        parts.append(f"Assessment: {rationale}")
    return " ".join(parts)


def _concerns(item: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if item.get("url"):
        notes.append("Link not verified.")
    else:
        notes.append("No link stored.")
    if item.get("job_listing"):
        notes.append("Job listing, not a consulting service page.")
    if item.get("name_unverified"):
        notes.append("Company name is an assessment, not verified as a business.")
    if int(item.get("confidence") or 0) < 45:
        notes.append("Evidence is thin.")
    if int(item.get("factors", {}).get("engagement_compatibility") or 0) <= 5 and item.get("classification") == "engagement":
        notes.append("Full-time or daily availability. Weak engagement fit. Uncertain fit is flagged, not rejected.")
    if item.get("icp_only"):
        notes.append("ICP match only. Not a qualified lead.")
    if item.get("classification") == "unknown":
        notes.append("Uncertain fit. Not rejected.")
    if item.get("classification") in {"engagement", "prospect"}:
        notes.append("No contact is stored.")
        if item.get("classification") == "prospect" and not item.get("funding_stage"):
            notes.append("Funding, revenue, and hiring are not in the stored evidence.")
    return notes


def _next_action(item: dict[str, Any]) -> str:
    if item.get("generic") or item.get("classification") in {"research", "unknown", "competitor"}:
        return "No action is justified."
    if item.get("band") == "low" or int(item.get("confidence") or 0) < 45:
        return "No action is justified."
    if item.get("icp_only"):
        return "No action is justified until there is a stated need."
    if item.get("classification") == "engagement":
        return "Open the source and decide whether to track a follow-up."
    if item.get("classification") == "prospect":
        return "Keep it as a hypothesis until there is a stated need."
    if item.get("classification") == "partner":
        return "Note the channel. It is not a customer."
    return "No action is justified."


def _format_engagements(items: list[dict[str, Any]]) -> str:
    chosen = [
        item
        for item in items
        if item.get("classification") == "engagement" and not item.get("generic") and item.get("band") in {"high", "medium"}
    ]
    chosen.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("title") or "")))
    if not chosen:
        return "_No engagement is strong enough for this list._"
    return "\n\n".join(render_item(item) for item in chosen[:5])


def _format_prospects(items: list[dict[str, Any]], note: str) -> str:
    chosen = [item for item in items if item.get("classification") == "prospect" and not item.get("generic")]
    chosen.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("title") or "")))
    lines = ["An ICP hit alone is not a qualified lead."]
    if note:
        lines.append(note)
    if not chosen:
        lines.append("_No strategic prospects in this window._")
        return "\n".join(lines)
    lines.extend(render_item(item) for item in chosen[:5])
    return "\n\n".join(lines)


def _format_partners(items: list[dict[str, Any]]) -> str:
    chosen = [item for item in items if item.get("classification") == "partner" and not item.get("generic")]
    if not chosen:
        return "_No partner channels in this window._"
    blocks = []
    for item in chosen[:5]:
        blocks.append(render_item(item) + "\nChannel, not a customer.")
    return "\n\n".join(blocks)


def _format_watchlist(items: list[dict[str, Any]]) -> str:
    noise = [item for item in items if item.get("generic")]
    shown = []
    for item in items:
        if item.get("generic"):
            continue
        kind = item.get("classification")
        low_engagement = kind == "engagement" and item.get("band") == "low"
        if kind in {"research", "unknown", "competitor"} or low_engagement:
            shown.append(item)
    lines: list[str] = []
    if noise:
        count = len(noise)
        noun = "item was" if count == 1 else "items were"
        lines.append(
            f"_{count} generic job {noun} left off this brief (job boards, videos, or broad searches)._"
            if count == 1
            else f"_{count} generic job pages, videos, or broad searches were left off this brief._"
        )
    if not shown:
        lines.append("_Nothing else on the watchlist._")
        return "\n".join(lines)
    lines.extend(render_item(item) for item in shown[:8])
    return "\n\n".join(lines)


def _actionable(item: dict[str, Any]) -> bool:
    action = str(item.get("next_action") or "")
    if item.get("classification") not in {"engagement", "prospect"}:
        return False
    if action.startswith("No action"):
        return False
    return True


def _best_unfollowed(db_path: str | Path, items: list[dict[str, Any]], high_only: bool) -> dict[str, Any] | None:
    ranked = sorted(items, key=lambda row: (-int(row.get("score") or 0), str(row.get("title") or "")))
    for item in ranked:
        if item.get("classification") not in {"engagement", "prospect"}:
            continue
        if item.get("generic") or item.get("icp_only"):
            continue
        if high_only and item.get("band") != "high":
            continue
        if not high_only and not _actionable(item):
            continue
        if _is_closed(db_path, item):
            continue
        return item
    return None


def _is_closed(db_path: str | Path, item: dict[str, Any]) -> bool:
    key = str(item.get("item_key") or "")
    if not key:
        return False
    if key in _handled_commitment_keys(db_path):
        return True
    if key in _closed_brief_keys(db_path):
        return True
    url_key = item.get("url_key") or ""
    if url_key and url_key in _pursuit_url_keys(db_path):
        return True
    return False


def _handled_commitment_keys(db_path: str | Path) -> set[str]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return set()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'commitments'"
        ).fetchone()
        if not exists:
            return set()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(commitments)")}
        if "decision_id" not in columns:
            return set()
        rows = conn.execute(
            "SELECT decision_id FROM commitments WHERE decision_id != ''"
        ).fetchall()
    except sqlite3.Error:
        return set()
    finally:
        conn.close()
    return {str(row[0]) for row in rows if row[0]}


def _closed_brief_keys(db_path: str | Path) -> set[str]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return set()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pending_actions'"
        ).fetchone()
        if not exists:
            return set()
        rows = conn.execute(
            """
            SELECT source_key FROM pending_actions
            WHERE source_key LIKE 'brief:%' AND status IN ('acknowledged', 'rejected')
            """
        ).fetchall()
    except sqlite3.Error:
        return set()
    finally:
        conn.close()
    keys = set()
    for row in rows:
        source = str(row[0] or "")
        if source.startswith("brief:"):
            keys.add(source[len("brief:") :])
    return keys


def _pursuit_url_keys(db_path: str | Path) -> set[str]:
    try:
        from desk_work import list_pursuits

        rows = list_pursuits(db_path)
    except Exception:
        return set()
    return {normalize_url(str(row.get("url") or "")) for row in rows if row.get("url")}


def _load_scored(db_path: str | Path, today: date | None) -> list[dict[str, Any]]:
    since = _since_iso(db_path, today)
    runs = _read_runs(db_path, since)
    loops = _read_loops(db_path)
    return prepare_items(runs, loops)


def _since_iso(db_path: str | Path, today: date | None) -> str:
    moment = today or datetime.now().astimezone().date()
    start = datetime(moment.year, moment.month, moment.day, tzinfo=UTC) - timedelta(days=_lookback_days(db_path))
    return start.isoformat()


def _lookback_days(db_path: str | Path) -> int:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return 7
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'desk_settings'"
        ).fetchone()
        if not exists:
            return 7
        row = conn.execute(
            "SELECT value FROM desk_settings WHERE key = 'brief_lookback_days'"
        ).fetchone()
    except sqlite3.Error:
        return 7
    finally:
        conn.close()
    if not row or row[0] is None:
        return 7
    try:
        return max(1, min(30, int(row[0])))
    except (TypeError, ValueError):
        return 7


def _read_runs(db_path: str | Path, since_iso: str) -> list[dict[str, Any]]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return []
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'skill_runs'"
        ).fetchone()
        if not exists:
            return []
        rows = conn.execute(
            """
            SELECT skill_name, executed_at, result_json
            FROM skill_runs
            WHERE executed_at >= ?
            ORDER BY executed_at ASC
            """,
            (since_iso,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [
        {"skill_name": row[0], "executed_at": row[1], "result_json": row[2]}
        for row in rows
    ]


def _read_loops(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return []
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'open_loops'"
        ).fetchone()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if not exists:
        return []
    try:
        from open_loops import list_open_loops

        return list_open_loops(db_path=db_path, limit=50)
    except Exception:
        return []


def _seen_map(db_path: str | Path) -> dict[str, str]:
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return {}
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'desk_settings'"
        ).fetchone()
        if not exists:
            return {}
        row = conn.execute(
            "SELECT value FROM desk_settings WHERE key = ?",
            (_SEEN_KEY,),
        ).fetchone()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    if not row or not row[0]:
        return {}
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return {}
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, dict):
        return {}
    return {str(key): str(value) for key, value in items.items()}


def _write_seen(db_path: str | Path, items: dict[str, str]) -> None:
    from desk_settings import set_setting

    set_setting(db_path, _SEEN_KEY, json.dumps({"items": items}))


def _set_brief_status(
    db_path: str | Path,
    item_key: str,
    title: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    from priority_inbox import emit_priority_action

    source_key = f"brief:{item_key}"
    emit_priority_action(
        kind="brief_item",
        title=(title or "Brief item")[:180],
        description="Owner reviewed a briefing item.",
        payload=payload,
        priority=1,
        source_key=source_key,
        db_path=str(resolve_db_path(db_path)),
    )
    resolved = resolve_db_path(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                UPDATE pending_actions
                SET status = ?, reviewed_by = 'desk', reviewed_at = ?, payload_json = ?
                WHERE source_key = ?
                """,
                (status, now, json.dumps(payload), source_key),
            )
    finally:
        conn.close()


def _company_from_title(title: str) -> str:
    match = re.search(r"\bat\s+(.+)$", title, re.I)
    if match:
        tail = re.split(r"\s(?:\||–|—|-)\s", match.group(1), maxsplit=1)[0]
        if _usable_company(tail):
            return tail.strip()
    match = re.search(r"\s(?:\||–|—)\s+(.+)$", title)
    if match and _usable_company(match.group(1)):
        return match.group(1).strip()
    return ""


def _usable_company(name: str) -> bool:
    text = " ".join((name or "").split())
    key = normalize_name(text)
    if not key or key in _GENERIC_COMPANIES or key in _BAD_COMPANY or len(key) < 3:
        return False
    if re.search(r"\b(jobs|hiring|apply|series|remote|indeed|linkedin)\b", text, re.I):
        return False
    return True


def _stamp(found: str, skill: str) -> str:
    text = (found or "").strip()
    day = text[:10] if len(text) >= 10 and text[4:5] == "-" else ""
    if day and skill:
        return f"{day} {skill}"
    if day:
        return day
    return skill


def _parse_day(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
