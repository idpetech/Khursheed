"""
Victor-style Central Orchestrator
Single entry point for all command routing (CLI, UI, MCP)
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from database_migrations import DatabaseMigrations
from manager import Manager
from skills.base import Skill


class SkillRegistry:
    """Central registry for all skills"""
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = Path(db_path)
        self._ensure_db_initialized()
        
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
        
    def _ensure_db_initialized(self) -> None:
        """Ensure database is initialized with latest schema"""
        migrations = DatabaseMigrations(str(self.db_path))
        migrations.run_all_migrations()
        
    def register_skill(self, skill: Skill, module_path: str = None) -> None:
        """Register a skill in the central registry"""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skill_registry 
                (skill_name, skill_class, module_path, description, enabled, last_registered_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                skill.name,
                skill.__class__.__name__,
                module_path or f"skills.{skill.name}",
                (getattr(skill, '__doc__', '') or '').strip() or None,
                True,
                datetime.now(timezone.utc).isoformat()
            ))
            
    def get_enabled_skills(self) -> List[Dict[str, Any]]:
        """Get list of all enabled skills"""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT skill_name, skill_class, module_path, description, version
                FROM skill_registry 
                WHERE enabled = 1
                ORDER BY skill_name
            """)
            return [dict(zip([col[0] for col in cursor.description], row)) 
                   for row in cursor.fetchall()]
            
    def is_skill_enabled(self, skill_name: str) -> bool:
        """Check if skill is enabled"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT enabled FROM skill_registry WHERE skill_name = ?",
                (skill_name,)
            )
            row = cursor.fetchone()
            return row[0] if row else False


class PendingActionManager:
    """Manages pending actions for review/approve flow"""
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = Path(db_path)
        
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.Connection(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
        
    def create_pending_action(
        self, 
        action_type: str,
        title: str,
        payload: Dict[str, Any],
        description: str = None,
        priority: int = 0,
        created_by: str = "system"
    ) -> str:
        """Create a new pending action"""
        action_id = str(uuid.uuid4())
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO pending_actions 
                (action_id, action_type, title, description, payload_json, 
                 priority, created_by, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action_id,
                action_type,
                title,
                description,
                json.dumps(payload),
                priority,
                created_by,
                'pending',
                datetime.now(timezone.utc).isoformat()
            ))
            
        return action_id
        
    def get_pending_actions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get list of pending actions"""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT action_id, action_type, title, description, payload_json,
                       priority, created_by, status, created_at, expires_at
                FROM pending_actions 
                WHERE status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT ?
            """, (limit,))
            
            return [dict(zip([col[0] for col in cursor.description], row)) 
                   for row in cursor.fetchall()]
                   
    def approve_action(self, action_id: str, reviewed_by: str = "user") -> Dict[str, Any]:
        """Approve and execute a pending action"""
        with self._get_connection() as conn:
            # Get action details
            cursor = conn.execute("""
                SELECT action_type, payload_json FROM pending_actions 
                WHERE action_id = ? AND status = 'pending'
            """, (action_id,))
            
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Action not found or already processed"}
                
            action_type, payload_json = row
            payload = json.loads(payload_json)
            
            # Mark as approved
            conn.execute("""
                UPDATE pending_actions 
                SET status = 'approved', reviewed_by = ?, reviewed_at = ?
                WHERE action_id = ?
            """, (reviewed_by, datetime.now(timezone.utc).isoformat(), action_id))
            
            return {
                "status": "success", 
                "action_id": action_id,
                "action_type": action_type,
                "payload": payload
            }
            
    def reject_action(self, action_id: str, reviewed_by: str = "user") -> bool:
        """Reject a pending action"""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                UPDATE pending_actions 
                SET status = 'rejected', reviewed_by = ?, reviewed_at = ?
                WHERE action_id = ? AND status = 'pending'
            """, (reviewed_by, datetime.now(timezone.utc).isoformat(), action_id))
            
            return cursor.rowcount > 0


class ScheduledJobManager:
    """Manages scheduled jobs replacing interval-based system"""
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = Path(db_path)
        
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
        
    def create_job(
        self,
        job_name: str,
        job_type: str,
        target: str,
        schedule_config: Dict[str, Any],
        payload: Dict[str, Any] = None,
        enabled: bool = True
    ) -> str:
        """Create a new scheduled job"""
        job_id = str(uuid.uuid4())
        next_run = self._calculate_next_run(schedule_config)
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO scheduled_jobs 
                (job_id, job_name, job_type, target, payload_json, schedule_type,
                 schedule_config, next_run_at, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                job_name,
                job_type,
                target,
                json.dumps(payload or {}),
                schedule_config.get('type', 'interval'),
                json.dumps(schedule_config),
                next_run,
                enabled,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat()
            ))
            
        return job_id
        
    def _calculate_next_run(self, schedule_config: Dict[str, Any]) -> str:
        """Calculate next run time based on schedule config"""
        schedule_type = schedule_config.get('type', 'interval')
        now = datetime.now(timezone.utc)
        
        if schedule_type == 'interval':
            hours = schedule_config.get('interval_hours', 24)
            next_run = now + timedelta(hours=hours)
        elif schedule_type == 'daily':
            hour = schedule_config.get('hour', 9)
            minute = schedule_config.get('minute', 0)
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
        else:
            # Default to 24 hours from now
            next_run = now + timedelta(hours=24)
            
        return next_run.isoformat()
        
    def get_due_jobs(self) -> List[Dict[str, Any]]:
        """Get jobs that are due to run"""
        now = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT job_id, job_name, job_type, target, payload_json, schedule_config
                FROM scheduled_jobs 
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
            """, (now,))
            
            return [dict(zip([col[0] for col in cursor.description], row)) 
                   for row in cursor.fetchall()]
                   
    def update_job_status(self, job_id: str, status: str, error: str = None) -> None:
        """Update job status after execution"""
        now = datetime.now(timezone.utc).isoformat()
        
        with self._get_connection() as conn:
            # Get current schedule config to calculate next run
            cursor = conn.execute(
                "SELECT schedule_config FROM scheduled_jobs WHERE job_id = ?",
                (job_id,)
            )
            row = cursor.fetchone()
            if row:
                schedule_config = json.loads(row[0])
                next_run = self._calculate_next_run(schedule_config)
                
                conn.execute("""
                    UPDATE scheduled_jobs 
                    SET last_run_at = ?, last_status = ?, last_error = ?,
                        next_run_at = ?, run_count = run_count + 1,
                        updated_at = ?
                    WHERE job_id = ?
                """, (now, status, error, next_run, now, job_id))


class VictorOrchestrator:
    """
    Central orchestrator for Victor-style command center
    Single entry point for all commands from CLI, UI, and MCP
    """
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = db_path
        self.manager = Manager(db_path)
        self.skill_registry = SkillRegistry(db_path)
        self.pending_actions = PendingActionManager(db_path)
        self.scheduled_jobs = ScheduledJobManager(db_path)
        self.logger = logging.getLogger("victor_orchestrator")
        
        # Initialize database
        self._initialize_database()
        
    def _initialize_database(self) -> None:
        """Initialize database with latest schema"""
        migrations = DatabaseMigrations(self.db_path)
        migrations.run_all_migrations()
        
    def register_skill(self, skill: Skill) -> None:
        """Register skill in both manager and registry"""
        self.manager.register(skill)
        self.skill_registry.register_skill(skill)
        
    def register_skills(self, skills: List[Skill]) -> None:
        """Register multiple skills"""
        for skill in skills:
            self.register_skill(skill)
            
    def execute_command(self, command: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Central command execution entry point
        
        Args:
            command: Command to execute (e.g., "run_skill", "check_email", "executive_summary")
            context: Command context including parameters, user info, etc.
            
        Returns:
            Standardized response dictionary
        """
        context = context or {}
        run_id = str(uuid.uuid4())
        
        try:
            self.logger.info(f"Executing command: {command}", extra={
                "run_id": run_id,
                "command": command,
                "context_keys": list(context.keys())
            })
            
            # Route command to appropriate handler
            if command == "run_skill":
                return self._handle_run_skill(run_id, context)
            elif command == "check_email":
                return self._handle_check_email(run_id, context)
            elif command == "executive_summary":
                return self._handle_executive_summary(run_id, context)
            elif command == "lead_generation":
                return self._handle_lead_generation(run_id, context)
            elif command == "get_timeline":
                return self._handle_get_timeline(run_id, context)
            elif command == "get_pending_actions":
                return self._handle_get_pending_actions(run_id, context)
            elif command == "approve_action":
                return self._handle_approve_action(run_id, context)
            elif command == "reject_action":
                return self._handle_reject_action(run_id, context)
            elif command == "run_scheduled_jobs":
                return self._handle_run_scheduled_jobs(run_id, context)
            elif command == "list_skills":
                return self._handle_list_skills(run_id, context)
            else:
                return {
                    "status": "error",
                    "run_id": run_id,
                    "message": f"Unknown command: {command}",
                    "available_commands": [
                        "run_skill", "check_email", "executive_summary", 
                        "lead_generation", "get_timeline", "get_pending_actions",
                        "approve_action", "reject_action", "run_scheduled_jobs", "list_skills"
                    ]
                }
                
        except Exception as e:
            self.logger.error(f"Command execution failed: {command}", extra={
                "run_id": run_id,
                "error": str(e),
                "command": command
            }, exc_info=True)
            
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Command execution failed: {str(e)}",
                "command": command
            }
            
    def _handle_run_skill(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle skill execution with enhanced logging"""
        skill_name = context.get("skill_name")
        payload = context.get("payload", {})
        task_id = context.get("task_id", f"task-{run_id}")
        
        if not skill_name:
            return {
                "status": "error",
                "run_id": run_id,
                "message": "skill_name is required"
            }
            
        if not self.skill_registry.is_skill_enabled(skill_name):
            return {
                "status": "error", 
                "run_id": run_id,
                "message": f"Skill '{skill_name}' is not enabled or registered"
            }
            
        try:
            result = self.manager.run_skill(skill_name, task_id, payload)
            
            return {
                "status": "success",
                "run_id": run_id,
                "skill_name": skill_name,
                "task_id": task_id,
                "result": result
            }
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "skill_name": skill_name,
                "message": str(e)
            }
            
    def _handle_check_email(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle email checking"""
        return self._handle_run_skill(run_id, {
            "skill_name": "sifter",
            "payload": {},
            "task_id": f"email-check-{run_id}"
        })
        
    def _handle_executive_summary(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle executive summary generation"""
        # Import here to avoid circular imports
        try:
            from executive_summary import generate_executive_summary
            from notifications import MarkdownFileNotifier
            
            summary = generate_executive_summary(self.manager, MarkdownFileNotifier())
            
            return {
                "status": "success",
                "run_id": run_id,
                "summary": summary,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to generate executive summary: {str(e)}"
            }
            
    def _handle_lead_generation(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle lead generation"""
        default_queries = [
            "Fractional CTO roles in Jacksonville",
            "Warehouse optimization consulting"
        ]
        
        return self._handle_run_skill(run_id, {
            "skill_name": "lead_scout",
            "payload": {"queries": context.get("queries", default_queries)},
            "task_id": f"lead-gen-{run_id}"
        })
        
    def _handle_get_timeline(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get unified timeline"""
        limit = context.get("limit", 100)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT event_type, event_id, event_source, event_context,
                           event_time, event_status, event_data, error_message
                    FROM unified_timeline 
                    ORDER BY event_time DESC 
                    LIMIT ?
                """, (limit,))
                
                timeline = [dict(zip([col[0] for col in cursor.description], row)) 
                           for row in cursor.fetchall()]
                
                return {
                    "status": "success",
                    "run_id": run_id,
                    "timeline": timeline,
                    "count": len(timeline)
                }
                
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to get timeline: {str(e)}"
            }
            
    def _handle_get_pending_actions(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get pending actions for review"""
        limit = context.get("limit", 50)
        
        try:
            actions = self.pending_actions.get_pending_actions(limit)
            
            return {
                "status": "success",
                "run_id": run_id,
                "pending_actions": actions,
                "count": len(actions)
            }
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to get pending actions: {str(e)}"
            }
            
    def _handle_approve_action(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Approve and execute pending action"""
        action_id = context.get("action_id")
        reviewed_by = context.get("reviewed_by", "user")
        
        if not action_id:
            return {
                "status": "error",
                "run_id": run_id,
                "message": "action_id is required"
            }
            
        try:
            result = self.pending_actions.approve_action(action_id, reviewed_by)
            
            # If approval was successful, execute the action
            if result.get("status") == "success":
                execution_result = self._execute_approved_action(
                    result["action_type"], 
                    result["payload"]
                )
                result["execution"] = execution_result
                
            result["run_id"] = run_id
            return result
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to approve action: {str(e)}"
            }
            
    def _handle_reject_action(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Reject pending action"""
        action_id = context.get("action_id")
        reviewed_by = context.get("reviewed_by", "user")
        
        if not action_id:
            return {
                "status": "error",
                "run_id": run_id,
                "message": "action_id is required"
            }
            
        try:
            success = self.pending_actions.reject_action(action_id, reviewed_by)
            
            return {
                "status": "success" if success else "error",
                "run_id": run_id,
                "message": "Action rejected" if success else "Action not found or already processed",
                "action_id": action_id
            }
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to reject action: {str(e)}"
            }
            
    def _handle_run_scheduled_jobs(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Run due scheduled jobs"""
        try:
            due_jobs = self.scheduled_jobs.get_due_jobs()
            results = []
            
            for job in due_jobs:
                job_result = self._execute_scheduled_job(job)
                results.append(job_result)
                
                # Update job status
                self.scheduled_jobs.update_job_status(
                    job["job_id"],
                    job_result.get("status", "failed"),
                    job_result.get("error")
                )
                
            return {
                "status": "success",
                "run_id": run_id,
                "jobs_executed": len(results),
                "results": results
            }
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to run scheduled jobs: {str(e)}"
            }
            
    def _handle_list_skills(self, run_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """List available skills"""
        try:
            skills = self.skill_registry.get_enabled_skills()
            
            return {
                "status": "success",
                "run_id": run_id,
                "skills": skills,
                "count": len(skills)
            }
            
        except Exception as e:
            return {
                "status": "error",
                "run_id": run_id,
                "message": f"Failed to list skills: {str(e)}"
            }
            
    def _execute_approved_action(self, action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an approved action"""
        # This would contain the actual execution logic for different action types
        # For now, return a placeholder
        return {
            "status": "executed",
            "action_type": action_type,
            "executed_at": datetime.now(timezone.utc).isoformat()
        }
        
    def _execute_scheduled_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a scheduled job"""
        try:
            job_type = job["job_type"]
            target = job["target"]
            payload = json.loads(job["payload_json"])
            
            if job_type == "skill":
                result = self.manager.run_skill(target, f"scheduled-{job['job_id']}", payload)
                return {
                    "status": "success",
                    "job_id": job["job_id"],
                    "result": result
                }
            else:
                return {
                    "status": "error",
                    "job_id": job["job_id"],
                    "error": f"Unknown job type: {job_type}"
                }
                
        except Exception as e:
            return {
                "status": "error",
                "job_id": job["job_id"],
                "error": str(e)
            }


# Global orchestrator instance (singleton pattern for now)
_orchestrator_instance: Optional[VictorOrchestrator] = None


def get_orchestrator(db_path: str = "khursheed.db") -> VictorOrchestrator:
    """Get global orchestrator instance"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = VictorOrchestrator(db_path)
    return _orchestrator_instance


def execute_command(command: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """Global command execution entry point"""
    return get_orchestrator().execute_command(command, context)