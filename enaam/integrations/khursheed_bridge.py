"""
Khursheed Bridge - Wrapper for existing Khursheed functionality

This module provides a bridge to call existing Khursheed workflows
without modifying the original implementation.
"""

import logging
import os
import time
from typing import Any, Dict, Optional

# Import legacy modules through proper package structure
from ..legacy import (
    generate_executive_summary,
    Manager,
    CompositeNotifier,
    EmailNotifier, 
    MarkdownFileNotifier,
    EchoSkill,
    LeadScoutSkill,
    SifterSkill,
    TimestampSkill,
)

from ..core.container import resolve_optional
from ..core.error_handler import (
    ErrorContext,
    get_error_logger,
    handle_bridge_errors,
    log_and_suppress,
)
from ..core.exceptions import (
    KhursheedBridgeError,
    create_safe_error_response,
    log_error_safely,
    safe_handle_external_error
)

# Import Enaam logger and dependency injection
from ..core.logging import EnaamLogger

# Import enums and constants
from ..core.enums import (
    ResponseStatus,
    SourceType,
    TaskNames,
    DefaultQueries,
    DataFields,
    EnvironmentKeys,
    FileNames,
    SkillName,
)
from ..core.constants import (
    DefaultValues,
    TaskConstants,
)
from ..core.config_loader import get_config, EmailConfig


class KhursheedBridge:
    """
    Bridge to existing Khursheed functionality.
    
    Uses dependency injection for external dependencies to eliminate
    global state and improve testability.
    """
    
    def __init__(self, logger: Optional[EnaamLogger] = None, email_config: Optional[EmailConfig] = None) -> None:
        """
        Initialize KhursheedBridge with dependency injection.
        
        Args:
            logger: Logger instance. If None, resolves from container.
            email_config: Email configuration. If None, loads from global config.
        """
        self._manager = None
        self._logger = logger or resolve_optional(EnaamLogger) or self._create_fallback_logger()
        self._error_logger = get_error_logger('khursheed_bridge')
        self._email_config = email_config or get_config().email
        self._initialize_manager()
    
    def _create_fallback_logger(self) -> EnaamLogger:
        """Create fallback logger when container resolution fails."""
        from ..core.logging import create_logger
        return create_logger()
    
    def _initialize_manager(self) -> None:
        """Initialize the Khursheed manager with all available skills"""
        self._manager = Manager()
        
        # Register core skills
        skills_to_register = [
            EchoSkill(),
            LeadScoutSkill(), 
            SifterSkill(),
            TimestampSkill()
        ]
        
        # Try to add new skills if available
        try:
            from ..legacy import CalculatorSkill, WeatherSkill, FileAnalyzerSkill
            skills_to_register.extend([
                CalculatorSkill(),
                WeatherSkill(),
                FileAnalyzerSkill()
            ])
        except ImportError:
            # New skills not available, continue with core skills
            pass
        
        self._manager.register_many(skills_to_register)
    
    @log_and_suppress(default_return=None, log_level=logging.WARNING)
    def _log_execution(self, function_name: str, input_data: Dict[str, Any], response: Dict[str, Any], execution_time_ms: int) -> None:
        """Log function execution to Enaam logger"""
        self._logger.log_execution(
            function_name=function_name,
            source=response.get("source", "khursheed"),
            status=response.get("status", "unknown"),
            input_data=input_data,
            output_data=response,
            execution_time_ms=execution_time_ms,
            error_message=response.get("data", {}).get("error") if response.get("status") == "error" else None
        )
    
    def _execute_with_logging(self, function_name: str, func, input_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a function with logging wrapper.
        
        This method provides structured error handling and logging for bridge operations.
        On success, returns the function result. On error, logs the error and returns 
        an error response structure for backward compatibility with the existing API.
        """
        with ErrorContext(f"Bridge operation: {function_name}", self._error_logger):
            start_time = time.time()
            try:
                result = func()
                execution_time_ms = int((time.time() - start_time) * 1000)
                self._log_execution(function_name, input_data or {}, result, execution_time_ms)
                return result
            except Exception as e:
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # Log safely with full context and get correlation ID
                correlation_id = log_error_safely(
                    e, 
                    self._error_logger, 
                    context={
                        'operation': function_name,
                        'execution_time_ms': execution_time_ms,
                        'input_data_keys': list((input_data or {}).keys()),
                        'component': 'khursheed_bridge'
                    }
                )
                
                # Create safe error response that doesn't leak internal details
                _, safe_response = create_safe_error_response(
                    e, 
                    context={'bridge_operation': function_name}
                )
                
                # Create error response for backward compatibility with safe message
                error_response = {
                    "status": "error",
                    "source": "khursheed",
                    "action": function_name,
                    "data": {
                        "error": safe_response.get('error', {}).get('message', 'Operation failed'),
                        "correlation_id": correlation_id
                    },
                    "next_steps": ["Check system configuration", "Review error logs", f"Reference error ID: {correlation_id}"]
                }
                
                self._log_execution(function_name, input_data or {}, error_response, execution_time_ms)
                
                # Return safe error response instead of raising for bridge operations
                # This maintains backward compatibility with existing callers
                return error_response
    
    def weekly_digest(self) -> dict[str, Any]:
        """Generate weekly digest using existing weekly_summary.py logic"""
        def _execute():
            # Use the same logic as weekly_summary.py but without email sending
            summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "weekly_digest",
                DataFields.DATA.value: {DataFields.SUMMARY.value: summary},
                DataFields.NEXT_STEPS.value: TaskConstants.WEEKLY_DIGEST_NEXT_STEPS
            }
        
        return self._execute_with_logging("weekly_digest", _execute)
    
    def email_summary(self) -> dict[str, Any]:
        """Check emails using existing sifter skill"""
        def _execute():
            # Run the sifter skill to check emails
            result = self._manager.run_skill(SkillName.SIFTER.value, TaskNames.ENAAM_EMAIL_CHECK.value, {})
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "email_summary", 
                DataFields.DATA.value: result,
                DataFields.NEXT_STEPS.value: TaskConstants.EMAIL_NEXT_STEPS
            }
        
        return self._execute_with_logging("email_summary", _execute)
    
    # NEW REQUIRED WRAPPER FUNCTIONS
    
    def weekly_monday_9am_digest(self) -> dict[str, Any]:
        """
        Monday 9 AM weekly digest - wraps the existing weekly_summary.py automation
        This mimics the exact cron job behavior but returns structured response
        """
        def _execute():
            # Check if email sending is configured
            if self._email_config.enabled:
                # Full weekly summary with email (like the cron job)
                notifier = CompositeNotifier(
                    MarkdownFileNotifier(),
                    EmailNotifier(
                        sender=self._email_config.sender,
                        password=self._email_config.password,
                        recipient=self._email_config.recipient
                    )
                )
                summary = generate_executive_summary(self._manager, notifier)
                
                return {
                    DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                    DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                    DataFields.ACTION.value: "weekly_monday_9am_digest",
                    DataFields.DATA.value: {
                        DataFields.SUMMARY.value: summary,
                        DataFields.EMAIL_SENT.value: True,
                        DataFields.RECIPIENT.value: self._email_config.recipient
                    },
                    DataFields.NEXT_STEPS.value: TaskConstants.WEEKLY_MONDAY_NEXT_STEPS
                }
            else:
                # Just generate summary without email
                summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
                
                return {
                    DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                    DataFields.SOURCE.value: SourceType.KHURSHEED.value, 
                    DataFields.ACTION.value: "weekly_monday_9am_digest",
                    DataFields.DATA.value: {
                        DataFields.SUMMARY.value: summary,
                        DataFields.EMAIL_SENT.value: False,
                        DataFields.NOTE.value: "Email credentials not configured"
                    },
                    DataFields.NEXT_STEPS.value: ["Configure email settings for full automation", "Review generated summary"]
                }
        
        return self._execute_with_logging("weekly_monday_9am_digest", _execute)
    
    def lead_generation_run(self) -> dict[str, Any]:
        """
        Lead generation automation - wraps the existing lead_scout skill execution
        This matches the task-003 from tasks.json with 3-day interval
        """
        def _execute():
            # Use the same payload as tasks.json task-003
            payload = {
                DataFields.QUERIES.value: TaskConstants.DEFAULT_LEAD_QUERIES
            }
            
            result = self._manager.run_skill(SkillName.LEAD_SCOUT.value, TaskNames.ENAAM_LEAD_GENERATION.value, payload)
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "lead_generation_run",
                DataFields.DATA.value: result,
                DataFields.NEXT_STEPS.value: TaskConstants.LEAD_GENERATION_NEXT_STEPS
            }
        
        return self._execute_with_logging("lead_generation_run", _execute, 
                                        {DataFields.QUERIES.value: TaskConstants.DEFAULT_LEAD_QUERIES})
    
    def email_triage_run(self) -> dict[str, Any]:
        """
        Email triage automation - wraps the existing sifter skill for full email processing
        This performs the complete email triage and expense extraction workflow
        """
        def _execute():
            # Run comprehensive email triage
            result = self._manager.run_skill(SkillName.SIFTER.value, TaskNames.ENAAM_EMAIL_TRIAGE.value, {})
            
            # Process the result to provide better summary
            data = result.copy()
            
            # Add triage summary if available
            if DataFields.EMAILS_PROCESSED.value in result:
                data[DataFields.TRIAGE_SUMMARY.value] = f"Processed {result.get(DataFields.EMAILS_PROCESSED.value, 0)} emails"
                
            if DataFields.EXPENSES_EXTRACTED.value in result:
                data[DataFields.EXPENSE_SUMMARY.value] = f"Extracted {result.get(DataFields.EXPENSES_EXTRACTED.value, 0)} expense items"
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value, 
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "email_triage_run",
                DataFields.DATA.value: data,
                DataFields.NEXT_STEPS.value: TaskConstants.EMAIL_TRIAGE_NEXT_STEPS
            }
        
        return self._execute_with_logging("email_triage_run", _execute)
    
    def lead_scan(self) -> dict[str, Any]:
        """Run lead discovery using existing lead_scout skill"""
        def _execute():
            # Default search queries from tasks.json
            payload = {
                DataFields.QUERIES.value: TaskConstants.DEFAULT_LEAD_QUERIES
            }
            
            result = self._manager.run_skill(SkillName.LEAD_SCOUT.value, TaskNames.ENAAM_LEAD_SCAN.value, payload)
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value, 
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "lead_scan",
                DataFields.DATA.value: result,
                DataFields.NEXT_STEPS.value: TaskConstants.LEAD_NEXT_STEPS
            }
        
        return self._execute_with_logging("lead_scan", _execute, 
                                        {DataFields.QUERIES.value: TaskConstants.DEFAULT_LEAD_QUERIES})
    
    def executive_summary(self) -> dict[str, Any]:
        """Generate executive summary using existing logic"""
        def _execute():
            summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                DataFields.SOURCE.value: SourceType.KHURSHEED.value,
                DataFields.ACTION.value: "executive_summary",
                DataFields.DATA.value: {DataFields.SUMMARY.value: summary},
                DataFields.NEXT_STEPS.value: TaskConstants.EXECUTIVE_SUMMARY_NEXT_STEPS
            }
        
        return self._execute_with_logging("executive_summary", _execute)
    
    def run_scheduled_tasks(self) -> dict[str, Any]:
        """Run all scheduled Khursheed tasks from tasks.json"""
        def _execute():
            tasks = self._manager.load_tasks(FileNames.TASKS_JSON.value)
            self._manager.run_tasks(tasks)
            
            return {
                DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
                DataFields.SOURCE.value: SourceType.KHURSHEED.value, 
                DataFields.ACTION.value: "run_scheduled_tasks",
                DataFields.DATA.value: {DataFields.TASKS_EXECUTED.value: len(tasks)},
                DataFields.NEXT_STEPS.value: TaskConstants.SCHEDULED_TASKS_NEXT_STEPS
            }
        
        return self._execute_with_logging("run_scheduled_tasks", _execute, {"tasks_file": FileNames.TASKS_JSON.value})
    
    # ENAAM STATE AND LOGGING FUNCTIONS
    
    @handle_bridge_errors()
    def get_execution_logs(self, limit: int = 10) -> dict[str, Any]:
        """Get recent Enaam execution logs"""
        recent_runs = self._logger.get_recent_runs(limit)
        stats = self._logger.get_function_stats()
        
        return {
            DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
            DataFields.SOURCE.value: SourceType.ENAAM.value,
            DataFields.ACTION.value: "get_execution_logs",
            DataFields.DATA.value: {
                DataFields.RECENT_RUNS.value: recent_runs,
                DataFields.FUNCTION_STATS.value: stats,
                DataFields.TOTAL_RUNS.value: len(recent_runs)
            },
            DataFields.NEXT_STEPS.value: TaskConstants.EXECUTION_LOGS_NEXT_STEPS
        }