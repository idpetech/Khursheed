"""
Priority Inbox - Emit and manage priority actions with email notifications

Provides functions for creating priority actions with automatic email notifications
for high-priority items and deduplication based on source keys.
"""

import os
import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pathlib import Path

from notifications import EmailNotifier


# Configure basic logging for this module
logger = logging.getLogger(__name__)


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
    Emit a priority action into the pending_actions table with email notifications.
    
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
        - For priority >= 2, sends email notification (if configured)
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
                # Return existing action_id, no email needed
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
                action_id, kind, title, description, str(payload),
                created_at, "priority_inbox", "pending", priority, expires_at, source_key
            ))
            
            # Send email notification if priority >= 2
            if priority >= 2:
                _send_priority_email_notification(
                    conn, action_id, title, description, priority
                )
            
            return action_id
            
    finally:
        conn.close()


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


def _send_priority_email_notification(
    conn: sqlite3.Connection,
    action_id: str,
    title: str, 
    description: str,
    priority: int
) -> None:
    """
    Send email notification for priority action.
    
    Args:
        conn: Database connection for logging
        action_id: Action ID to link notification log
        title: Action title
        description: Action description  
        priority: Priority level
        
    Note:
        Never raises exceptions - degrades gracefully and logs warnings
    """
    log_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    # Get email configuration from environment
    email_to = os.getenv("KHURSHEED_PRIORITY_EMAIL_TO")
    email_from = os.getenv("KHURSHEED_PRIORITY_EMAIL_FROM") 
    email_password = os.getenv("KHURSHEED_PRIORITY_EMAIL_PASSWORD")
    smtp_host = os.getenv("KHURSHEED_PRIORITY_EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("KHURSHEED_PRIORITY_EMAIL_SMTP_PORT", "587"))
    
    # Check required configuration
    if not all([email_to, email_from, email_password]):
        # Log warning and skip email
        logger.warning(
            "Priority email configuration incomplete - skipping notification for action %s", 
            action_id
        )
        
        # Log the skip to notification_log
        conn.execute("""
            INSERT INTO notification_log (
                log_id, notification_type, recipient, subject, content,
                status, error_message, related_action_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, "email", email_to or "unknown", 
            f"Priority Action: {title}",
            f"Description: {description}\nPriority: {priority}",
            "failed", "Email configuration incomplete (missing env vars)",
            action_id, created_at
        ))
        return
    
    # Attempt to send email
    try:
        priority_text = {0: "Low", 1: "Medium", 2: "High", 3: "Urgent"}.get(priority, "Unknown")
        subject = f"🚨 {priority_text} Priority Action: {title}"
        content = f"""
Priority Action Alert

Title: {title}
Priority: {priority_text} ({priority})
Action ID: {action_id}

Description:
{description}

This is an automated notification from Khursheed Priority Inbox.
Please review and take appropriate action.
        """.strip()
        
        # Create and send email
        notifier = EmailNotifier(
            sender=email_from,
            password=email_password, 
            recipient=email_to,
            subject=subject,
            smtp_host=smtp_host,
            smtp_port=smtp_port
        )
        
        result = notifier.send(content)
        sent_at = datetime.now(timezone.utc).isoformat()
        
        # Log successful send
        conn.execute("""
            INSERT INTO notification_log (
                log_id, notification_type, recipient, subject, content,
                status, sent_at, related_action_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, "email", email_to, subject, content,
            "sent", sent_at, action_id, created_at
        ))
        
        logger.info("Priority email sent for action %s: %s", action_id, result)
        
    except Exception as e:
        # Log error and continue - never raise
        error_msg = f"Failed to send priority email: {str(e)}"
        logger.warning("Priority email failed for action %s: %s", action_id, error_msg)
        
        # Log the failure to notification_log
        conn.execute("""
            INSERT INTO notification_log (
                log_id, notification_type, recipient, subject, content,
                status, error_message, related_action_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, "email", email_to, subject, content,
            "failed", error_msg, action_id, created_at
        ))