"""
Enaam State Logging

Logs all Enaam function executions to SQLite database.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional


class EnaamLogger:
    """Logger for tracking Enaam function executions"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "enaam_runs.db")
        
        self.db_path = db_path
        # Use check_same_thread=False to allow multi-threaded access
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._initialize_database()
    
    def _initialize_database(self) -> None:
        """Initialize the logging database schema"""
        with self._connection:
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS enaam_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    function_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_data TEXT,
                    output_summary TEXT,
                    execution_time_ms INTEGER,
                    error_message TEXT
                )
            """)
            
            # Create index for efficient querying
            self._connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON enaam_runs(timestamp)
            """)
            
            self._connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_function_name 
                ON enaam_runs(function_name)
            """)
    
    def log_execution(
        self,
        function_name: str,
        source: str,
        status: str,
        input_data: Dict[str, Any] = None,
        output_data: Dict[str, Any] = None,
        execution_time_ms: int = None,
        error_message: str = None
    ) -> int:
        """Log a function execution"""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create output summary
        output_summary = self._create_output_summary(output_data)
        
        with self._connection:
            cursor = self._connection.execute("""
                INSERT INTO enaam_runs (
                    timestamp, function_name, source, status,
                    input_data, output_summary, execution_time_ms, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
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
    
    def _create_output_summary(self, output_data: Dict[str, Any]) -> str:
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
        """Get recent function executions"""
        cursor = self._connection.execute("""
            SELECT id, timestamp, function_name, source, status, 
                   output_summary, execution_time_ms, error_message
            FROM enaam_runs
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        columns = ['id', 'timestamp', 'function_name', 'source', 'status', 
                  'output_summary', 'execution_time_ms', 'error_message']
        
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_function_stats(self) -> Dict[str, Any]:
        """Get statistics about function executions"""
        cursor = self._connection.execute("""
            SELECT function_name, COUNT(*) as count,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                   AVG(execution_time_ms) as avg_time_ms
            FROM enaam_runs
            GROUP BY function_name
            ORDER BY count DESC
        """)
        
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
    
    def close(self) -> None:
        """Close database connection"""
        if self._connection:
            self._connection.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global logger instance
logger = EnaamLogger()