"""Senders the desk should always read for a bill, statement, or subscription.

A registered domain matches itself and any subdomain: mail2.jea.com matches jea.com.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from bill_feedback import normalize_sender
from runtime import resolve_db_path

BILLER_KINDS = ("bill", "card_statement", "subscription")

# Starting list. The desk can add and remove rows.
SEEDED_BILLERS = (
    ("paypal.com", "PayPal", "bill"),
    ("bankofamerica.com", "Bank of America", "bill"),
    ("cursor.com", "Cursor", "subscription"),
    ("anthropic.com", "Claude", "subscription"),
    ("openai.com", "OpenAI", "subscription"),
    ("jea.com", "JEA", "bill"),
    ("citi.com", "Citi", "card_statement"),
    ("tecoenergy.com", "Peoples Gas", "bill"),
)

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS billers (
    domain TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'desk'
)
"""


def ensure_billers_table(db_path: str | Path) -> Path:
    resolved = resolve_db_path(db_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'billers'"
            ).fetchone()
            conn.execute(_TABLE_SQL)
            if not exists:
                now = datetime.now(UTC).isoformat()
                for domain, name, kind in SEEDED_BILLERS:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO billers
                            (domain, display_name, kind, created_at, created_by)
                        VALUES (?, ?, ?, ?, 'seed')
                        """,
                        (domain, name, kind, now),
                    )
    finally:
        conn.close()
    return resolved


def registrable_domain(domain: str) -> str:
    """Last two labels. mail2.jea.com and info6.citi.com become jea.com and citi.com."""
    labels = [part for part in (domain or "").lower().strip(".").split(".") if part]
    if len(labels) >= 2:
        return ".".join(labels[-2:])
    return ".".join(labels)


def domain_matches(sender_domain: str, registered: str) -> bool:
    sender = (sender_domain or "").lower().strip(".")
    saved = (registered or "").lower().strip(".")
    if not sender or not saved:
        return False
    return sender == saved or sender.endswith("." + saved)


def list_billers(db_path: str | Path) -> list[dict[str, str]]:
    resolved = ensure_billers_table(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT domain, display_name, kind, created_by FROM billers ORDER BY display_name"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def find_biller(db_path: str | Path, sender: str) -> dict[str, str] | None:
    """Return the biller row whose domain matches this From header, if any."""
    _email, domain = normalize_sender(sender)
    if not domain:
        return None
    matches = [row for row in list_billers(db_path) if domain_matches(domain, row["domain"])]
    if not matches:
        return None
    matches.sort(key=lambda row: len(row["domain"]), reverse=True)
    return matches[0]


def watched_candidate_kind(db_path: str | Path, sender: str) -> str | None:
    """Kind to send to the model when the keyword screen would otherwise drop the mail."""
    row = find_biller(db_path, sender)
    if row is None:
        return None
    if row["kind"] == "subscription":
        return "trial_ending"
    return "new_bill"


def add_biller(
    db_path: str | Path,
    domain_or_sender: str,
    display_name: str = "",
    kind: str = "bill",
    created_by: str = "desk",
) -> dict[str, Any]:
    """Add a domain. An email address is reduced to its registrable domain."""
    text = (domain_or_sender or "").strip()
    if "@" in text:
        _email, domain = normalize_sender(text)
    else:
        domain = text.lower().strip(".")
    domain = registrable_domain(domain)
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        return {"status": "error", "message": "Enter a domain such as paypal.com."}
    if kind not in BILLER_KINDS:
        return {"status": "error", "message": "Kind must be bill, card statement, or subscription."}
    name = (display_name or "").strip() or domain
    resolved = ensure_billers_table(db_path)
    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO billers
                    (domain, display_name, kind, created_at, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (domain, name, kind, now, created_by),
            )
            inserted = cursor.rowcount > 0
    finally:
        conn.close()
    if not inserted:
        return {
            "status": "ok",
            "message": f"{domain} is already on the biller list.",
            "domain": domain,
            "inserted": False,
        }
    return {
        "status": "ok",
        "message": f"I'll read mail from {domain} for a {kind.replace('_', ' ')}.",
        "domain": domain,
        "inserted": True,
    }


def remove_biller(db_path: str | Path, domain: str) -> dict[str, Any]:
    saved = (domain or "").lower().strip(".")
    resolved = ensure_billers_table(db_path)
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute("DELETE FROM billers WHERE domain = ?", (saved,))
            removed = cursor.rowcount > 0
    finally:
        conn.close()
    if not removed:
        return {"status": "error", "message": f"{saved} is not on the list."}
    return {"status": "ok", "message": f"Removed {saved}.", "domain": saved}
