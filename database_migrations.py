"""
Database migrations for Victor-style command center
Implements unified timeline, review queue, scheduled jobs, and notification logging
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional


class DatabaseMigrations:
    """Handles database schema migrations for Victor-style command center"""
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = Path(db_path)
        
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with proper configuration"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
        
    def run_all_migrations(self) -> None:
        """Run all migrations in sequence"""
        with self.get_connection() as conn:
            # Create migration tracking table first
            self._create_migration_table(conn)
            
            # Run each migration if not already applied
            migrations = [
                (1, "create_skill_runs_v2", self._migrate_skill_runs_to_append_only),
                (2, "create_pending_actions", self._create_pending_actions_table),
                (3, "create_scheduled_jobs", self._create_scheduled_jobs_table),
                (4, "create_notification_log", self._create_notification_log_table),
                (5, "create_unified_timeline_view", self._create_unified_timeline_view),
                (6, "create_skill_registry", self._create_skill_registry_table),
            ]
            
            for version, name, migration_func in migrations:
                if not self._is_migration_applied(conn, version):
                    print(f"Applying migration {version}: {name}")
                    migration_func(conn)
                    self._mark_migration_applied(conn, version, name)
                    print(f"✓ Migration {version} completed")
                else:
                    print(f"Migration {version}: {name} already applied")
    
    def _create_migration_table(self, conn: sqlite3.Connection) -> None:
        """Create table to track applied migrations"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        
    def _is_migration_applied(self, conn: sqlite3.Connection, version: int) -> bool:
        """Check if migration is already applied"""
        cursor = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        )
        return cursor.fetchone() is not None
        
    def _mark_migration_applied(self, conn: sqlite3.Connection, version: int, name: str) -> None:
        """Mark migration as applied"""
        conn.execute(
            """INSERT INTO schema_migrations (version, name, applied_at) 
               VALUES (?, ?, ?)""",
            (version, name, datetime.now(timezone.utc).isoformat())
        )
        
    def _migrate_skill_runs_to_append_only(self, conn: sqlite3.Connection) -> None:
        """Migration 1: Convert skill_runs to append-only with run_id"""
        
        # Check if old table exists
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='skill_runs'
        """)
        
        if cursor.fetchone():
            # Rename old table
            conn.execute("ALTER TABLE skill_runs RENAME TO skill_runs_old")
        
        # Create new append-only skill_runs table
        conn.execute("""
            CREATE TABLE skill_runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                result_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                error_message TEXT,
                execution_time_ms INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        
        # Create indexes for efficient querying
        conn.execute("""
            CREATE INDEX idx_skill_runs_task_id ON skill_runs(task_id)
        """)
        conn.execute("""
            CREATE INDEX idx_skill_runs_skill_name ON skill_runs(skill_name)
        """)
        conn.execute("""
            CREATE INDEX idx_skill_runs_executed_at ON skill_runs(executed_at)
        """)
        
        # Migrate data from old table if it exists
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='skill_runs_old'
        """)
        
        if cursor.fetchone():
            conn.execute("""
                INSERT INTO skill_runs 
                (run_id, task_id, skill_name, executed_at, result_json, status, created_at)
                SELECT 
                    hex(randomblob(16)) as run_id,
                    task_id,
                    skill_name, 
                    executed_at,
                    result_json,
                    'completed' as status,
                    executed_at as created_at
                FROM skill_runs_old
            """)
            
            # Drop old table
            conn.execute("DROP TABLE skill_runs_old")
        
        # Create view for latest run per task/skill (backward compatibility)
        conn.execute("""
            CREATE VIEW latest_skill_runs AS
            SELECT sr.*
            FROM skill_runs sr
            INNER JOIN (
                SELECT task_id, skill_name, MAX(executed_at) as max_executed_at
                FROM skill_runs
                GROUP BY task_id, skill_name
            ) latest ON sr.task_id = latest.task_id 
                    AND sr.skill_name = latest.skill_name
                    AND sr.executed_at = latest.max_executed_at
        """)
        
    def _create_pending_actions_table(self, conn: sqlite3.Connection) -> None:
        """Migration 2: Create pending_actions table for review/approve flow"""
        conn.execute("""
            CREATE TABLE pending_actions (
                action_id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,  -- 'email', 'notification', 'file_write', etc.
                title TEXT NOT NULL,
                description TEXT,
                payload_json TEXT NOT NULL,  -- JSON data for the action
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                created_by TEXT NOT NULL DEFAULT 'system',
                status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved', 'rejected', 'executed'
                reviewed_at TEXT,
                reviewed_by TEXT,
                executed_at TEXT,
                error_message TEXT,
                priority INTEGER NOT NULL DEFAULT 0,  -- 0=low, 1=medium, 2=high, 3=urgent
                expires_at TEXT  -- Optional expiration
            )
        """)
        
        # Create indexes
        conn.execute("""
            CREATE INDEX idx_pending_actions_status ON pending_actions(status)
        """)
        conn.execute("""
            CREATE INDEX idx_pending_actions_type ON pending_actions(action_type)
        """)
        conn.execute("""
            CREATE INDEX idx_pending_actions_created_at ON pending_actions(created_at)
        """)
        conn.execute("""
            CREATE INDEX idx_pending_actions_priority ON pending_actions(priority DESC)
        """)
        
    def _create_scheduled_jobs_table(self, conn: sqlite3.Connection) -> None:
        """Migration 3: Create scheduled_jobs table to replace interval_days"""
        conn.execute("""
            CREATE TABLE scheduled_jobs (
                job_id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL UNIQUE,
                job_type TEXT NOT NULL,  -- 'skill', 'bridge_function', 'custom'
                target TEXT NOT NULL,  -- skill name or function name
                payload_json TEXT NOT NULL DEFAULT '{}',
                schedule_type TEXT NOT NULL,  -- 'interval', 'cron', 'one_time'
                schedule_config TEXT NOT NULL,  -- JSON config: {"interval_hours": 24} or {"cron": "0 9 * * 1"}
                next_run_at TEXT NOT NULL,
                last_run_at TEXT,
                last_status TEXT,  -- 'success', 'failed', 'skipped'
                last_error TEXT,
                run_count INTEGER NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        
        # Create indexes
        conn.execute("""
            CREATE INDEX idx_scheduled_jobs_next_run ON scheduled_jobs(next_run_at)
        """)
        conn.execute("""
            CREATE INDEX idx_scheduled_jobs_enabled ON scheduled_jobs(enabled)
        """)
        conn.execute("""
            CREATE INDEX idx_scheduled_jobs_name ON scheduled_jobs(job_name)
        """)
        
    def _create_notification_log_table(self, conn: sqlite3.Connection) -> None:
        """Migration 4: Create notification_log for delivery tracking"""
        conn.execute("""
            CREATE TABLE notification_log (
                log_id TEXT PRIMARY KEY,
                notification_type TEXT NOT NULL,  -- 'email', 'file', 'webhook', etc.
                recipient TEXT NOT NULL,  -- email address, file path, URL, etc.
                subject TEXT,
                content TEXT,
                status TEXT NOT NULL,  -- 'sent', 'failed', 'pending', 'retry'
                sent_at TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT,  -- Additional context (headers, file size, etc.)
                related_run_id TEXT,  -- Link to skill_runs.run_id if applicable
                related_action_id TEXT,  -- Link to pending_actions.action_id if applicable
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        
        # Create indexes
        conn.execute("""
            CREATE INDEX idx_notification_log_type ON notification_log(notification_type)
        """)
        conn.execute("""
            CREATE INDEX idx_notification_log_status ON notification_log(status)
        """)
        conn.execute("""
            CREATE INDEX idx_notification_log_sent_at ON notification_log(sent_at)
        """)
        conn.execute("""
            CREATE INDEX idx_notification_log_related_run ON notification_log(related_run_id)
        """)
        
    def _create_skill_registry_table(self, conn: sqlite3.Connection) -> None:
        """Migration 6: Create skill_registry for central skill management"""
        conn.execute("""
            CREATE TABLE skill_registry (
                skill_name TEXT PRIMARY KEY,
                skill_class TEXT NOT NULL,
                module_path TEXT NOT NULL,
                description TEXT,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                config_schema TEXT,  -- JSON schema for skill configuration
                last_registered_at TEXT NOT NULL DEFAULT (datetime('now')),
                version TEXT,
                dependencies TEXT,  -- JSON array of required dependencies
                metadata_json TEXT   -- Additional metadata
            )
        """)
        
        # Create index
        conn.execute("""
            CREATE INDEX idx_skill_registry_enabled ON skill_registry(enabled)
        """)
        
    def _create_unified_timeline_view(self, conn: sqlite3.Connection) -> None:
        """Migration 5: Create unified timeline view aggregating all events"""
        conn.execute("""
            CREATE VIEW unified_timeline AS
            -- Skill runs
            SELECT 
                'skill_run' as event_type,
                run_id as event_id,
                skill_name as event_source,
                task_id as event_context,
                executed_at as event_time,
                status as event_status,
                json_object(
                    'skill_name', skill_name,
                    'task_id', task_id,
                    'execution_time_ms', execution_time_ms,
                    'result_summary', CASE 
                        WHEN length(result_json) > 200 
                        THEN substr(result_json, 1, 200) || '...'
                        ELSE result_json 
                    END
                ) as event_data,
                error_message
            FROM skill_runs
            
            UNION ALL
            
            -- Pending actions
            SELECT 
                'pending_action' as event_type,
                action_id as event_id,
                action_type as event_source,
                title as event_context,
                created_at as event_time,
                status as event_status,
                json_object(
                    'action_type', action_type,
                    'priority', priority,
                    'description', description,
                    'created_by', created_by
                ) as event_data,
                error_message
            FROM pending_actions
            
            UNION ALL
            
            -- Notification log
            SELECT 
                'notification' as event_type,
                log_id as event_id,
                notification_type as event_source,
                recipient as event_context,
                COALESCE(sent_at, created_at) as event_time,
                status as event_status,
                json_object(
                    'notification_type', notification_type,
                    'subject', subject,
                    'retry_count', retry_count
                ) as event_data,
                error_message
            FROM notification_log
            
            UNION ALL
            
            -- Scheduled job runs
            SELECT 
                'scheduled_job' as event_type,
                job_id as event_id,
                job_name as event_source,
                target as event_context,
                COALESCE(last_run_at, created_at) as event_time,
                COALESCE(last_status, 'scheduled') as event_status,
                json_object(
                    'job_type', job_type,
                    'schedule_type', schedule_type,
                    'next_run_at', next_run_at,
                    'run_count', run_count
                ) as event_data,
                last_error as error_message
            FROM scheduled_jobs
            
            ORDER BY event_time DESC
        """)


def migrate_database(db_path: str = "khursheed.db") -> None:
    """Run database migrations"""
    migrations = DatabaseMigrations(db_path)
    migrations.run_all_migrations()
    print("✓ All database migrations completed successfully")


if __name__ == "__main__":
    migrate_database()