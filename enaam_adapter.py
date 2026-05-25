"""
Enaam Adapter
Thin adapter layer connecting Enaam MCP to Enaam orchestrator
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from enaam_orchestrator import execute_command, get_orchestrator
from enaam.core.logging import EnaamLogger
from enaam.core.enums import ResponseStatus, SourceType, DataFields


class EnaamAdapter:
    """
    Thin adapter connecting Enaam MCP layer to Enaam orchestrator
    Maintains Enaam logging while using unified orchestrator as execution engine
    """
    
    def __init__(self, logger: Optional[EnaamLogger] = None):
        self.logger = logger or self._create_fallback_logger()
        self.orchestrator = get_orchestrator()
        
    def _create_fallback_logger(self) -> EnaamLogger:
        """Create fallback logger if none provided"""
        from enaam.core.logging import create_logger
        return create_logger()
    
    def _log_execution(
        self, 
        function_name: str, 
        input_data: Dict[str, Any], 
        result: Dict[str, Any], 
        execution_time_ms: int
    ) -> None:
        """Log execution to Enaam logger"""
        try:
            self.logger.log_execution(
                function_name=function_name,
                source=result.get("source", "victor"),
                status=result.get("status", "unknown"),
                input_data=input_data,
                output_data=result,
                execution_time_ms=execution_time_ms,
                error_message=result.get("message") if result.get("status") == "error" else None
            )
        except Exception as e:
            logging.warning(f"Failed to log execution: {e}")
    
    def _execute_with_logging(
        self, 
        function_name: str, 
        command: str, 
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Execute command through Victor with Enaam logging"""
        start_time = datetime.now(timezone.utc)
        
        try:
            result = execute_command(command, context)
            
            # Calculate execution time
            execution_time_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            
            # Convert orchestrator response to Enaam format
            enaam_result = self._convert_orchestrator_to_enaam_response(result, function_name)
            
            # Log execution
            self._log_execution(function_name, context or {}, enaam_result, execution_time_ms)
            
            return enaam_result
            
        except Exception as e:
            execution_time_ms = int(
                (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            )
            
            error_result = {
                DataFields.STATUS.value: ResponseStatus.ERROR.value,
                DataFields.SOURCE.value: SourceType.ENAAM.value,
                DataFields.ACTION.value: function_name,
                DataFields.DATA.value: {
                    "error": str(e),
                    "victor_command": command
                },
                "next_steps": ["Check system logs", "Verify Victor orchestrator status"]
            }
            
            self._log_execution(function_name, context or {}, error_result, execution_time_ms)
            
            return error_result
    
    def _convert_orchestrator_to_enaam_response(
        self, 
        orchestrator_result: Dict[str, Any], 
        function_name: str
    ) -> Dict[str, Any]:
        """Convert orchestrator response format to Enaam response format"""
        
        # Extract status
        status = ResponseStatus.SUCCESS.value if orchestrator_result.get("status") == "success" else ResponseStatus.ERROR.value
        
        # Build Enaam-style response
        enaam_response = {
            DataFields.STATUS.value: status,
            DataFields.SOURCE.value: SourceType.ENAAM.value,
            DataFields.ACTION.value: function_name,
            DataFields.DATA.value: {},
            "next_steps": []
        }
        
        # Map specific response data
        if status == ResponseStatus.SUCCESS.value:
            if "summary" in orchestrator_result:
                enaam_response[DataFields.DATA.value][DataFields.SUMMARY.value] = orchestrator_result["summary"]
                enaam_response["next_steps"] = ["Review generated summary", "Take action on key insights"]
                
            elif "timeline" in orchestrator_result:
                enaam_response[DataFields.DATA.value]["timeline"] = orchestrator_result["timeline"]
                enaam_response[DataFields.DATA.value]["count"] = orchestrator_result.get("count", 0)
                enaam_response["next_steps"] = ["Review recent activity", "Check for any failed operations"]
                
            elif "pending_actions" in orchestrator_result:
                enaam_response[DataFields.DATA.value]["pending_actions"] = orchestrator_result["pending_actions"]
                enaam_response[DataFields.DATA.value]["count"] = orchestrator_result.get("count", 0)
                enaam_response["next_steps"] = ["Review pending actions", "Approve or reject as needed"]
                
            elif "skills" in orchestrator_result:
                enaam_response[DataFields.DATA.value]["skills"] = orchestrator_result["skills"]
                enaam_response[DataFields.DATA.value]["count"] = orchestrator_result.get("count", 0)
                enaam_response["next_steps"] = ["Review available skills", "Test skills if needed"]
                
            elif "result" in orchestrator_result:
                # Skill execution result
                enaam_response[DataFields.DATA.value] = orchestrator_result["result"]
                enaam_response["next_steps"] = ["Review skill execution result"]
                
            else:
                # Generic success response
                enaam_response[DataFields.DATA.value] = orchestrator_result
                enaam_response["next_steps"] = ["Operation completed successfully"]
        else:
            # Error response
            enaam_response[DataFields.DATA.value] = {
                "error": orchestrator_result.get("message", "Unknown error"),
                "run_id": orchestrator_result.get("run_id")
            }
            enaam_response["next_steps"] = ["Check error logs", "Retry operation if appropriate"]
        
        return enaam_response
    
    # Bridge function adapters - thin wrappers that call Victor
    
    def weekly_digest(self) -> Dict[str, Any]:
        """Generate weekly digest via Victor"""
        return self._execute_with_logging("weekly_digest", "executive_summary")
    
    def email_summary(self) -> Dict[str, Any]:
        """Check emails via Victor"""
        return self._execute_with_logging("email_summary", "check_email")
    
    def weekly_monday_9am_digest(self) -> Dict[str, Any]:
        """Monday morning digest via Victor"""
        return self._execute_with_logging("weekly_monday_9am_digest", "executive_summary")
    
    def lead_generation_run(self) -> Dict[str, Any]:
        """Lead generation via Victor"""
        return self._execute_with_logging("lead_generation_run", "lead_generation")
    
    def email_triage_run(self) -> Dict[str, Any]:
        """Email triage via Victor"""
        return self._execute_with_logging("email_triage_run", "check_email")
    
    def lead_scan(self) -> Dict[str, Any]:
        """Lead scan via Victor"""
        return self._execute_with_logging("lead_scan", "lead_generation")
    
    def executive_summary(self) -> Dict[str, Any]:
        """Executive summary via Victor"""
        return self._execute_with_logging("executive_summary", "executive_summary")
    
    def run_scheduled_tasks(self) -> Dict[str, Any]:
        """Run scheduled tasks via Victor"""
        return self._execute_with_logging("run_scheduled_tasks", "run_scheduled_jobs")
    
    def get_execution_logs(self, limit: int = 10) -> Dict[str, Any]:
        """Get execution logs via Victor timeline"""
        return self._execute_with_logging(
            "get_execution_logs", 
            "get_timeline", 
            {"limit": limit}
        )
    
    def get_pending_actions(self, limit: int = 50) -> Dict[str, Any]:
        """Get pending actions via Victor"""
        return self._execute_with_logging(
            "get_pending_actions",
            "get_pending_actions", 
            {"limit": limit}
        )
    
    def approve_pending_action(self, action_id: str, reviewed_by: str = "enaam") -> Dict[str, Any]:
        """Approve pending action via Victor"""
        return self._execute_with_logging(
            "approve_pending_action",
            "approve_action",
            {"action_id": action_id, "reviewed_by": reviewed_by}
        )
    
    def reject_pending_action(self, action_id: str, reviewed_by: str = "enaam") -> Dict[str, Any]:
        """Reject pending action via Victor"""
        return self._execute_with_logging(
            "reject_pending_action", 
            "reject_action",
            {"action_id": action_id, "reviewed_by": reviewed_by}
        )
    
    def run_skill(self, skill_name: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run skill via Victor"""
        return self._execute_with_logging(
            "run_skill",
            "run_skill",
            {"skill_name": skill_name, "payload": payload or {}}
        )
    
    def list_skills(self) -> Dict[str, Any]:
        """List skills via Victor"""
        return self._execute_with_logging("list_skills", "list_skills")


# Create singleton adapter instance
_adapter_instance: Optional[EnaamAdapter] = None


def get_enaam_adapter() -> EnaamAdapter:
    """Get singleton Enaam adapter instance"""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = EnaamAdapter()
    return _adapter_instance