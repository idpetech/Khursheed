"""
Priority Inbox - Emit and manage priority actions with WhatsApp alerts

Provides functions for creating priority actions with urgent WhatsApp alerts
and deduplication based on source keys.
"""

import json
import re
import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path

from notifications import send_whatsapp_template


# Configure basic logging for this module
logger = logging.getLogger(__name__)

BILL_KINDS = ("new_bill", "overdue_payment", "trial_ending")


def normalize_due_date(value: Any) -> Optional[str]:
    """Return YYYY-MM-DD, or None when the value is not a date."""
    if value in (None, "", "Unknown", "null", "None"):
        return None
    text = str(value).strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text[:10])
    if iso and text[:10] == iso.group(0):
        return iso.group(0)
    us = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if us:
        month, day, year = (int(part) for part in us.groups())
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def priority_for_bill(
    kind: str,
    due_date: Any = None,
    now: datetime | None = None,
) -> tuple[int, Optional[str]]:
    """Priority from a stored due date. No mailbox or model call."""
    if kind == "overdue_payment":
        return 3, None
    normalized = normalize_due_date(due_date)
    if normalized:
        try:
            due_dt = datetime.fromisoformat(normalized + "T23:59:59")
            current = now or datetime.now()
            if current.tzinfo is not None:
                current = current.astimezone().replace(tzinfo=None)
            days_until = (due_dt - current).days
            if days_until <= 2:
                priority = 3
            elif days_until <= 7:
                priority = 2
            else:
                priority = 1
            return priority, due_dt.isoformat()
        except ValueError:
            pass
    return 1, None


def emit_priority_action(
    kind: str,
    title: str, 
    description: str,
    payload: dict,
    priority: int,
    source_key: str,
    expires_at: Optional[str] = None,
    db_path: str = "khursheed.db"
) -> str:
    """
    Emit a priority action into the pending_actions table.
    
    Args:
        kind: Action type (e.g., 'email', 'notification', 'file_write')
        title: Short title for the action
        description: Detailed description of the action
        payload: JSON-serializable payload data
        priority: Priority level (0=low, 1=medium, 2=high, 3=urgent)
        source_key: Unique identifier for deduplication
        expires_at: Optional expiration timestamp (ISO format)
        db_path: Path to SQLite database
        
    Returns:
        str: The action_id of the created or existing action
        
    Note:
        - If source_key already exists, returns existing action_id without inserting
        - For priority >= 3, sends a WhatsApp template (if configured)
        - Never raises on notification failures, only logs warnings
    """
    db_path_obj = Path(db_path)
    
    # Connect to database with 30s busy timeout
    conn = sqlite3.connect(db_path_obj, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    
    try:
        with conn:
            # Check for existing action with same source_key
            cursor = conn.execute(
                "SELECT action_id FROM pending_actions WHERE source_key = ?",
                (source_key,)
            )
            existing = cursor.fetchone()
            
            if existing:
                return existing[0]
            
            # Create new action
            action_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            
            # Insert into pending_actions
            conn.execute("""
                INSERT INTO pending_actions (
                    action_id, action_type, title, description, payload_json,
                    created_at, created_by, status, priority, expires_at, source_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action_id, kind, title, description, json.dumps(payload, default=str),
                created_at, "priority_inbox", "pending", priority, expires_at, source_key
            ))
            
            # Arrival is one event, even when the due date is still far away.
            # A later day only messages again if the bill becomes urgent.
            if priority >= 3 or kind in BILL_KINDS:
                _send_priority_whatsapp_notification(
                    conn, action_id, title, description, payload
                )
            
            return action_id
            
    finally:
        conn.close()


def list_priority_actions(
    min_priority: int = 0, 
    db_path: str = "khursheed.db"
) -> Dict[str, Any]:
    """
    List priority actions at or above the specified priority level.
    
    Args:
        min_priority: Minimum priority level to include (default: 0 for all)
        db_path: Path to SQLite database
        
    Returns:
        Dictionary with 'actions' key containing list of actions
    """
    try:
        actions = list_open_priority_actions(min_priority, db_path)
        return {"actions": actions}
    except Exception as e:
        return {"error": f"Failed to list priority actions: {e}", "actions": []}


def list_open_priority_actions(
    min_priority: int = 2, 
    db_path: str = "khursheed.db"
) -> List[Dict[str, Any]]:
    """
    List open priority actions at or above the specified priority level.
    
    Args:
        min_priority: Minimum priority level to include (default: 2)
        db_path: Path to SQLite database
        
    Returns:
        List of pending action dictionaries, ordered by newest first
    """
    db_path_obj = Path(db_path)
    
    # Connect to database with 30s busy timeout  
    conn = sqlite3.connect(db_path_obj, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    
    try:
        cursor = conn.execute("""
            SELECT action_id, action_type, title, description, payload_json,
                   created_at, created_by, status, reviewed_at, reviewed_by,
                   executed_at, error_message, priority, expires_at, source_key
            FROM pending_actions
            WHERE status = 'pending' AND priority >= ?
            ORDER BY created_at DESC
        """, (min_priority,))
        
        columns = [
            'action_id', 'action_type', 'title', 'description', 'payload_json',
            'created_at', 'created_by', 'status', 'reviewed_at', 'reviewed_by',
            'executed_at', 'error_message', 'priority', 'expires_at', 'source_key'
        ]
        
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
        
    finally:
        conn.close()


def refresh_open_bill_priorities(db_path: str = "khursheed.db") -> List[str]:
    """Raise stored bill priorities as the due date gets closer.

    Reads only the local pending_actions rows. Does not open a mailbox.
    WhatsApp is sent only when an item first reaches priority 3.
    """
    db_path_obj = Path(db_path)
    conn = sqlite3.connect(db_path_obj, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    updated: List[str] = []
    try:
        with conn:
            rows = conn.execute(
                """
                SELECT action_id, action_type, title, description, payload_json, priority
                FROM pending_actions
                WHERE status = 'pending'
                  AND action_type IN ('new_bill', 'overdue_payment', 'trial_ending')
                """
            ).fetchall()
            for action_id, kind, title, description, payload_json, old_priority in rows:
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                new_priority, expires_at = priority_for_bill(kind, payload.get("due_date"))
                old_priority = old_priority or 0
                if new_priority <= old_priority:
                    continue
                conn.execute(
                    """
                    UPDATE pending_actions
                    SET priority = ?, expires_at = ?
                    WHERE action_id = ?
                    """,
                    (new_priority, expires_at, action_id),
                )
                updated.append(action_id)
                if new_priority >= 3 and old_priority < 3:
                    _send_priority_whatsapp_notification(
                        conn, action_id, title or "", description or "", payload
                    )
        return updated
    finally:
        conn.close()


def _whatsapp_detail(payload: dict, description: str) -> str:
    """One line for the template: vendor, amount, and due date when present."""
    vendor = payload.get("vendor")
    amount = payload.get("amount")
    currency = payload.get("currency") or ""
    due_date = payload.get("due_date")
    parts: list[str] = []
    if vendor:
        parts.append(str(vendor))
    if amount not in (None, ""):
        parts.append(f"{amount} {currency}".strip())
    if due_date:
        parts.append(f"due {due_date}")
    if parts:
        line = " · ".join(parts)
    else:
        line = description or "Open the desk for details."
    return f"{line}. Have you paid this?"


def _log_notification(
    conn: sqlite3.Connection,
    *,
    notification_type: str,
    recipient: str,
    subject: str,
    content: str,
    status: str,
    action_id: str,
    error_message: str | None = None,
    sent_at: str | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO notification_log (
            log_id, notification_type, recipient, subject, content,
            status, sent_at, error_message, related_action_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            notification_type,
            recipient,
            subject,
            content,
            status,
            sent_at,
            error_message,
            action_id,
            created_at,
        ),
    )


def _send_priority_whatsapp_notification(
    conn: sqlite3.Connection,
    action_id: str,
    title: str,
    description: str,
    payload: dict,
) -> None:
    """Send a WhatsApp template for an urgent action. Never raises."""
    detail = _whatsapp_detail(payload or {}, description)
    recipient = "configured"
    try:
        result = send_whatsapp_template(title, detail)
        _log_notification(
            conn,
            notification_type="whatsapp",
            recipient=result,
            subject=title,
            content=detail,
            status="sent",
            action_id=action_id,
            sent_at=datetime.now(timezone.utc).isoformat(),
        )
        logger.info("Priority WhatsApp sent for action %s: %s", action_id, result)
    except Exception as exc:
        error_msg = f"Failed to send priority WhatsApp: {exc}"
        logger.warning("Priority WhatsApp failed for action %s: %s", action_id, error_msg)
        _log_notification(
            conn,
            notification_type="whatsapp",
            recipient=recipient,
            subject=title,
            content=detail,
            status="failed",
            action_id=action_id,
            error_message=error_msg,
        )
