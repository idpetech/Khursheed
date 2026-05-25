"""
Enaam Exception Hierarchy - Backward Compatibility Layer

This module provides backward compatibility with the old exception system
while leveraging the new comprehensive error system in core/errors.py.

NEW CODE SHOULD USE: enaam.core.errors module
THIS MODULE: Maintains backward compatibility only
"""

import logging
from typing import Any, Dict, Optional

# Import new error system
from .errors import (
    EnaamBaseError,
    EnaamValidationError,
    EnaamConfigurationError, 
    EnaamDatabaseError,
    EnaamExternalServiceError,
    EnaamAuthenticationError,
    EnaamBusinessLogicError,
    EnaamSystemError,
    EnaamMCPError,
    EnaamIntegrationError,
    EnaamCriticalError,
    ErrorSeverity,
    ErrorCategory,
    create_error_response as new_create_error_response,
    sanitize_error_message as new_sanitize_error_message,
)

# Import new error sanitization system
from .error_sanitizer import (
    ErrorSanitizer,
    SafeErrorLogger,
    ErrorSensitivityLevel,
    ErrorCategory as SanitizerErrorCategory,
    create_error_sanitizer,
    create_safe_error_logger,
)

# For backward compatibility - re-export new system with old names
from typing import Tuple


# Backward compatibility - keep old ConfigurationError for legacy imports
class ConfigurationError(EnaamConfigurationError):
    """
    DEPRECATED: Use EnaamConfigurationError from enaam.core.errors instead.
    
    Legacy configuration error class maintained for backward compatibility.
    """
    
    def __init__(self, message: str, config_key: Optional[str] = None):
        super().__init__(message, config_key=config_key)


# Use new base error class
class EnaamError(EnaamBaseError):
    """
    DEPRECATED: Use EnaamBaseError from enaam.core.errors instead.
    
    Legacy base error class maintained for backward compatibility.
    Maps old-style constructor to new comprehensive error system.
    """
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        # Map old parameters to new system
        super().__init__(
            message,
            code=error_code,
            context=details,
            cause=cause
        )
        
        # Keep old attributes for backward compatibility
        self.error_code = self.code
        self.details = self.context
    
    def to_dict(self) -> Dict[str, Any]:
        """Backward compatible dictionary representation."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details
        }


# Remove duplicate - already defined above for backward compatibility


class DatabaseError(EnaamDatabaseError):
    """
    DEPRECATED: Use EnaamDatabaseError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, operation: Optional[str] = None, table: Optional[str] = None, **kwargs):
        # Extract old-style details
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(
            message,
            operation=operation,
            table=table,
            context=details,
            cause=cause
        )
        
        # Maintain backward compatibility attributes
        self.error_code = self.code
        self.details = self.context


class KhursheedBridgeError(EnaamIntegrationError):
    """
    DEPRECATED: Use EnaamIntegrationError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, skill_name: Optional[str] = None, operation: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        if skill_name:
            details['skill_name'] = skill_name
        
        super().__init__(
            message,
            integration_name="khursheed",
            operation=operation,
            context=details,
            cause=cause
        )


class MCPError(EnaamMCPError):
    """
    DEPRECATED: Use EnaamMCPError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, method: Optional[str] = None, request_id: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(
            message,
            method=method,
            request_id=request_id,
            context=details,
            cause=cause
        )
        
        # Maintain backward compatibility attributes
        self.error_code = self.code
        self.details = self.context


class ValidationError(EnaamValidationError):
    """
    DEPRECATED: Use EnaamValidationError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, field: Optional[str] = None, value: Optional[Any] = None, constraint: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(
            message,
            field=field,
            value=value,
            constraint=constraint,
            context=details,
            cause=cause
        )
        
        # Maintain backward compatibility attributes
        self.error_code = self.code
        self.details = self.context


class AuthenticationError(EnaamAuthenticationError):
    """
    DEPRECATED: Use EnaamAuthenticationError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(message, context=details, cause=cause)
        
        # Maintain backward compatibility attributes
        self.error_code = self.code
        self.details = self.context


class ExternalServiceError(EnaamExternalServiceError):
    """
    DEPRECATED: Use EnaamExternalServiceError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, service: Optional[str] = None, status_code: Optional[int] = None, response_body: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(
            message,
            service_name=service,
            status_code=status_code,
            response_body=response_body,
            context=details,
            cause=cause
        )


class BusinessLogicError(EnaamBusinessLogicError):
    """
    DEPRECATED: Use EnaamBusinessLogicError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, rule: Optional[str] = None, context: Optional[Dict[str, Any]] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(
            message,
            business_rule=rule,
            domain_context=context,
            context=details,
            cause=cause
        )


class RetryableError(EnaamExternalServiceError):
    """
    DEPRECATED: Use appropriate error type with retry strategy from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, retry_after: Optional[int] = None, max_retries: Optional[int] = None, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        if retry_after:
            details['retry_after_seconds'] = retry_after
        
        # Use external service error with retry strategy
        from .errors import ErrorRecoveryStrategy
        super().__init__(
            message,
            context=details,
            cause=cause,
            recovery_strategy=ErrorRecoveryStrategy.RETRY,
            max_retries=max_retries or 3
        )


class CriticalError(EnaamCriticalError):
    """
    DEPRECATED: Use EnaamCriticalError from enaam.core.errors instead.
    """
    
    def __init__(self, message: str, **kwargs):
        details = kwargs.pop('details', {})
        cause = kwargs.pop('cause', None)
        
        super().__init__(message, context=details, cause=cause)


# Backward compatibility for utility functions
def sanitize_error_message(message: str) -> str:
    """
    DEPRECATED: Use sanitize_error_message from enaam.core.errors instead.
    """
    return new_sanitize_error_message(message)


def create_error_response(error, include_details: bool = True) -> Dict[str, Any]:
    """
    DEPRECATED: Use create_error_response from enaam.core.errors instead.
    
    Maintains backward compatibility for old error response format.
    """
    if hasattr(error, 'to_dict'):
        # New error system
        return new_create_error_response(error, include_technical_details=include_details)
    else:
        # Legacy error handling
        response = {
            "status": "error",
            "error": {
                "code": getattr(error, 'error_code', 'UNKNOWN_ERROR'),
                "message": sanitize_error_message(str(error))
            }
        }
        
        if include_details and hasattr(error, 'details'):
            response["error"]["details"] = error.details
        
        return response


# NEW SAFE ERROR RESPONSE SYSTEM
# Use these functions for all external error responses to prevent information leakage

def create_safe_error_response(error: Exception, context: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Create a safe error response for external clients with full internal logging.
    
    This function:
    1. Logs full error details internally with sanitization
    2. Returns a safe, sanitized error response for external clients
    3. Provides correlation ID for error tracking
    
    Args:
        error: The exception that occurred
        context: Additional context about the error
        
    Returns:
        Tuple of (correlation_id, safe_error_response)
    """
    import logging
    
    # Get logger for internal logging
    logger = logging.getLogger('enaam.errors')
    
    # Create sanitizer and safe logger
    sanitizer = create_error_sanitizer()
    safe_logger = create_safe_error_logger(logger)
    
    # Log internally and get sanitized response
    correlation_id, client_response = safe_logger.log_and_sanitize(error, context)
    
    return correlation_id, client_response


def safe_handle_external_error(func):
    """
    Decorator for external-facing functions to ensure safe error handling.
    
    This decorator:
    1. Catches all exceptions from the decorated function
    2. Logs full details internally
    3. Returns safe error responses to external callers
    4. Prevents information leakage
    
    Usage:
        @safe_handle_external_error
        def my_api_endpoint(request):
            # Implementation that might raise exceptions
            return success_response
    """
    import functools
    import logging
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Create safe error response
            correlation_id, safe_response = create_safe_error_response(
                e, 
                context={
                    'function': func.__name__,
                    'args_count': len(args),
                    'kwargs_keys': list(kwargs.keys())
                }
            )
            
            # Return safe response in standard format
            return {
                'status': 'error',
                'correlation_id': correlation_id,
                **safe_response
            }
    
    return wrapper


def log_error_safely(error: Exception, logger: logging.Logger, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Log an error safely with automatic sanitization.
    
    Args:
        error: The exception to log
        logger: Logger instance to use
        context: Additional context information
        
    Returns:
        Correlation ID for error tracking
    """
    safe_logger = create_safe_error_logger(logger)
    return safe_logger.log_error(error, context=context)


def sanitize_error_for_client(error: Exception, error_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Sanitize error for external client consumption.
    
    Args:
        error: The exception that occurred
        error_id: Optional error ID for correlation
        
    Returns:
        Sanitized error response safe for external clients
    """
    sanitizer = create_error_sanitizer()
    return sanitizer.sanitize_error_for_client(error, error_id)


def get_safe_error_message(error: Exception) -> str:
    """
    Get a safe error message for external display.
    
    Args:
        error: The exception to get message for
        
    Returns:
        Safe error message with no internal details
    """
    sanitizer = create_error_sanitizer()
    response = sanitizer.sanitize_error_for_client(error)
    return response.get('error', {}).get('message', 'An error occurred')