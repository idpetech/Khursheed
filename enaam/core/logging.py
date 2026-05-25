"""
Enaam State Logging

Thread-safe logging for all Enaam function executions to SQLite database.
"""

import json
import sqlite3
import threading
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import DatabaseConstants, PathConstants
from .error_handler import handle_database_errors, get_error_logger
from .exceptions import DatabaseError


class ThreadLocalConnection:
    """Thread-local SQLite connection manager"""
    
    def __init__(self, db_path: str):
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
                        timeout=DatabaseConstants.DEFAULT_TIMEOUT,  # 30 second timeout for busy database
                        isolation_level=DatabaseConstants.DEFERRED_ISOLATION  # Better concurrency
                    )
                    # Enable WAL mode for better concurrent access
                    self._local.connection.execute(DatabaseConstants.PRAGMA_JOURNAL_MODE_WAL)
                    self._local.connection.execute(DatabaseConstants.PRAGMA_SYNCHRONOUS_NORMAL)
        return self._local.connection
    
    def close_all(self) -> None:
        """Close all thread-local connections"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            delattr(self._local, 'connection')


class EnaamLogger:
    """Thread-safe logger for tracking Enaam function executions"""
    
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            # Default to data directory in project root
            data_dir = PathConstants.get_data_dir()
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / DatabaseConstants.ENAAM_RUNS_DB)
        
        self.db_path = db_path
        self._connection_manager = ThreadLocalConnection(db_path)
        self._init_lock = threading.RLock()
        self._initialized = False
        self._initialize_database()
    
    @property
    def _connection(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        return self._connection_manager.get_connection()
    
    def _initialize_database(self) -> None:
        """Initialize the logging database schema (thread-safe)"""
        with self._init_lock:
            if self._initialized:
                return
                
            try:
                connection = self._connection
                with connection:
                    connection.execute(DatabaseConstants.CREATE_ENAAM_RUNS_TABLE)
                    
                    # Create index for efficient querying
                    connection.execute(DatabaseConstants.CREATE_TIMESTAMP_INDEX)
                    
                    connection.execute(DatabaseConstants.CREATE_FUNCTION_NAME_INDEX)
                    
                self._initialized = True
            except sqlite3.Error as e:
                logger = get_error_logger('logging')
                logger.exception("Failed to initialize Enaam logging database")
                raise DatabaseError(
                    f"Failed to initialize Enaam logging database: {str(e)}",
                    operation="database_initialization",
                    cause=e
                )
    
    def log_execution(
        self,
        function_name: str,
        source: str,
        status: str,
        input_data: dict[str, Any] = None,
        output_data: dict[str, Any] = None,
        execution_time_ms: int = None,
        error_message: str = None
    ) -> int | None:
        """Log a function execution (thread-safe)"""
        try:
            # Ensure database is initialized for this thread
            if not self._initialized:
                self._initialize_database()
                
            timestamp = datetime.now(UTC).isoformat()
            
            # Create output summary
            output_summary = self._create_output_summary(output_data)
            
            connection = self._connection
            with connection:
                cursor = connection.execute(DatabaseConstants.INSERT_ENAAM_RUN, (
                    timestamp,
                    function_name,
                    source,
                    status,
                    json.dumps(input_data) if input_data else None,
                    output_summary,
                    execution_time_ms,
                    error_message
                ))
                
                return cursor.lastrowid
                
        except sqlite3.Error as e:
            # Log to stderr instead of raising to avoid breaking main functionality
            logger = get_error_logger('logging')
            logger.error("Failed to log execution to database: %s", str(e))
            return None
        except Exception as e:
            logger = get_error_logger('logging')
            logger.exception("Unexpected error in log_execution")
            return None
    
    def _create_output_summary(self, output_data: dict[str, Any]) -> str:
        """Create a concise summary of the output data"""
        if not output_data:
            return None
            
        # Extract key information for summary
        summary_parts = []
        
        if "status" in output_data:
            summary_parts.append(f"Status: {output_data['status']}")
            
        if "action" in output_data:
            summary_parts.append(f"Action: {output_data['action']}")
            
        data = output_data.get("data", {})
        if isinstance(data, dict):
            if "summary" in data:
                # Truncate long summaries
                summary = data["summary"]
                if len(summary) > 200:
                    summary = summary[:200] + "..."
                summary_parts.append(f"Summary: {summary}")
                
            if "tasks_executed" in data:
                summary_parts.append(f"Tasks executed: {data['tasks_executed']}")
                
            if "error" in data:
                summary_parts.append(f"Error: {data['error']}")
        
        return " | ".join(summary_parts) if summary_parts else json.dumps(output_data)[:500]
    
    def get_recent_runs(self, limit: int = 50) -> list:
        """Get recent function executions (thread-safe)"""
        try:
            # Ensure database is initialized for this thread
            if not self._initialized:
                self._initialize_database()
                
            connection = self._connection
            cursor = connection.execute(DatabaseConstants.SELECT_RECENT_RUNS, (limit,))
            
            columns = ['id', 'timestamp', 'function_name', 'source', 'status', 
                      'output_summary', 'execution_time_ms', 'error_message']
            
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
            
        except sqlite3.Error as e:
            logger = get_error_logger('logging')
            logger.error("Failed to get recent runs: %s", str(e))
            return []
    
    def get_function_stats(self) -> dict[str, Any]:
        """Get statistics about function executions (thread-safe)"""
        try:
            # Ensure database is initialized for this thread
            if not self._initialized:
                self._initialize_database()
                
            connection = self._connection
            cursor = connection.execute(DatabaseConstants.SELECT_FUNCTION_STATS)
            
            stats = {}
            for row in cursor.fetchall():
                function_name, count, successes, errors, avg_time = row
                stats[function_name] = {
                    "total_executions": count,
                    "successes": successes,
                    "errors": errors,
                    "success_rate": successes / count if count > 0 else 0,
                    "avg_execution_time_ms": round(avg_time, 2) if avg_time else None
                }
                
            return stats
            
        except sqlite3.Error as e:
            logger = get_error_logger('logging')
            logger.error("Failed to get function stats: %s", str(e))
            return {}
    
    def close(self) -> None:
        """Close all database connections"""
        try:
            self._connection_manager.close_all()
        except Exception as e:
            logger = get_error_logger('logging')
            logger.error("Error closing database connections: %s", str(e))
    
    # Standard logging interface methods for compatibility
    def debug(self, message: str, *args) -> None:
        """Debug logging (compatible with standard logger interface)"""
        error_logger = get_error_logger('enaam_logger')
        error_logger.debug(message, *args)
    
    def info(self, message: str, *args) -> None:
        """Info logging (compatible with standard logger interface)"""
        error_logger = get_error_logger('enaam_logger')
        error_logger.info(message, *args)
    
    def warning(self, message: str, *args) -> None:
        """Warning logging (compatible with standard logger interface)"""
        error_logger = get_error_logger('enaam_logger')
        error_logger.warning(message, *args)
    
    def error(self, message: str, *args) -> None:
        """Error logging (compatible with standard logger interface)"""
        error_logger = get_error_logger('enaam_logger')
        error_logger.error(message, *args)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Factory function for creating logger instances
def create_logger(db_path: str | None = None) -> EnaamLogger:
    """
    Create a new EnaamLogger instance.
    
    This factory function creates logger instances without any global state.
    All instances are independent and thread-safe.
    
    Args:
        db_path: Optional database path. If None, uses default location.
        
    Returns:
        New EnaamLogger instance
    """
    return EnaamLogger(db_path)


# Dependency injection helper
def create_default_logger() -> EnaamLogger:
    """Create default logger instance for dependency injection."""
    return create_logger()