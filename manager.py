import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from skills.base import Skill

PROJECT_ROOT = Path(__file__).resolve().parent


class ThreadLocalConnection:
    """Thread-local SQLite connection manager for Khursheed Manager"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.RLock()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get or create thread-local database connection"""
        if not hasattr(self._local, 'connection'):
            with self._lock:
                # Double-check after acquiring lock
                if not hasattr(self._local, 'connection'):
                    self._local.connection = sqlite3.connect(
                        self.db_path,
                        timeout=30.0,  # 30 second timeout for busy database
                        check_same_thread=False  # Allow cross-thread usage
                    )
                    # Enable WAL mode for better concurrent access
                    self._local.connection.execute("PRAGMA journal_mode=WAL")
                    self._local.connection.execute("PRAGMA synchronous=NORMAL")
        return self._local.connection
    
    def close_all(self) -> None:
        """Close all thread-local connections"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            delattr(self._local, 'connection')


class Manager:
    def __init__(self, db_path: str = "khursheed.db") -> None:
        self._skills: Dict[str, Skill] = {}
        self._db_path = PROJECT_ROOT / db_path
        self._connection_manager = ThreadLocalConnection(self._db_path)
        self._init_lock = threading.RLock()
        self._initialized = False
        self._initialize_database()

    @property
    def _connection(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        return self._connection_manager.get_connection()

    def _initialize_database(self) -> None:
        """Initialize the database schema (thread-safe)"""
        with self._init_lock:
            if self._initialized:
                return
                
            try:
                connection = self._connection
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS skill_runs (
                            task_id TEXT NOT NULL,
                            skill_name TEXT NOT NULL,
                            executed_at TEXT NOT NULL,
                            result_json TEXT NOT NULL,
                            PRIMARY KEY (task_id, skill_name)
                        )
                        """
                    )
                self._initialized = True
            except sqlite3.Error as e:
                raise RuntimeError(f"Failed to initialize Khursheed database: {e}") from e

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def register_many(self, skills: Iterable[Skill]) -> None:
        for skill in skills:
            self.register(skill)

    def list_skill_names(self) -> List[str]:
        return sorted(self._skills.keys())

    def run_skill(self, skill_name: str, task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        skill = self._skills.get(skill_name)
        if skill is None:
            raise KeyError(f"Skill '{skill_name}' is not registered.")
        result = skill.run({"id": task_id, "payload": payload, "skills": [skill_name]})
        self._record_run(task_id, skill_name, result)
        return result

    def close(self) -> None:
        """Close all database connections"""
        self._connection_manager.close_all()

    def __enter__(self) -> "Manager":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def load_tasks(self, path: str) -> List[Dict[str, Any]]:
        task_path = PROJECT_ROOT / path
        data = json.loads(task_path.read_text())
        return data.get("tasks", [])

    def run_tasks(self, tasks: Iterable[Dict[str, Any]]) -> None:
        for task in tasks:
            task_id = task["id"]
            interval_days = task.get("interval_days")
            for skill_name in task.get("skills", []):
                if interval_days is None:
                    if self._has_run(task_id, skill_name):
                        continue
                else:
                    if not self._is_due(task_id, skill_name, interval_days):
                        continue
                skill = self._skills.get(skill_name)
                if skill is None:
                    raise KeyError(f"Skill '{skill_name}' is not registered.")
                result = skill.run(task)
                self._record_run(task_id, skill_name, result)

    def _is_due(self, task_id: str, skill_name: str, interval_days: int) -> bool:
        last_run_at = self._last_run_at(task_id, skill_name)
        if last_run_at is None:
            return True
        return datetime.now(timezone.utc) - last_run_at >= timedelta(days=interval_days)

    def _last_run_at(self, task_id: str, skill_name: str) -> datetime | None:
        cursor = self._connection.execute(
            """
            SELECT executed_at
            FROM skill_runs
            WHERE task_id = ? AND skill_name = ?
            ORDER BY executed_at DESC
            LIMIT 1
            """,
            (task_id, skill_name),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0])

    def _has_run(self, task_id: str, skill_name: str) -> bool:
        cursor = self._connection.execute(
            """
            SELECT 1
            FROM skill_runs
            WHERE task_id = ? AND skill_name = ?
            """,
            (task_id, skill_name),
        )
        return cursor.fetchone() is not None

    def get_runs_since(self, since: datetime) -> List[Dict[str, Any]]:
        cursor = self._connection.execute(
            """
            SELECT task_id, skill_name, executed_at, result_json
            FROM skill_runs
            WHERE executed_at >= ?
            ORDER BY executed_at DESC
            """,
            (since.isoformat(),),
        )
        return [
            {
                "task_id": row[0],
                "skill_name": row[1],
                "executed_at": row[2],
                "result_json": row[3],
            }
            for row in cursor.fetchall()
        ]

    def _record_run(self, task_id: str, skill_name: str, result: Dict[str, Any]) -> None:
        import uuid
        run_id = str(uuid.uuid4())
        executed_at = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(result)
        status = "completed"  # Default status for successful runs
        
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO skill_runs 
                (run_id, task_id, skill_name, executed_at, result_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, task_id, skill_name, executed_at, payload, status, executed_at),
            )
