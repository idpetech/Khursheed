"""Desk settings the morning run reads: mail window, research queries, ICP seed.

Values live in SQLite so a Railway volume keeps them. Missing keys fall back
to the defaults below. A removed ICP company is not put back.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any

from runtime import resolve_db_path

SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS desk_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

ICP_SQL = """
CREATE TABLE IF NOT EXISTS icp_seed (
    company_name TEXT PRIMARY KEY,
    website TEXT NOT NULL DEFAULT '',
    industry TEXT NOT NULL DEFAULT '',
    employee_count INTEGER NOT NULL DEFAULT 0,
    funding_stage TEXT NOT NULL DEFAULT '',
    has_cto TEXT NOT NULL DEFAULT 'unknown',
    acquired TEXT NOT NULL DEFAULT 'no',
    hiring_signals_url TEXT NOT NULL DEFAULT ''
)
"""

DEFAULT_LEAD_QUERIES = (
    "Fractional CTO roles in Jacksonville\n"
    "Warehouse optimization consulting"
)
DEFAULT_CTO_QUERIES = (
    '"fractional CTO" remote United States\n'
    '"part-time CTO" remote United States\n'
    '"interim CTO" remote United States\n'
    '"fractional CTO" Jacksonville FL hybrid OR remote\n'
    '"fractional CTO" startup Florida remote'
)

DEFAULTS = {
    "mail_lookback_days": "2",
    "brief_lookback_days": "7",
    "lead_queries": DEFAULT_LEAD_QUERIES,
    "lead_interval_days": "3",
    "cto_queries": DEFAULT_CTO_QUERIES,
    "icp_enabled": "0",
    "icp_interval_days": "3",
    "icp_industries": "saas, fintech, edtech, commerce",
    "icp_employee_min": "10",
    "icp_employee_max": "50",
    "icp_funding_stages": "seed, series-a, series-b",
    "icp_top_n": "5",
    "icp_notes": "",
    "morning_run_enabled": "1",
    "morning_run_time": "07:00",
}


def ensure_desk_settings(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            _create(conn)
    finally:
        conn.close()
    return resolved


def _create(conn: sqlite3.Connection) -> None:
    settings_existed = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'desk_settings'"
    ).fetchone()
    seed_existed = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'icp_seed'"
    ).fetchone()
    conn.execute(SETTINGS_SQL)
    conn.execute(ICP_SQL)
    if not settings_existed:
        now = datetime.now(UTC).isoformat()
        for key, value in DEFAULTS.items():
            conn.execute(
                """
                INSERT OR IGNORE INTO desk_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, value, now),
            )
    if not seed_existed:
        _seed_icp_from_csv(conn)


def _seed_icp_from_csv(conn: sqlite3.Connection) -> None:
    path = Path(__file__).resolve().parent / "data" / "icp_seed.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("company_name") or "").strip()
            if not name:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO icp_seed (
                    company_name, website, industry, employee_count,
                    funding_stage, has_cto, acquired, hiring_signals_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    (row.get("website") or "").strip(),
                    (row.get("industry") or "").strip().lower(),
                    _as_int(row.get("employee_count"), 0),
                    (row.get("funding_stage") or "").strip().lower(),
                    (row.get("has_cto") or "unknown").strip().lower(),
                    (row.get("acquired") or "no").strip().lower(),
                    (row.get("hiring_signals_url") or "").strip(),
                ),
            )


def get_setting(db_path: str | Path, key: str, default: str = "") -> str:
    resolved = ensure_desk_settings(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT value FROM desk_settings WHERE key = ?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return DEFAULTS.get(key, default)
    return str(row[0])


def set_setting(db_path: str | Path, key: str, value: str) -> None:
    resolved = ensure_desk_settings(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO desk_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
    finally:
        conn.close()


def get_int(
    db_path: str | Path,
    key: str,
    default: int,
    low: int,
    high: int,
) -> int:
    try:
        value = int(str(get_setting(db_path, key, str(default))).strip())
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def mail_lookback_days(db_path: str | Path) -> int:
    return get_int(db_path, "mail_lookback_days", 2, 1, 30)


def brief_lookback_days(db_path: str | Path) -> int:
    return get_int(db_path, "brief_lookback_days", 7, 1, 30)


def query_lines(db_path: str | Path, key: str) -> list[str]:
    raw = get_setting(db_path, key, DEFAULTS.get(key, ""))
    return [line.strip() for line in raw.splitlines() if line.strip()]


def comma_list(db_path: str | Path, key: str) -> list[str]:
    raw = get_setting(db_path, key, DEFAULTS.get(key, ""))
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def icp_enabled(db_path: str | Path) -> bool:
    return get_setting(db_path, "icp_enabled", "0").strip().lower() in {"1", "true", "yes", "on"}


def morning_run_enabled(db_path: str | Path) -> bool:
    return get_setting(db_path, "morning_run_enabled", "1").strip().lower() in {"1", "true", "yes", "on"}


def parse_morning_time(value: str) -> tuple[int, int] | None:
    """Return hour and minute for a 24-hour clock value such as 07:00."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", (value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def morning_run_is_due(now: datetime, time_text: str, last_date: str) -> bool:
    """True once, in the 30 minutes after the configured local time, if today has not run."""
    parsed = parse_morning_time(time_text)
    if parsed is None or last_date == now.date().isoformat():
        return False
    scheduled = now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
    return scheduled <= now < scheduled + timedelta(minutes=30)


def icp_payload(db_path: str | Path) -> dict[str, Any]:
    return {
        "industries": comma_list(db_path, "icp_industries"),
        "employee_min": get_int(db_path, "icp_employee_min", 10, 1, 100000),
        "employee_max": get_int(db_path, "icp_employee_max", 50, 1, 100000),
        "funding_stages": comma_list(db_path, "icp_funding_stages"),
        "top_n": get_int(db_path, "icp_top_n", 5, 1, 20),
        "notes": get_setting(db_path, "icp_notes", ""),
    }


def prepare_desk_tasks(tasks: list[dict[str, Any]], db_path: str | Path) -> list[dict[str, Any]]:
    """Copy the task file and apply the desk's mail and research settings."""
    prepared: list[dict[str, Any]] = []
    for task in tasks:
        item = dict(task)
        payload = dict(task.get("payload") or {})
        skills = list(task.get("skills") or [])
        if "sifter" in skills:
            payload["lookback_days"] = mail_lookback_days(db_path)
        if "lead_scout" in skills:
            queries = query_lines(db_path, "lead_queries")
            if queries:
                payload["queries"] = queries
            item["interval_days"] = get_int(db_path, "lead_interval_days", 3, 1, 30)
        if "cto_radar" in skills:
            queries = query_lines(db_path, "cto_queries")
            if queries:
                payload["queries"] = queries
        if "icp_prospector" in skills:
            payload.update(icp_payload(db_path))
            item["interval_days"] = get_int(db_path, "icp_interval_days", 3, 1, 30)
        item["payload"] = payload
        item["skills"] = skills
        prepared.append(item)
    if icp_enabled(db_path):
        interval = get_int(db_path, "icp_interval_days", 3, 1, 30)
        payload = icp_payload(db_path)
        if not any("icp_finder" in task["skills"] for task in prepared):
            prepared.append(
                {
                    "id": "task-icp-finder",
                    "skills": ["icp_finder"],
                    "interval_days": interval,
                    "payload": payload,
                }
            )
        if not any("icp_prospector" in task["skills"] for task in prepared):
            prepared.append(
                {
                    "id": "task-icp-prospector",
                    "skills": ["icp_prospector"],
                    "interval_days": interval,
                    "payload": payload,
                }
            )
    return prepared


def list_icp_seed(db_path: str | Path) -> list[dict[str, Any]]:
    resolved = ensure_desk_settings(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT company_name, website, industry, employee_count,
                   funding_stage, has_cto, acquired, hiring_signals_url
            FROM icp_seed
            ORDER BY company_name
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def add_icp_company(
    db_path: str | Path,
    company_name: str,
    website: str = "",
    industry: str = "",
    employee_count: int = 0,
    funding_stage: str = "",
    has_cto: str = "unknown",
) -> dict[str, Any]:
    name = (company_name or "").strip()
    if not name:
        return {"status": "error", "message": "Enter a company name."}
    resolved = ensure_desk_settings(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO icp_seed (
                    company_name, website, industry, employee_count,
                    funding_stage, has_cto, acquired, hiring_signals_url
                ) VALUES (?, ?, ?, ?, ?, ?, 'no', '')
                ON CONFLICT(company_name) DO UPDATE SET
                    website = excluded.website,
                    industry = excluded.industry,
                    employee_count = excluded.employee_count,
                    funding_stage = excluded.funding_stage,
                    has_cto = excluded.has_cto
                """,
                (
                    name,
                    (website or "").strip(),
                    (industry or "").strip().lower(),
                    _as_int(employee_count, 0),
                    (funding_stage or "").strip().lower(),
                    (has_cto or "unknown").strip().lower(),
                ),
            )
    finally:
        conn.close()
    return {"status": "ok", "message": f"Saved {name} on the ICP list."}


def remove_icp_company(db_path: str | Path, company_name: str) -> dict[str, Any]:
    name = (company_name or "").strip()
    resolved = ensure_desk_settings(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute("DELETE FROM icp_seed WHERE company_name = ?", (name,))
            removed = cursor.rowcount > 0
    finally:
        conn.close()
    if not removed:
        return {"status": "error", "message": f"{name} is not on the ICP list."}
    return {"status": "ok", "message": f"Removed {name}."}


def choose_icp_candidate(db_path: str | Path, action_id: str, accept: bool) -> dict[str, Any]:
    """Add a suggested company to the ICP list, or skip it."""
    resolved = resolve_db_path(db_path)
    action = _pending_icp_candidate(resolved, action_id)
    if action is None:
        return {"status": "error", "message": "That suggestion is no longer waiting."}
    payload = json.loads(action["payload_json"] or "{}")
    name = str(payload.get("company_name") or action["title"] or "Company").strip()
    if accept:
        add_icp_company(
            resolved,
            name,
            str(payload.get("website") or ""),
            str(payload.get("industry") or ""),
            _as_int(payload.get("employee_count"), 0),
            str(payload.get("funding_stage") or ""),
            "unknown",
        )
        _close_action(resolved, action_id, "acknowledged")
        return {"status": "ok", "message": f"Added {name} to the ICP list."}
    _close_action(resolved, action_id, "rejected")
    return {"status": "ok", "message": f"Skipped {name}."}


def _pending_icp_candidate(db_path: Path, action_id: str) -> sqlite3.Row | None:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT action_id, action_type, title, payload_json, status
            FROM pending_actions
            WHERE action_id = ?
            """,
            (action_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["status"] != "pending" or row["action_type"] != "icp_candidate":
        return None
    return row


def _close_action(db_path: Path, action_id: str, status: str) -> None:
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        with conn:
            conn.execute(
                """
                UPDATE pending_actions
                SET status = ?, reviewed_by = 'desk', reviewed_at = ?
                WHERE action_id = ? AND status = 'pending'
                """,
                (status, now, action_id),
            )
    finally:
        conn.close()


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
