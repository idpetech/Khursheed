from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from manager import Manager
from notifications import Notifier


def generate_executive_summary(
    manager: Manager,
    notifier: Notifier,
    now: datetime | None = None,
) -> str:
    timestamp = now or datetime.now(timezone.utc)
    since = timestamp - timedelta(days=1)
    runs = manager.get_runs_since(since)

    db_path = str(getattr(manager, "_db_path", "khursheed.db"))
    tasks_section = _format_tasks(runs)
    pending_bills = _extract_pending_bills(runs)
    leads = _extract_top_leads(runs, limit=3)
    priority_alerts = _extract_priority_alerts(min_priority=2, db_path=db_path)
    cto_opportunities = _extract_cto_opportunities(runs, limit=5)
    icp_companies = _extract_icp_companies(runs, limit=5)
    open_loops = _extract_open_loops(db_path)
    priority_action = _highest_other_priority_action(db_path)
    linkedin_draft = _newest_linkedin_draft(db_path)
    recommendations = _build_recommendations(priority_action, open_loops, linkedin_draft)

    report = "\n".join(
        [
            f"# Executive Summary - {timestamp.date().isoformat()}",
            "",
            "## Priority Alerts",
            _format_priority_alerts(priority_alerts),
            "",
            "## Tasks Completed",
            tasks_section,
            "",
            "## Pending Bills",
            _format_pending_bills(pending_bills),
            "",
            "## Top Leads",
            _format_leads(leads),
            "",
            "## Fractional CTO Opportunities",
            _format_cto_opportunities(cto_opportunities),
            "",
            "## Top ICP Companies",
            _format_icp_companies(icp_companies),
            "",
            "## Open Loops",
            _format_open_loops(open_loops),
            "",
            "## Recommended Actions",
            _format_recommendations(recommendations),
            "",
        ]
    )
    notifier.send(report)
    return report


def _extract_priority_alerts(min_priority: int = 2, db_path: str = "khursheed.db") -> List[Dict[str, Any]]:
    """Read open priority actions straight from the pending_actions table.

    Degrades gracefully: if priority_inbox or the table is unavailable, returns [].
    """
    try:
        import priority_inbox

        return priority_inbox.list_open_priority_actions(min_priority=min_priority, db_path=db_path)
    except Exception:  # noqa: BLE001 - summary must never fail on a missing source
        return []


def _extract_open_loops(db_path: str) -> List[Dict[str, Any]]:
    try:
        from open_loops import list_open_loops

        return list_open_loops(db_path=db_path, limit=10)
    except Exception:  # noqa: BLE001 - summary must never fail on a missing source
        return []


def _highest_other_priority_action(db_path: str) -> Dict[str, Any] | None:
    """Highest-priority pending item that is not itself a LinkedIn draft."""
    try:
        import priority_inbox

        actions = priority_inbox.list_open_priority_actions(min_priority=0, db_path=db_path)
    except Exception:  # noqa: BLE001
        return None
    candidates = [action for action in actions if action.get("action_type") != "linkedin_post_draft"]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda action: (-(action.get("priority") or 0), action.get("created_at") or ""),
    )[0]


def _newest_linkedin_draft(db_path: str) -> Dict[str, Any] | None:
    try:
        import priority_inbox

        actions = priority_inbox.list_open_priority_actions(min_priority=0, db_path=db_path)
    except Exception:  # noqa: BLE001
        return None
    drafts = [action for action in actions if action.get("action_type") == "linkedin_post_draft"]
    if not drafts:
        return None
    return sorted(drafts, key=lambda action: action.get("created_at") or "", reverse=True)[0]


def _build_recommendations(
    priority_action: Dict[str, Any] | None,
    open_loops: List[Dict[str, Any]],
    linkedin_draft: Dict[str, Any] | None,
) -> List[str]:
    """Three rule-based recommendations. Missing sources stay explicit."""
    lines: List[str] = []
    if priority_action:
        lines.append(f"Handle priority action: {priority_action.get('title', '(untitled)')}")
    else:
        lines.append("No further recommendation.")
    if open_loops:
        lines.append(f"Follow up: {open_loops[0].get('title', '(untitled)')}")
    else:
        lines.append("No further recommendation.")
    if linkedin_draft:
        lines.append(f"Review LinkedIn draft: {linkedin_draft.get('title', '(untitled)')}")
    else:
        lines.append("No further recommendation.")
    return lines[:3]


def _format_open_loops(loops: List[Dict[str, Any]]) -> str:
    if not loops:
        return "_No open loops._"
    lines = []
    for loop in loops:
        due = loop.get("due_at")
        suffix = f" — due {due}" if due else ""
        lines.append(f"- {loop.get('title', '(untitled)')}{suffix}")
    return "\n".join(lines)


def _format_recommendations(lines: List[str]) -> str:
    padded = list(lines)
    while len(padded) < 3:
        padded.append("No further recommendation.")
    return "\n".join(f"{index}. {text}" for index, text in enumerate(padded[:3], start=1))


def _format_priority_alerts(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return "_No open priority alerts._"
    severity = {3: "URGENT", 2: "HIGH", 1: "MEDIUM", 0: "LOW"}
    lines = []
    for alert in sorted(alerts, key=lambda a: a.get("priority", 0), reverse=True):
        label = severity.get(alert.get("priority", 0), "LOW")
        title = alert.get("title", "(untitled)")
        expires = alert.get("expires_at")
        suffix = f" — due {expires}" if expires else ""
        lines.append(f"- [{label}] {title}{suffix}")
        lines.extend(_priority_alert_details(alert, title))
    return "\n".join(lines)


def _priority_alert_details(alert: Dict[str, Any], title: str) -> List[str]:
    """Sender and dates live on the payload. Say so when they were never stored."""
    payload = _alert_payload(alert)
    sender = _alert_text(payload, "from", "sender", "email") or "not recorded"
    subject = _alert_text(payload, "subject") or _description_subject(alert, title)
    mailbox = _alert_text(payload, "account", "mailbox")
    sent = _alert_text(payload, "sent_at", "date", "email_date") or "not recorded"
    recorded = alert.get("created_at") or "not recorded"
    details = [f"  From: {sender}"]
    if subject:
        details.append(f"  Subject: {subject}")
    if mailbox:
        details.append(f"  Mailbox: {mailbox}")
    details.append(f"  Sent: {sent}")
    details.append(f"  Recorded: {recorded}")
    return details


def _description_subject(alert: Dict[str, Any], title: str) -> str:
    description = alert.get("description")
    if not isinstance(description, str):
        return ""
    text = description.strip()
    if not text or text == title:
        return ""
    return text


def _alert_text(payload: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _alert_payload(alert: Dict[str, Any]) -> Dict[str, Any]:
    raw = alert.get("payload_json") or {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _extract_cto_opportunities(runs: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    opportunities: List[Dict[str, Any]] = []
    for run in runs:
        if run["skill_name"] != "cto_radar":
            continue
        try:
            payload = json.loads(run["result_json"])
        except (ValueError, TypeError):
            continue
        opportunities.extend(payload.get("opportunities", []))
    opportunities.sort(key=lambda o: o.get("score", 0), reverse=True)
    return opportunities[:limit]


def _format_cto_opportunities(opportunities: List[Dict[str, Any]]) -> str:
    if not opportunities:
        return "_No fractional CTO opportunities found in the last 24 hours._"
    lines = []
    for opp in opportunities:
        tags = ", ".join(opp.get("tags", [])) or "Uncategorized"
        location = opp.get("location", "unknown")
        work_mode = opp.get("work_mode", "unknown")
        lines.append(
            f"- {opp.get('title')} ({location}, {work_mode}; {tags}) - {opp.get('url')}"
        )
    return "\n".join(lines)


def _extract_icp_companies(runs: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    companies: List[Dict[str, Any]] = []
    for run in runs:
        if run["skill_name"] != "icp_prospector":
            continue
        try:
            payload = json.loads(run["result_json"])
        except (ValueError, TypeError):
            continue
        companies.extend(payload.get("top_companies", []))
    companies.sort(key=lambda c: c.get("score", 0), reverse=True)
    return companies[:limit]


def _format_icp_companies(companies: List[Dict[str, Any]]) -> str:
    if not companies:
        return "_No ICP companies found in the last 24 hours._"
    lines = []
    for company in companies:
        name = company.get("name") or company.get("company_name") or "(unknown)"
        industry = company.get("industry", "?")
        stage = company.get("funding_stage", "?")
        has_cto = company.get("has_cto", "?")
        hiring = company.get("is_hiring_ai", "?")
        lines.append(
            f"- {name} ({industry}, {stage}; CTO: {has_cto}, hiring AI: {hiring})"
        )
    return "\n".join(lines)


def _format_tasks(runs: List[Dict[str, Any]]) -> str:
    if not runs:
        return "_No tasks executed in the last 24 hours._"
    lines = []
    for run in runs:
        lines.append(
            f"- `{run['skill_name']}` for `{run['task_id']}` at {run['executed_at']}"
        )
    return "\n".join(lines)


def _extract_pending_bills(runs: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    pending: List[Dict[str, str]] = []
    for run in runs:
        if run["skill_name"] != "sifter":
            continue
        payload = json.loads(run["result_json"])
        for account in payload.get("accounts", []):
            for entry in account.get("categorized", []):
                if entry.get("category") == "Urgent/Bill":
                    pending.append(
                        {
                            "subject": entry.get("subject", ""),
                            "from": entry.get("from", ""),
                        }
                    )
    return pending


def _format_pending_bills(pending: List[Dict[str, str]]) -> str:
    if not pending:
        return "_No pending bills detected._"
    return "\n".join(
        [
            f"- {item['subject']} ({item['from']})"
            for item in pending
            if item["subject"] or item["from"]
        ]
    )


def _extract_top_leads(runs: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    leads: List[Dict[str, Any]] = []
    for run in runs:
        if run["skill_name"] != "lead_scout":
            continue
        payload = json.loads(run["result_json"])
        for query in payload.get("queries", []):
            for lead in query.get("leads", []):
                leads.append(lead)
    leads.sort(key=lambda lead: lead.get("score", 0), reverse=True)
    return leads[:limit]


def _format_leads(leads: List[Dict[str, Any]]) -> str:
    if not leads:
        return "_No leads found in the last 24 hours._"
    lines = []
    for lead in leads:
        tags = ", ".join(lead.get("tags", [])) or "Uncategorized"
        lines.append(f"- {lead.get('title')} ({tags}) - {lead.get('url')}")
    return "\n".join(lines)
