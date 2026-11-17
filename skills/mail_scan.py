"""Choose mailboxes and turn a header scan into a short bill report.

The sifter reads every envelope in the lookback window, then opens a body
only when the subject looks like a bill, a renewal, a statement, or a
subscription notice.
"""

from __future__ import annotations

import hashlib
import re
from email.utils import parsedate_to_datetime


BUCKET_LABELS = {
    "upcoming_bill": "Upcoming bill / payment due",
    "renewal": "Renewal / expiration notice",
    "statement": "Invoice / statement",
    "subscription": "Recurring subscription",
}
BUCKET_ORDER = ("upcoming_bill", "renewal", "statement", "subscription")

_PROMO = ("%", "discount", "coupon", "promo", "flash sale", "mastercard", "credit card")
_IGNORE = (
    "terms of use",
    "my credit",
    "accept it asap",
    "privacy policy",
    "newsletter",
)


def parse_mailbox_name(line: str) -> str:
    """Last quoted name in an IMAP LIST line. Unquoted names use the last token."""
    quoted = re.findall(r'"((?:\\"|[^"])*)"', line or "")
    if quoted:
        return quoted[-1].replace('\\"', '"')
    parts = (line or "").split()
    return parts[-1] if parts else ""


def choose_mailboxes(names: list[str]) -> list[str]:
    """Inbox, All Mail, Receipts, and Archive. Sent, spam, and trash stay closed."""
    chosen: list[str] = []
    for name in names:
        if not name or name in chosen:
            continue
        label = name.lower().strip()
        base = label.split("/")[-1]
        if base in {"spam", "trash", "drafts", "sent", "bulk", "junk"}:
            continue
        if label == "inbox" or base == "inbox":
            chosen.append(name)
        elif "all mail" in label or base == "receipts" or base == "archive":
            chosen.append(name)
    return chosen


def local_screen(subject: str, sender: str = "") -> str | None:
    """Bucket a header, or None when the body should stay closed."""
    text = f"{subject} {sender}".lower()
    if any(marker in text for marker in _IGNORE):
        return None
    if any(marker in text for marker in _PROMO) and "statement" not in text and "invoice" not in text:
        return None
    if any(phrase in text for phrase in ("deactivat", "subscription will be", "trial ends", "trial expires", "auto-renew")):
        return "renewal"
    if any(
        phrase in text
        for phrase in (
            "upcoming bill",
            "bill estimate",
            "amount due",
            "payment due",
            "past due",
            "your bill",
            "wireless account",
            "pay your bill",
        )
    ):
        return "upcoming_bill"
    if any(phrase in text for phrase in ("statement", "invoice", "insurance document", "policy ending")):
        return "statement"
    if "credit card" not in text and "credits" in text:
        return "subscription"
    return None


def notice_source_key(bucket: str, account: str, subject: str) -> str:
    """Same mail stays one row after it has been handled or dismissed."""
    text = re.sub(r"\s+", " ", (subject or "").strip().lower())
    raw = f"{bucket}|{account}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def queue_mail_notice(
    db_path: str,
    *,
    bucket: str,
    account: str,
    subject: str,
    sender: str = "",
    line: str = "",
    message_id: str = "",
    sent_at: str = "",
) -> str | None:
    """Put a renewal, statement, or subscription where the desk can close it.

    A payable bill is queued by the sifter itself and is not duplicated here.
    """
    if bucket not in {"renewal", "statement", "subscription"}:
        return None
    source_key = notice_source_key(bucket, account, subject)
    existing = _pending_notice_id(db_path, subject, source_key)
    if existing:
        return existing
    from priority_inbox import emit_priority_action

    kind = "renewal_notice" if bucket == "renewal" else "mail_notice"
    return emit_priority_action(
        kind=kind,
        title=subject or line or "Mail notice",
        description=line or subject,
        payload={
            "bucket": bucket,
            "account": account,
            "subject": subject,
            "from": sender,
            "message_id": message_id,
            "sent_at": sent_at,
            "line": line,
        },
        priority=2 if bucket == "renewal" else 1,
        source_key=source_key,
        db_path=db_path,
    )


def _pending_notice_id(db_path: str, subject: str, source_key: str) -> str | None:
    import sqlite3

    from runtime import resolve_db_path

    conn = sqlite3.connect(resolve_db_path(db_path), timeout=30.0)
    try:
        row = conn.execute(
            """
            SELECT action_id FROM pending_actions
            WHERE source_key = ? AND status = 'pending'
            """,
            (source_key,),
        ).fetchone()
        if row:
            return row[0]
        row = conn.execute(
            """
            SELECT action_id FROM pending_actions
            WHERE status = 'pending'
              AND action_type IN ('renewal_notice', 'mail_notice')
              AND (title = ? OR description = ?)
            LIMIT 1
            """,
            (subject, subject),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE pending_actions SET source_key = ? WHERE action_id = ?",
            (source_key, row[0]),
        )
        conn.commit()
        return row[0]
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def notable_ignore(subject: str) -> bool:
    text = (subject or "").lower()
    return any(marker in text for marker in ("my credit", "terms of use", "accept it asap", "mastercard"))


def short_when(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    return f"{parsed.strftime('%b')} {parsed.day}"


def vendor_name(sender: str) -> str:
    display = (sender or "").split("<", 1)[0].strip().strip('"')
    if display and "@" not in display:
        return display
    match = re.search(r"@([^.>]+)", sender or "")
    if match:
        return match.group(1)
    return sender or "Unknown"


def format_scan_report(coverage: dict, findings: list[dict], ignored: list[str]) -> str:
    """The desk report: coverage, the four buckets, and one bottom line."""
    accounts = coverage.get("accounts") or []
    mailbox_count = sum(len(account.get("mailboxes") or []) for account in accounts)
    bits = []
    for account in accounts:
        boxes = ", ".join(account.get("mailboxes") or []) or "none"
        label = f"{account.get('name')}: {boxes}"
        failed = account.get("failed") or []
        if failed:
            label = f"{label}; could not open {', '.join(failed)}"
        if account.get("error"):
            label = f"{label} ({account['error']})"
        bits.append(label)
    coverage_line = (
        f"Coverage: {len(accounts)} accounts / {mailbox_count} mailboxes "
        f"({'; '.join(bits) or 'none'}). "
        f"{coverage.get('envelopes', 0)} envelopes reviewed, "
        f"{coverage.get('unique', 0)} unique, "
        f"{coverage.get('opened', 0)} opened, "
        f"{coverage.get('unavailable', 0)} unavailable."
    )
    sections = [coverage_line, ""]
    by_bucket: dict[str, list[dict]] = {bucket: [] for bucket in BUCKET_ORDER}
    for finding in findings:
        by_bucket.setdefault(finding.get("bucket") or "", []).append(finding)
    for bucket in BUCKET_ORDER:
        rows = by_bucket.get(bucket) or []
        if not rows:
            continue
        sections.append(BUCKET_LABELS.get(bucket, bucket))
        for row in rows:
            sections.append(f"- {row.get('line') or row.get('subject') or 'Message'}")
        sections.append("")
    if ignored:
        sections.append("Ignored / not billing (notable)")
        for subject in ignored[:8]:
            sections.append(f"- {subject}")
        sections.append("")
    sections.append(f"Bottom line: {_bottom_line(findings)}")
    return "\n".join(sections).strip()


def _bottom_line(findings: list[dict]) -> str:
    bills = [row for row in findings if row.get("bucket") == "upcoming_bill"]
    renewals = [row for row in findings if row.get("bucket") == "renewal"]
    if not bills and not renewals:
        return "No bill or renewal stood out in this scan."
    parts = []
    if len(bills) == 1:
        parts.append(f"One bill to look at — {bills[0].get('line')}")
    elif bills:
        parts.append(f"{len(bills)} bills to look at")
    if len(renewals) == 1:
        parts.append(f"one renewal — {renewals[0].get('line')}")
    elif renewals:
        parts.append(f"{len(renewals)} renewals")
    return ". ".join(parts) + "."
