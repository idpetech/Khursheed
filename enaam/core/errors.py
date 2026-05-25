"""
Enaam Comprehensive Error System

A hierarchical error system providing:
- Clear error categorization and inheritance hierarchy
- Rich contextual information for debugging
- Consistent error codes for programmatic handling
- Error serialization for APIs
- Error recovery strategies
- Error aggregation for multiple failures

This system replaces the existing enaam/core/exceptions.py with a more comprehensive approach.
"""

import json
import time
import traceback
from enum import Enum
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class ErrorSeverity(Enum):
    """Error severity levels for classification and handling priority."""
    LOW = "low"           # Minor issues, warnings
    MEDIUM = "medium"     # Standard errors, recoverable issues  
    HIGH = "high"         # Serious errors, major functionality impacted
    CRITICAL = "critical" # System-threatening errors requiring immediate attention


class ErrorCategory(Enum):
    """High-level error categories for classification."""
    VALIDATION = "validation"         # Input/data validation failures
    CONFIGURATION = "configuration"   # System/app configuration issues
    DATABASE = "database"            # Data persistence errors
    EXTERNAL_SERVICE = "external"     # Third-party service failures
    AUTHENTICATION = "authentication" # Auth/authz failures
    BUSINESS_LOGIC = "business"       # Domain/business rule violations
    SYSTEM = "system"                # Infrastructure/runtime errors
    MCP = "mcp"                      # Model Context Protocol errors
    INTEGRATION = "integration"      # External system integration errors


class ErrorRecoveryStrategy(Enum):
    """Suggested recovery strategies for different error types."""
    NONE = "none"                    # No automatic recovery possible
    RETRY = "retry"                  # Retry the operation
    FALLBACK = "fallback"            # Use alternative approach
    SKIP = "skip"                    # Skip this operation and continue
    RELOAD = "reload"                # Reload configuration/data
    RESTART = "restart"              # Restart component/service
    MANUAL = "manual"                # Manual intervention required


class EnaamBaseError(Exception):
    """
    Base class for all Enaam errors.
    
    Provides comprehensive error information including:
    - Hierarchical error codes
    - Rich contextual data
    - Error severity and category classification
    - Suggested recovery strategies
    - Automatic error tracking and correlation
    """
    
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        category: Optional[ErrorCategory] = None,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        recovery_strategy: ErrorRecoveryStrategy = ErrorRecoveryStrategy.NONE,
        retry_count: int = 0,
        max_retries: int = 0,
        correlation_id: Optional[str] = None,
        user_message: Optional[str] = None,
        technical_details: Optional[str] = None,
    ):
        """
        Initialize base error with comprehensive information.
        
        Args:
            message: Primary error message (for developers)
            code: Machine-readable error code
            category: Error category for classification
            severity: Error severity level
            context: Additional contextual information
            cause: Original exception that triggered this error
            recovery_strategy: Suggested recovery approach
            retry_count: Current retry attempt number
            max_retries: Maximum retry attempts allowed
            correlation_id: ID to correlate related errors
            user_message: User-friendly error message
            technical_details: Additional technical information
        """
        super().__init__(message)
        
        # Core error information
        self.message = message
        self.code = code or self._generate_error_code()
        self.category = category or self._get_default_category()
        self.severity = severity
        
        # Contextual information
        self.context = context or {}
        self.cause = cause
        self.user_message = user_message or self._generate_user_message()
        self.technical_details = technical_details
        
        # Recovery information
        self.recovery_strategy = recovery_strategy
        self.retry_count = retry_count
        self.max_retries = max_retries
        
        # Tracking information
        self.correlation_id = correlation_id or self._generate_correlation_id()
        self.timestamp = time.time()
        self.stack_trace = self._capture_stack_trace()
        
        # Add cause chain to context
        if cause:
            self.context["cause"] = {
                "type": type(cause).__name__,
                "message": str(cause),
                "details": getattr(cause, "details", {}) if hasattr(cause, "details") else {}
            }
    
    def _generate_error_code(self) -> str:
        """Generate error code based on class name."""
        class_name = self.__class__.__name__
        if class_name.endswith("Error"):
            class_name = class_name[:-5]  # Remove "Error" suffix
        return class_name.upper().replace("ENAAM", "")
    
    def _get_default_category(self) -> ErrorCategory:
        """Get default category based on error type."""
        return ErrorCategory.SYSTEM
    
    def _generate_user_message(self) -> str:
        """Generate user-friendly error message."""
        if self.severity == ErrorSeverity.CRITICAL:
            return "A critical system error occurred. Please contact support."
        elif self.severity == ErrorSeverity.HIGH:
            return "An error occurred while processing your request. Please try again."
        else:
            return "A minor issue was encountered. The system is attempting to recover."
    
    def _generate_correlation_id(self) -> str:
        """Generate unique correlation ID for error tracking."""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def _capture_stack_trace(self) -> str:
        """Capture stack trace for debugging."""
        return traceback.format_exc()
    
    def can_retry(self) -> bool:
        """Check if this error can be retried."""
        return (self.recovery_strategy == ErrorRecoveryStrategy.RETRY and 
                self.retry_count < self.max_retries)
    
    def should_escalate(self) -> bool:
        """Check if this error should be escalated."""
        return self.severity in {ErrorSeverity.HIGH, ErrorSeverity.CRITICAL}
    
    def is_transient(self) -> bool:
        """Check if this is likely a transient error."""
        return self.recovery_strategy in {ErrorRecoveryStrategy.RETRY, ErrorRecoveryStrategy.RELOAD}
    
    def get_retry_delay(self) -> int:
        """Get suggested retry delay in seconds."""
        if not self.can_retry():
            return 0
        # Exponential backoff: 2^retry_count seconds, capped at 60
        return min(2 ** self.retry_count, 60)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert error to dictionary for serialization.
        
        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "user_message": self.user_message,
                "category": self.category.value,
                "severity": self.severity.value,
                "recovery_strategy": self.recovery_strategy.value,
                "context": self.context,
                "correlation_id": self.correlation_id,
                "timestamp": self.timestamp,
                "retry_info": {
                    "can_retry": self.can_retry(),
                    "retry_count": self.retry_count,
                    "max_retries": self.max_retries,
                    "retry_delay": self.get_retry_delay()
                }
            }
        }
    
    def to_json(self) -> str:
        """Convert error to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def __str__(self) -> str:
        """String representation of the error."""
        parts = [f"{self.code}: {self.message}"]
        
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"Context: {context_str}")
        
        if self.correlation_id:
            parts.append(f"Correlation: {self.correlation_id}")
            
        return " | ".join(parts)
    
    def __repr__(self) -> str:
        """Detailed representation of the error."""
        return (f"{self.__class__.__name__}("
                f"code='{self.code}', "
                f"message='{self.message}', "
                f"severity={self.severity.value}, "
                f"category={self.category.value})")


class EnaamValidationError(EnaamBaseError):
    """
    Input and data validation errors.
    
    Raised when data fails validation rules, required fields are missing,
    or input format is invalid.
    """
    
    def __init__(
        self,
        message: str,
        *,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        constraint: Optional[str] = None,
        validation_rule: Optional[str] = None,
        **kwargs
    ):
        # Build context from validation-specific parameters
        context = kwargs.get("context", {})
        if field:
            context["field"] = field
        if value is not None:
            context["value"] = str(value)[:200]  # Truncate long values
        if constraint:
            context["constraint"] = constraint
        if validation_rule:
            context["validation_rule"] = validation_rule
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.VALIDATION
        kwargs.setdefault("severity", ErrorSeverity.LOW)
        kwargs.setdefault("code", "VALIDATION_FAILED")
        
        super().__init__(message, **kwargs)
    
    def _generate_user_message(self) -> str:
        """Generate user-friendly validation error message."""
        field = self.context.get("field")
        if field:
            return f"Please check the value for '{field}' and try again."
        return "Please check your input and try again."


class EnaamConfigurationError(EnaamBaseError):
    """
    System and application configuration errors.
    
    Raised when configuration is missing, invalid, or incompatible.
    """
    
    def __init__(
        self,
        message: str,
        *,
        config_key: Optional[str] = None,
        config_file: Optional[str] = None,
        expected_value: Optional[Any] = None,
        actual_value: Optional[Any] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if config_key:
            context["config_key"] = config_key
        if config_file:
            context["config_file"] = config_file
        if expected_value is not None:
            context["expected"] = str(expected_value)
        if actual_value is not None:
            context["actual"] = str(actual_value)
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.CONFIGURATION
        kwargs.setdefault("severity", ErrorSeverity.HIGH)
        kwargs.setdefault("code", "CONFIGURATION_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.RELOAD)
        
        super().__init__(message, **kwargs)


class EnaamDatabaseError(EnaamBaseError):
    """
    Database and data persistence errors.
    
    Raised when database operations fail due to connectivity issues,
    constraint violations, or other persistence problems.
    """
    
    def __init__(
        self,
        message: str,
        *,
        operation: Optional[str] = None,
        table: Optional[str] = None,
        query: Optional[str] = None,
        connection_id: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if operation:
            context["operation"] = operation
        if table:
            context["table"] = table
        if query:
            # Sanitize query for logging (remove potential sensitive data)
            sanitized_query = query.replace("'", "").replace('"', "")[:100]
            context["query"] = sanitized_query
        if connection_id:
            context["connection_id"] = connection_id
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.DATABASE
        kwargs.setdefault("severity", ErrorSeverity.HIGH)
        kwargs.setdefault("code", "DATABASE_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.RETRY)
        kwargs.setdefault("max_retries", 3)
        
        super().__init__(message, **kwargs)


class EnaamExternalServiceError(EnaamBaseError):
    """
    External service and API errors.
    
    Raised when external services fail or return unexpected responses.
    """
    
    def __init__(
        self,
        message: str,
        *,
        service_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        request_id: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if service_name:
            context["service"] = service_name
        if endpoint:
            context["endpoint"] = endpoint
        if status_code:
            context["status_code"] = status_code
        if response_body:
            # Truncate and sanitize response body
            context["response_preview"] = response_body[:200]
        if request_id:
            context["external_request_id"] = request_id
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.EXTERNAL_SERVICE
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        kwargs.setdefault("code", "EXTERNAL_SERVICE_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.RETRY)
        kwargs.setdefault("max_retries", 2)
        
        super().__init__(message, **kwargs)


class EnaamAuthenticationError(EnaamBaseError):
    """
    Authentication and authorization errors.
    
    Raised when authentication fails or access is denied.
    """
    
    def __init__(
        self,
        message: str,
        *,
        auth_method: Optional[str] = None,
        user_id: Optional[str] = None,
        resource: Optional[str] = None,
        required_permission: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if auth_method:
            context["auth_method"] = auth_method
        if user_id:
            context["user_id"] = user_id
        if resource:
            context["resource"] = resource
        if required_permission:
            context["required_permission"] = required_permission
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.AUTHENTICATION
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        kwargs.setdefault("code", "AUTHENTICATION_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.MANUAL)
        
        super().__init__(message, **kwargs)
    
    def _generate_user_message(self) -> str:
        """Generate user-friendly auth error message."""
        return "Authentication failed. Please check your credentials and try again."


class EnaamBusinessLogicError(EnaamBaseError):
    """
    Business logic and domain rule errors.
    
    Raised when operations violate business rules or domain constraints.
    """
    
    def __init__(
        self,
        message: str,
        *,
        business_rule: Optional[str] = None,
        domain_context: Optional[Dict[str, Any]] = None,
        suggestion: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if business_rule:
            context["business_rule"] = business_rule
        if domain_context:
            context["domain_context"] = domain_context
        if suggestion:
            context["suggestion"] = suggestion
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.BUSINESS_LOGIC
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        kwargs.setdefault("code", "BUSINESS_RULE_VIOLATION")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.MANUAL)
        
        super().__init__(message, **kwargs)


class EnaamSystemError(EnaamBaseError):
    """
    System-level infrastructure errors.
    
    Raised when system resources are unavailable or infrastructure fails.
    """
    
    def __init__(
        self,
        message: str,
        *,
        component: Optional[str] = None,
        resource: Optional[str] = None,
        system_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if component:
            context["component"] = component
        if resource:
            context["resource"] = resource
        if system_info:
            context["system_info"] = system_info
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.SYSTEM
        kwargs.setdefault("severity", ErrorSeverity.HIGH)
        kwargs.setdefault("code", "SYSTEM_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.RESTART)
        
        super().__init__(message, **kwargs)


class EnaamMCPError(EnaamBaseError):
    """
    Model Context Protocol specific errors.
    
    Raised when MCP operations fail due to protocol issues,
    invalid requests, or server problems.
    """
    
    def __init__(
        self,
        message: str,
        *,
        method: Optional[str] = None,
        request_id: Optional[str] = None,
        mcp_version: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if method:
            context["mcp_method"] = method
        if request_id:
            context["mcp_request_id"] = request_id
        if mcp_version:
            context["mcp_version"] = mcp_version
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.MCP
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        kwargs.setdefault("code", "MCP_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.RETRY)
        kwargs.setdefault("max_retries", 2)
        
        super().__init__(message, **kwargs)


class EnaamIntegrationError(EnaamBaseError):
    """
    External system integration errors.
    
    Raised when integration with external systems (like Khursheed) fails.
    """
    
    def __init__(
        self,
        message: str,
        *,
        integration_name: Optional[str] = None,
        operation: Optional[str] = None,
        external_error: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.get("context", {})
        if integration_name:
            context["integration"] = integration_name
        if operation:
            context["operation"] = operation
        if external_error:
            context["external_error"] = external_error
        
        kwargs["context"] = context
        kwargs["category"] = ErrorCategory.INTEGRATION
        kwargs.setdefault("severity", ErrorSeverity.MEDIUM)
        kwargs.setdefault("code", "INTEGRATION_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.FALLBACK)
        kwargs.setdefault("max_retries", 2)
        
        super().__init__(message, **kwargs)


class EnaamCriticalError(EnaamBaseError):
    """
    Critical system errors requiring immediate attention.
    
    Raised when the system encounters errors that threaten
    overall system stability or data integrity.
    """
    
    def __init__(self, message: str, **kwargs):
        kwargs["category"] = ErrorCategory.SYSTEM
        kwargs["severity"] = ErrorSeverity.CRITICAL
        kwargs.setdefault("code", "CRITICAL_ERROR")
        kwargs.setdefault("recovery_strategy", ErrorRecoveryStrategy.MANUAL)
        
        super().__init__(message, **kwargs)
    
    def _generate_user_message(self) -> str:
        """Generate user message for critical errors."""
        return "A critical system error has occurred. The system administrators have been notified."


class EnaamErrorCollection:
    """
    Collection for aggregating multiple related errors.
    
    Useful for validation scenarios where multiple errors
    can be collected and reported together.
    """
    
    def __init__(self, errors: Optional[List[EnaamBaseError]] = None):
        self.errors: List[EnaamBaseError] = errors or []
        self.correlation_id = self._generate_correlation_id()
    
    def _generate_correlation_id(self) -> str:
        """Generate correlation ID for the error collection."""
        import uuid
        return f"batch-{str(uuid.uuid4())[:8]}"
    
    def add(self, error: EnaamBaseError) -> None:
        """Add an error to the collection."""
        error.correlation_id = self.correlation_id
        self.errors.append(error)
    
    def has_errors(self) -> bool:
        """Check if collection has any errors."""
        return len(self.errors) > 0
    
    def has_critical(self) -> bool:
        """Check if collection has any critical errors."""
        return any(error.severity == ErrorSeverity.CRITICAL for error in self.errors)
    
    def get_highest_severity(self) -> ErrorSeverity:
        """Get the highest severity level in the collection."""
        if not self.errors:
            return ErrorSeverity.LOW
        
        severity_order = [ErrorSeverity.LOW, ErrorSeverity.MEDIUM, ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]
        return max((error.severity for error in self.errors), 
                  key=lambda s: severity_order.index(s))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error collection to dictionary."""
        return {
            "error_collection": {
                "correlation_id": self.correlation_id,
                "error_count": len(self.errors),
                "highest_severity": self.get_highest_severity().value,
                "has_critical": self.has_critical(),
                "errors": [error.to_dict()["error"] for error in self.errors]
            }
        }
    
    def to_json(self) -> str:
        """Convert error collection to JSON."""
        return json.dumps(self.to_dict(), indent=2)


# Backward compatibility aliases
EnaamError = EnaamBaseError
ValidationError = EnaamValidationError 
ConfigurationError = EnaamConfigurationError
DatabaseError = EnaamDatabaseError
ExternalServiceError = EnaamExternalServiceError
AuthenticationError = EnaamAuthenticationError
BusinessLogicError = EnaamBusinessLogicError
SystemError = EnaamSystemError
MCPError = EnaamMCPError
KhursheedBridgeError = EnaamIntegrationError  # Alias for integration errors
RetryableError = EnaamExternalServiceError    # Most retryable errors are external service related
CriticalError = EnaamCriticalError


# Utility functions
def create_error_response(error: Union[EnaamBaseError, Exception], include_technical_details: bool = False) -> Dict[str, Any]:
    """
    Create standardized error response from any error.
    
    Args:
        error: Error to convert (EnaamBaseError or generic Exception)
        include_technical_details: Whether to include technical details
        
    Returns:
        Standardized error response dictionary
    """
    if isinstance(error, EnaamBaseError):
        response = error.to_dict()
        if include_technical_details and error.technical_details:
            response["error"]["technical_details"] = error.technical_details
        return response
    else:
        # Convert generic exception to EnaamSystemError
        enaam_error = EnaamSystemError(
            f"Unexpected error: {str(error)}",
            cause=error,
            technical_details=traceback.format_exc() if include_technical_details else None
        )
        return enaam_error.to_dict()


def sanitize_error_message(message: str) -> str:
    """
    Sanitize error message by removing sensitive information.
    
    Args:
        message: Raw error message
        
    Returns:
        Sanitized error message safe for external consumption
    """
    import re
    
    # Remove file paths
    message = re.sub(r'/[^\s]+', '<path>', message)
    
    # Remove potential credentials
    patterns = [
        (r'password[=:]\s*[^\s]+', 'password=<hidden>'),
        (r'token[=:]\s*[^\s]+', 'token=<hidden>'),
        (r'key[=:]\s*[^\s]+', 'key=<hidden>'),
        (r'secret[=:]\s*[^\s]+', 'secret=<hidden>'),
        (r'auth[=:]\s*[^\s]+', 'auth=<hidden>'),
    ]
    
    for pattern, replacement in patterns:
        message = re.sub(pattern, replacement, message, flags=re.IGNORECASE)
    
    return message


def wrap_exception(func):
    """
    Decorator to wrap function exceptions in appropriate Enaam errors.
    
    Automatically converts generic exceptions to Enaam error types
    based on the exception type and context.
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except EnaamBaseError:
            # Re-raise Enaam errors as-is
            raise
        except ValueError as e:
            raise EnaamValidationError(f"Validation error in {func.__name__}: {str(e)}", cause=e)
        except (ConnectionError, TimeoutError) as e:
            raise EnaamExternalServiceError(f"Service error in {func.__name__}: {str(e)}", cause=e)
        except PermissionError as e:
            raise EnaamAuthenticationError(f"Permission error in {func.__name__}: {str(e)}", cause=e)
        except Exception as e:
            raise EnaamSystemError(f"Unexpected error in {func.__name__}: {str(e)}", cause=e)
    
    return wrapper