"""
Khursheed Bridge - Thin wrapper using Victor orchestrator

This module provides a bridge to call Victor orchestrator while maintaining
the Enaam API interface for backward compatibility.
"""

import logging
import time
from typing import Any, Dict, Optional

# Import Victor adapter for thin bridge layer
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from enaam_victor_adapter import get_enaam_adapter

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
    Thin bridge to Victor orchestrator maintaining Enaam API compatibility.
    """
    
    def __init__(self, logger: Optional[EnaamLogger] = None, email_config: Optional[EmailConfig] = None) -> None:
        """
        Initialize KhursheedBridge with Victor adapter.
        
        Args:
            logger: Logger instance. If None, uses adapter's logger.
            email_config: Email configuration (maintained for compatibility).
        """
        self._adapter = get_enaam_adapter()
        self._logger = logger or self._adapter.logger
        self._error_logger = get_error_logger('khursheed_bridge')
        self._email_config = email_config or get_config().email
    
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
        """Generate weekly digest via Victor adapter"""
        return self._adapter.weekly_digest()
    
    def email_summary(self) -> dict[str, Any]:
        """Check emails via Victor adapter"""
        return self._adapter.email_summary()
    
    def weekly_monday_9am_digest(self) -> dict[str, Any]:
        """Monday 9 AM weekly digest via Victor adapter"""
        return self._adapter.weekly_monday_9am_digest()
    
    def lead_generation_run(self) -> dict[str, Any]:
        """Lead generation automation via Victor adapter"""
        return self._adapter.lead_generation_run()
    
    def email_triage_run(self) -> dict[str, Any]:
        """Email triage automation via Victor adapter"""
        return self._adapter.email_triage_run()
    
    def lead_scan(self) -> dict[str, Any]:
        """Lead scan via Victor adapter"""
        return self._adapter.lead_scan()
    
    def executive_summary(self) -> dict[str, Any]:
        """Executive summary via Victor adapter"""
        return self._adapter.executive_summary()
    
    def run_scheduled_tasks(self) -> dict[str, Any]:
        """Run scheduled tasks via Victor adapter"""
        return self._adapter.run_scheduled_tasks()
    
    # ENAAM STATE AND LOGGING FUNCTIONS
    
    def get_execution_logs(self, limit: int = 10) -> dict[str, Any]:
        """Get execution logs via Victor adapter"""
        return self._adapter.get_execution_logs(limit)