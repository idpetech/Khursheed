"""Startup helpers shared by the CLI, Hey Eman, and the orchestrator."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database_migrations import DatabaseMigrations


PROJECT_ROOT = Path(__file__).resolve().parent
TEST_ACTION_TYPES = ("test", "test_dedup", "test_financial")


def resolve_db_path(db_path: str | Path = "khursheed.db") -> Path:
    path = Path(db_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def prepare_runtime(db_path: str | Path = "khursheed.db") -> int:
    """Apply pending migrations and drop fixture rows from the review queue."""
    resolved = resolve_db_path(db_path)
    DatabaseMigrations(str(resolved)).run_all_migrations(verbose=False)
    return remove_test_pending_actions(resolved)


def remove_test_pending_actions(db_path: str | Path = "khursheed.db") -> int:
    """Delete fixture pending actions. Bills, drafts, and reminders stay."""
    resolved = resolve_db_path(db_path)
    if not resolved.exists():
        return 0
    conn = sqlite3.connect(resolved, timeout=30.0)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM pending_actions WHERE action_type IN (?, ?, ?)",
                TEST_ACTION_TYPES,
            )
            return cursor.rowcount
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
