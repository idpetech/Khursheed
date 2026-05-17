from __future__ import annotations

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

    tasks_section = _format_tasks(runs)
    pending_bills = _extract_pending_bills(runs)
    leads = _extract_top_leads(runs, limit=3)

    report = "\n".join(
        [
            f"# Executive Summary - {timestamp.date().isoformat()}",
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
        ]
    )
    notifier.send(report)
    return report


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
