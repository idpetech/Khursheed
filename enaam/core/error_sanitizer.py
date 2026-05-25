"""
Error Message Sanitizer - Prevents information leakage in error responses

This module provides comprehensive error sanitization to ensure that:
1. Internal system details are not exposed to external callers
2. Full error details are logged internally for debugging
3. Safe, generic error messages are returned to clients
4. Sensitive information (paths, credentials, etc.) is stripped
"""

import logging
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

from .constants import ValidationMessages, RegexPatterns


class ErrorSensitivityLevel(Enum):
    """Classification of error sensitivity levels"""
    PUBLIC = "public"        # Safe to show to external users
    INTERNAL = "internal"    # Should only be logged internally
    SENSITIVE = "sensitive"  # Contains credentials/secrets
    SYSTEM = "system"        # System internals (paths, stack traces)


class ErrorCategory(Enum):
    """Categories of errors for appropriate response mapping"""
    VALIDATION = "validation"
    AUTHENTICATION = "authentication" 
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"
    CONFIGURATION = "configuration"
    DATABASE = "database"
    EXTERNAL_SERVICE = "external_service"


class ErrorSanitizer:
    """Comprehensive error message sanitizer for security and privacy"""
    
    def __init__(self):
        # Sensitive patterns to remove from error messages
        # Order matters - more specific patterns first
        self._sensitive_patterns = [
            # Credentials and tokens (before other patterns)
            (re.compile(RegexPatterns.PASSWORD_PATTERN, re.IGNORECASE), 
             RegexPatterns.PASSWORD_REPLACEMENT),
            (re.compile(RegexPatterns.TOKEN_PATTERN, re.IGNORECASE), 
             RegexPatterns.TOKEN_REPLACEMENT),
            (re.compile(RegexPatterns.KEY_PATTERN, re.IGNORECASE), 
             RegexPatterns.KEY_REPLACEMENT),
            (re.compile(RegexPatterns.SECRET_PATTERN, re.IGNORECASE), 
             RegexPatterns.SECRET_REPLACEMENT),
            (re.compile(RegexPatterns.AUTH_PATTERN, re.IGNORECASE), 
             RegexPatterns.AUTH_REPLACEMENT),
            
            # API keys and connection strings (specific patterns first)
            (re.compile(r'sk-[a-zA-Z0-9]{8,}', re.IGNORECASE), '<api_key>'),
            (re.compile(r'Bearer\s+[a-zA-Z0-9._-]+', re.IGNORECASE), 'Bearer <token>'),
            (re.compile(r'mysql://[^\s]+', re.IGNORECASE), 'mysql://<connection_string>'),
            (re.compile(r'postgresql://[^\s]+', re.IGNORECASE), 'postgresql://<connection_string>'),
            (re.compile(r'mongodb://[^\s]+', re.IGNORECASE), 'mongodb://<connection_string>'),
            
            # File paths (after connection strings)
            (re.compile(r'/[a-zA-Z0-9_/.-]+\.(py|json|log|db|conf|env)', re.IGNORECASE), 
             '<file_path>'),
            (re.compile(r'/[a-zA-Z0-9_/.-]+', re.IGNORECASE), 
             '<file_path>'),
            (re.compile(r'[A-Z]:\\[a-zA-Z0-9_\\.-]+', re.IGNORECASE), 
             '<file_path>'),
            
            # IP addresses and hostnames
            (re.compile(r'\\b(?:[0-9]{1,3}\\.){3}[0-9]{1,3}\\b'), '<ip_address>'),
            (re.compile(r'localhost:[0-9]+'), 'localhost:<port>'),
            
            # Database table/column names  
            (re.compile(r'table\\s+["\']?([a-zA-Z0-9_]+)["\']?', re.IGNORECASE), 'table <table_name>'),
            (re.compile(r'column\\s+["\']?([a-zA-Z0-9_]+)["\']?', re.IGNORECASE), 'column <column_name>'),
            
            # Python module paths
            (re.compile(r'\\b[a-zA-Z0-9_.]+\\.[a-zA-Z0-9_.]*[a-zA-Z0-9_]\\b'), '<module_path>'),
            
            # Memory addresses
            (re.compile(r'0x[a-fA-F0-9]+'), '<memory_address>'),
            
            # Temporary file names
            (re.compile(r'/tmp/[a-zA-Z0-9_.-]+'), '<temp_file>'),
            (re.compile(r'\\AppData\\\\[a-zA-Z0-9_\\\\.-]+', re.IGNORECASE), '<temp_file>'),
        ]
        
        # Keywords that indicate sensitive content
        self._sensitive_keywords = {
            'password', 'secret', 'key', 'token', 'credential', 'auth',
            'api_key', 'access_token', 'refresh_token', 'private_key',
            'certificate', 'cert', 'ssl', 'tls'
        }
        
        # Exception types that should never expose details
        self._sensitive_exception_types = {
            'PermissionError', 'FileNotFoundError', 'ConnectionError',
            'TimeoutError', 'DatabaseError', 'AuthenticationError'
        }
        
        # Safe error mappings for common issues
        self._safe_error_mappings = {
            # Validation errors
            ErrorCategory.VALIDATION: "Invalid request format or parameters",
            
            # Authentication/Authorization
            ErrorCategory.AUTHENTICATION: "Authentication failed",
            ErrorCategory.AUTHORIZATION: "Access denied", 
            
            # Resource errors
            ErrorCategory.NOT_FOUND: "Requested resource not found",
            ErrorCategory.RATE_LIMIT: ValidationMessages.RATE_LIMIT_EXCEEDED,
            
            # Service errors
            ErrorCategory.SERVICE_UNAVAILABLE: "Service temporarily unavailable",
            ErrorCategory.EXTERNAL_SERVICE: "External service error",
            ErrorCategory.DATABASE: "Data access error",
            ErrorCategory.CONFIGURATION: "Configuration error",
            
            # Generic internal error
            ErrorCategory.INTERNAL_ERROR: ValidationMessages.INTERNAL_SERVER_ERROR,
        }
    
    def sanitize_error_for_client(self, error: Exception, error_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sanitize error for external client response.
        
        Args:
            error: The exception that occurred
            error_id: Optional error ID for correlation with logs
            
        Returns:
            Dict containing sanitized error response safe for external clients
        """
        category = self._categorize_error(error)
        sensitivity = self._assess_sensitivity(error)
        
        # Always use safe messages for external clients
        safe_message = self._safe_error_mappings.get(
            category, 
            ValidationMessages.INTERNAL_SERVER_ERROR
        )
        
        response = {
            "error": {
                "message": safe_message,
                "type": category.value,
                "code": self._get_http_status_code(category)
            }
        }
        
        # Add error ID for correlation if provided
        if error_id:
            response["error"]["error_id"] = error_id
        
        # For validation errors, we can be slightly more specific
        if category == ErrorCategory.VALIDATION and isinstance(error, (ValueError, TypeError)):
            # Only include sanitized validation details
            sanitized_details = self._sanitize_validation_error(str(error))
            if sanitized_details and len(sanitized_details) < 200:
                response["error"]["message"] = sanitized_details
        
        return response
    
    def sanitize_error_for_logging(self, error: Exception, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Prepare error details for internal logging with sensitive data sanitized.
        
        Args:
            error: The exception that occurred
            context: Additional context about the error
            
        Returns:
            Dict containing detailed error information safe for internal logging
        """
        # Get full error details
        error_details = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "error_category": self._categorize_error(error).value,
            "sensitivity_level": self._assess_sensitivity(error).value,
        }
        
        # Add stack trace for debugging (sanitized)
        if hasattr(error, '__traceback__') and error.__traceback__:
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            sanitized_traceback = []
            for line in tb_lines:
                sanitized_line = self._sanitize_content(line)
                sanitized_traceback.append(sanitized_line)
            error_details["traceback"] = sanitized_traceback
        
        # Add cause chain if available
        if hasattr(error, '__cause__') and error.__cause__:
            error_details["caused_by"] = {
                "type": type(error.__cause__).__name__,
                "message": self._sanitize_content(str(error.__cause__))
            }
        
        # Add context information (sanitized)
        if context:
            error_details["context"] = self._sanitize_context_data(context)
        
        # Add Enaam-specific error details if available
        if hasattr(error, 'operation') or hasattr(error, 'component') or hasattr(error, 'error_code'):
            error_details["enaam_error"] = {
                "operation": getattr(error, 'operation', None),
                "component": getattr(error, 'component', None), 
                "error_code": getattr(error, 'error_code', None)
            }
        
        return error_details
    
    def create_correlation_id(self, error: Exception) -> str:
        """Create a unique correlation ID for error tracking"""
        import uuid
        import hashlib
        
        # Create deterministic ID based on error type and message
        error_str = f"{type(error).__name__}:{str(error)[:100]}"
        hash_digest = hashlib.md5(error_str.encode()).hexdigest()[:8]
        unique_id = str(uuid.uuid4())[:8]
        
        return f"ERR-{hash_digest}-{unique_id}"
    
    def _categorize_error(self, error: Exception) -> ErrorCategory:
        """Categorize error type for appropriate handling"""
        error_type = type(error).__name__
        error_message = str(error).lower()
        
        # Check for validation errors
        if any(keyword in error_message for keyword in ['invalid', 'missing', 'required', 'format']):
            return ErrorCategory.VALIDATION
        
        # Check for authentication/authorization
        if any(keyword in error_message for keyword in ['auth', 'permission', 'access', 'forbidden']):
            if 'permission' in error_message or 'forbidden' in error_message:
                return ErrorCategory.AUTHORIZATION
            return ErrorCategory.AUTHENTICATION
        
        # Check for rate limiting
        if 'rate limit' in error_message or 'too many requests' in error_message:
            return ErrorCategory.RATE_LIMIT
        
        # Check for not found errors
        if 'not found' in error_message or error_type == 'FileNotFoundError':
            return ErrorCategory.NOT_FOUND
        
        # Check for service errors
        if any(keyword in error_message for keyword in ['connection', 'timeout', 'unreachable']):
            return ErrorCategory.SERVICE_UNAVAILABLE
        
        # Check for external service errors
        if any(keyword in error_message for keyword in ['api', 'http', 'request', 'response']):
            return ErrorCategory.EXTERNAL_SERVICE
        
        # Check for database errors
        if any(keyword in error_message for keyword in ['database', 'sql', 'query', 'table', 'column']):
            return ErrorCategory.DATABASE
        
        # Check for configuration errors
        if any(keyword in error_message for keyword in ['config', 'setting', 'environment', 'env']):
            return ErrorCategory.CONFIGURATION
        
        # Default to internal error
        return ErrorCategory.INTERNAL_ERROR
    
    def _assess_sensitivity(self, error: Exception) -> ErrorSensitivityLevel:
        """Assess the sensitivity level of error information"""
        error_message = str(error).lower()
        error_type = type(error).__name__
        
        # Check for sensitive keywords
        if any(keyword in error_message for keyword in self._sensitive_keywords):
            return ErrorSensitivityLevel.SENSITIVE
        
        # Check for system-level details
        if any(pattern in error_message for pattern in ['/', '\\', '.py', '.log', '0x']):
            return ErrorSensitivityLevel.SYSTEM
        
        # Check for sensitive exception types
        if error_type in self._sensitive_exception_types:
            return ErrorSensitivityLevel.INTERNAL
        
        # Default to internal for safety
        return ErrorSensitivityLevel.INTERNAL
    
    def _sanitize_content(self, content: str) -> str:
        """Apply all sanitization patterns to content"""
        if not isinstance(content, str):
            return str(content)
        
        sanitized = content
        for pattern, replacement in self._sensitive_patterns:
            sanitized = pattern.sub(replacement, sanitized)
        
        # Limit length to prevent log bombing
        if len(sanitized) > 1000:
            sanitized = sanitized[:1000] + "...[truncated]"
        
        return sanitized
    
    def _sanitize_validation_error(self, error_message: str) -> str:
        """Create a safe validation error message"""
        # Remove any sensitive content first
        sanitized = self._sanitize_content(error_message)
        
        # Map common validation errors to safe messages
        validation_mappings = {
            'invalid json': 'Invalid request format',
            'missing required': 'Missing required parameter',
            'too long': 'Parameter value too long',
            'invalid characters': 'Invalid parameter format',
            'unknown method': 'Unsupported operation',
            'invalid type': 'Invalid parameter type'
        }
        
        sanitized_lower = sanitized.lower()
        for pattern, safe_message in validation_mappings.items():
            if pattern in sanitized_lower:
                return safe_message
        
        # If no specific mapping, return generic validation error
        return "Invalid request parameters"
    
    def _sanitize_context_data(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize context data for logging"""
        if not isinstance(context, dict):
            return {}
        
        sanitized = {}
        for key, value in context.items():
            # Skip sensitive keys entirely
            if any(sensitive_key in key.lower() for sensitive_key in self._sensitive_keywords):
                sanitized[key] = "<hidden>"
                continue
            
            # Sanitize string values
            if isinstance(value, str):
                sanitized[key] = self._sanitize_content(value)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_context_data(value)
            elif isinstance(value, list):
                sanitized[key] = [self._sanitize_content(str(item)) if isinstance(item, str) else item 
                                for item in value[:10]]  # Limit list size
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _get_http_status_code(self, category: ErrorCategory) -> int:
        """Get appropriate HTTP status code for error category"""
        status_mappings = {
            ErrorCategory.VALIDATION: 400,
            ErrorCategory.AUTHENTICATION: 401,
            ErrorCategory.AUTHORIZATION: 403,
            ErrorCategory.NOT_FOUND: 404,
            ErrorCategory.RATE_LIMIT: 429,
            ErrorCategory.SERVICE_UNAVAILABLE: 503,
            ErrorCategory.EXTERNAL_SERVICE: 502,
            ErrorCategory.DATABASE: 500,
            ErrorCategory.CONFIGURATION: 500,
            ErrorCategory.INTERNAL_ERROR: 500,
        }
        return status_mappings.get(category, 500)


class SafeErrorLogger:
    """Logger wrapper that automatically sanitizes error information"""
    
    def __init__(self, logger: logging.Logger, sanitizer: ErrorSanitizer = None):
        self.logger = logger
        self.sanitizer = sanitizer or ErrorSanitizer()
    
    def log_error(self, error: Exception, level: int = logging.ERROR, 
                  context: Dict[str, Any] = None, correlation_id: str = None) -> str:
        """
        Log error with automatic sanitization and return correlation ID.
        
        Args:
            error: The exception to log
            level: Logging level (default: ERROR)
            context: Additional context information
            correlation_id: Optional existing correlation ID
            
        Returns:
            Correlation ID for error tracking
        """
        # Generate correlation ID if not provided
        if not correlation_id:
            correlation_id = self.sanitizer.create_correlation_id(error)
        
        # Prepare sanitized error details for logging
        error_details = self.sanitizer.sanitize_error_for_logging(error, context)
        
        # Log with correlation ID
        self.logger.log(
            level,
            "Error [%s]: %s - %s",
            correlation_id,
            error_details["error_type"],
            error_details["error_message"][:200],
            extra={
                "correlation_id": correlation_id,
                "error_details": error_details
            }
        )
        
        return correlation_id
    
    def log_and_sanitize(self, error: Exception, context: Dict[str, Any] = None) -> Tuple[str, Dict[str, Any]]:
        """
        Log error internally and return sanitized response for client.
        
        Returns:
            Tuple of (correlation_id, client_safe_response)
        """
        # Log full details internally
        correlation_id = self.log_error(error, context=context)
        
        # Create sanitized response for client
        client_response = self.sanitizer.sanitize_error_for_client(error, correlation_id)
        
        return correlation_id, client_response


# Factory functions for dependency injection
def create_error_sanitizer() -> ErrorSanitizer:
    """Create error sanitizer instance"""
    return ErrorSanitizer()


def create_safe_error_logger(logger: logging.Logger) -> SafeErrorLogger:
    """Create safe error logger instance"""
    return SafeErrorLogger(logger, create_error_sanitizer())