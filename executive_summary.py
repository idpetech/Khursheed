from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from manager import Manager
from notifications import Notifier


def _window_phrase(days: int) -> str:
    if int(days) <= 1:
        return "the last 24 hours"
    return f"the last {int(days)} days"


def generate_executive_summary(
    manager: Manager,
    notifier: Notifier,
    now: datetime | None = None,
    lookback_days: int | None = None,
) -> str:
    timestamp = now or datetime.now(timezone.utc)
    db_path = str(getattr(manager, "_db_path", "khursheed.db"))
    if lookback_days is None:
        try:
            from desk_settings import brief_lookback_days

            lookback_days = brief_lookback_days(db_path)
        except Exception:
            lookback_days = 1
    since = timestamp - timedelta(days=lookback_days)
    runs = manager.get_runs_since(since)
    window = _window_phrase(lookback_days)

    tasks_section = _format_tasks(runs, lookback_days)
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
            _format_leads(leads, window, _research_error(runs, "lead_scout")),
            "",
            "## Fractional CTO Opportunities",
            _format_cto_opportunities(
                cto_opportunities, window, _research_error(runs, "cto_radar")
            ),
            "",
            "## Top ICP Companies",
            _format_icp_companies(icp_companies, window, _research_error(runs, "icp_prospector")),
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


def mail_origin(alert: Dict[str, Any]) -> Dict[str, str]:
    """Inbox address, sender, subject, and sent time for one stored message.

    Older rows stored a short account name such as yahoo2. That name is
    resolved to the mailbox address in config/email_accounts.json.
    """
    payload = _alert_payload(alert)
    title = alert.get("title") or ""
    nickname = _alert_text(payload, "account", "mailbox")
    inbox = _alert_text(payload, "account_email", "mailbox_email") or _mailbox_address(nickname)
    sender = _alert_text(payload, "from", "sender")
    subject = _alert_text(payload, "subject") or _description_subject(alert, title)
    sent = _alert_text(payload, "sent_at", "date", "email_date")
    return {"inbox": inbox, "sender": sender, "subject": subject, "sent": sent}


def _priority_alert_details(alert: Dict[str, Any], title: str) -> List[str]:
    """Sender and dates live on the payload. Say so when they were never stored."""
    origin = mail_origin(alert)
    recorded = alert.get("created_at") or "not recorded"
    details = [f"  Inbox: {origin['inbox'] or 'not recorded'}"]
    details.append(f"  From: {origin['sender'] or 'not recorded'}")
    if origin["subject"]:
        details.append(f"  Subject: {origin['subject']}")
    details.append(f"  Sent: {origin['sent'] or 'not recorded'}")
    details.append(f"  Recorded: {recorded}")
    return details


def _mailbox_address(nickname: str) -> str:
    if not nickname:
        return ""
    directory = _mailbox_directory()
    return directory.get(nickname, nickname)


def _mailbox_directory() -> Dict[str, str]:
    path = Path(__file__).resolve().parent / "config" / "email_accounts.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    directory: Dict[str, str] = {}
    for entry in data.get("accounts", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        username = entry.get("username")
        if isinstance(name, str) and isinstance(username, str) and name.strip() and username.strip():
            directory[name.strip()] = username.strip()
    return directory


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


def _research_error(runs: List[Dict[str, Any]], skill_name: str) -> str:
    for run in runs:
        if run.get("skill_name") != skill_name:
            continue
        payload = _parse_result(run.get("result_json"))
        error = payload.get("error")
        if error:
            return str(error)[:300]
    return ""


def _parse_result(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_cto_opportunities(
    opportunities: List[Dict[str, Any]],
    window: str = "the last 24 hours",
    error: str = "",
) -> str:
    if not opportunities:
        text = f"_No fractional CTO opportunities found in {window}._"
        if error:
            return text + f"\n\nLast search failed: {error}"
        return text
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


def _format_icp_companies(
    companies: List[Dict[str, Any]],
    window: str = "the last 24 hours",
    error: str = "",
) -> str:
    if not companies:
        text = f"_No ICP companies found in {window}._"
        if error:
            return text + f"\n\nLast search failed: {error}"
        return text
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


def _format_tasks(runs: List[Dict[str, Any]], lookback_days: int = 1) -> str:
    if not runs:
        return f"_No tasks executed in {_window_phrase(lookback_days)}._"
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
                subject = entry.get("subject", "")
                bill_words = ("invoice", "past due", "amount due", "payment due", "overdue", "receipt", "statement")
                if entry.get("category") == "Urgent/Bill" and any(
                    word in subject.lower() for word in bill_words
                ):
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
        for query in payload.get("queries") or []:
            for lead in query.get("leads", []):
                leads.append(lead)
    leads.sort(key=lambda lead: lead.get("score", 0), reverse=True)
    return leads[:limit]


def _format_leads(
    leads: List[Dict[str, Any]],
    window: str = "the last 24 hours",
    error: str = "",
) -> str:
    if not leads:
        text = f"_No leads found in {window}._"
        if error:
            return text + f"\n\nLast search failed: {error}"
        return text
    lines = []
    for lead in leads:
        tags = ", ".join(lead.get("tags", [])) or "Uncategorized"
        lines.append(f"- {lead.get('title')} ({tags}) - {lead.get('url')}")
    return "\n".join(lines)
