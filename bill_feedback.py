"""Persist 'not a bill' corrections and suppress future false positives."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from runtime import resolve_db_path

# Domains that send news/opinion digests, not invoices to pay.
SEEDED_SUPPRESS_DOMAINS = (
    "aisecret.us",
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bill_suppressions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_type TEXT NOT NULL,
    match_value TEXT NOT NULL,
    reason TEXT,
    source_action_id TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'desk',
    UNIQUE(match_type, match_value)
)
"""


def ensure_bill_suppressions_table(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            conn.execute(_TABLE_SQL)
            now = datetime.now(UTC).isoformat()
            for domain in SEEDED_SUPPRESS_DOMAINS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bill_suppressions
                        (match_type, match_value, reason, source_action_id, created_at, created_by)
                    VALUES ('sender_domain', ?, ?, NULL, ?, 'seed')
                    """,
                    (domain.lower(), "Seeded newsletter/domain false-positive guard", now),
                )
    finally:
        conn.close()
    return resolved


def normalize_sender(from_header: str) -> tuple[str, str]:
    """Return (email, domain) lowercased from a From header."""
    _name, addr = parseaddr(from_header or "")
    email = (addr or "").strip().lower()
    if not email and "@" in (from_header or ""):
        match = re.search(r"[\w.+\-]+@[\w.\-]+", from_header)
        email = match.group(0).lower() if match else ""
    domain = email.split("@", 1)[1] if "@" in email else ""
    return email, domain


def is_bill_suppressed(
    db_path: str | Path,
    sender: str,
    subject: str = "",
) -> bool:
    """True when prior feedback or seed rules say this mail is not a bill."""
    resolved = ensure_bill_suppressions_table(db_path)
    email, domain = normalize_sender(sender)
    subject_key = _subject_key(subject)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        rows = conn.execute(
            "SELECT match_type, match_value FROM bill_suppressions"
        ).fetchall()
    finally:
        conn.close()
    for match_type, match_value in rows:
        value = (match_value or "").lower()
        if match_type == "sender_email" and email and email == value:
            return True
        if match_type == "sender_domain" and domain and domain == value:
            return True
        if match_type == "subject" and subject_key and subject_key == value:
            return True
        if (
            match_type == "sender_subject"
            and email
            and subject_key
            and value == f"{email}|{subject_key}"
        ):
            return True
    return False


def record_not_a_bill(
    db_path: str | Path,
    *,
    sender: str,
    subject: str = "",
    action_id: str | None = None,
    reviewed_by: str = "desk",
    reason: str = "User marked not a bill",
    skip_domain: bool = False,
) -> dict[str, Any]:
    """Suppress future matches for this sender.

    skip_domain is for a sender on the biller list: remember this subject from
    this address only, so other mail from the company is still read.
    """
    resolved = ensure_bill_suppressions_table(db_path)
    email, domain = normalize_sender(sender)
    subject_key = _subject_key(subject)
    now = datetime.now(UTC).isoformat()
    inserted: list[str] = []
    if skip_domain:
        pairs = (("sender_subject", f"{email}|{subject_key}" if email and subject_key else ""),)
    else:
        pairs = (
            ("sender_email", email),
            ("sender_domain", domain),
            ("subject", subject_key),
        )
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            for match_type, match_value in pairs:
                if not match_value:
                    continue
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO bill_suppressions
                        (match_type, match_value, reason, source_action_id, created_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (match_type, match_value, reason, action_id, now, reviewed_by),
                )
                if cursor.rowcount:
                    inserted.append(f"{match_type}:{match_value}")
    finally:
        conn.close()
    return {"status": "ok", "inserted": inserted, "email": email, "domain": domain}


def reject_not_a_bill(
    db_path: str | Path,
    action_id: str,
    reviewed_by: str = "desk",
) -> dict[str, Any]:
    """Close the pending bill action and remember the sender/subject."""
    resolved = ensure_bill_suppressions_table(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT action_id, action_type, payload_json, status, title, description
            FROM pending_actions
            WHERE action_id = ?
            """,
            (action_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "Action not found."}
        if row["status"] != "pending":
            return {"status": "error", "message": "Action already processed."}

        payload: dict[str, Any] = {}
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        sender = payload.get("from") or ""
        subject = payload.get("subject") or row["description"] or ""

        now = datetime.now(UTC).isoformat()
        with conn:
            conn.execute(
                """
                UPDATE pending_actions
                SET status = 'rejected', reviewed_by = ?, reviewed_at = ?
                WHERE action_id = ? AND status = 'pending'
                """,
                (reviewed_by, now, action_id),
            )
    finally:
        conn.close()

    from billers import find_biller

    watched = find_biller(resolved, sender) is not None
    recorded = record_not_a_bill(
        resolved,
        sender=sender,
        subject=subject,
        action_id=action_id,
        reviewed_by=reviewed_by,
        reason="User marked not a bill on desk",
        skip_domain=watched,
    )
    domain = recorded.get("domain") or "sender"
    if watched:
        message = (
            f"Marked not a bill. I'll skip this subject from {domain} "
            "and still read other mail from that company."
        )
    else:
        message = f"Marked not a bill. I'll skip similar mail from {domain}."
    return {
        "status": "success",
        "message": message,
        "action_id": action_id,
        "suppressions": recorded.get("inserted", []),
    }


def _subject_key(subject: str) -> str:
    text = re.sub(r"\s+", " ", (subject or "").strip().lower())
    # Drop common reply/forward prefixes so variants collapse.
    text = re.sub(r"^(re|fw|fwd):\s*", "", text)
    return text[:240]
