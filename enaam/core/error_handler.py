"""
Error Handler Decorators and Utilities

Provides consistent error handling decorators, logging utilities,
and error response formatting for the Enaam system.
"""

import functools
import logging
import sqlite3
import traceback
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union

from .exceptions import (
    BusinessLogicError,
    CriticalError,
    DatabaseError,
    EnaamError,
    ExternalServiceError,
    KhursheedBridgeError,
    MCPError,
    RetryableError,
    ValidationError,
    create_error_response,
    sanitize_error_message,
)

F = TypeVar('F', bound=Callable[..., Any])

# Removed global logger - use dependency injection instead


def get_error_logger(module_name: str) -> logging.Logger:
    """Get a module-specific error logger with enhanced formatting."""
    logger = logging.getLogger(f'enaam.errors.{module_name}')
    
    # Configure enhanced error logging format if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - '
            '[%(correlation_id)s] %(message)s',
            defaults={'correlation_id': 'N/A'}
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


def get_safe_error_logger(module_name: str):
    """Get safe error logger that automatically sanitizes error information"""
    from .error_sanitizer import create_safe_error_logger
    logger = get_error_logger(module_name)
    return create_safe_error_logger(logger)


def create_error_logger() -> logging.Logger:
    """Factory function to create error logger - eliminates global state."""
    return logging.getLogger('enaam.errors')


class ErrorContext:
    """Context manager for error handling with automatic cleanup."""
    
    def __init__(self, operation: str, logger: Optional[logging.Logger] = None):
        self.operation = operation
        self.logger = logger or create_error_logger()
        self.start_time = None
    
    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.debug("Starting operation: %s", self.operation)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        duration = time.time() - self.start_time if self.start_time else 0
        
        if exc_type is None:
            self.logger.debug("Operation completed successfully: %s (%.3fs)", self.operation, duration)
        else:
            self.logger.error(
                "Operation failed: %s (%.3fs) - %s: %s",
                self.operation,
                duration,
                exc_type.__name__,
                str(exc_val)
            )


def handle_errors(
    default_exception: Type[EnaamError] = EnaamError,
    reraise_known: bool = True,
    log_errors: bool = True,
    operation: Optional[str] = None
) -> Callable[[F], F]:
    """
    Decorator for consistent error handling.
    
    Args:
        default_exception: Exception type to wrap unknown errors
        reraise_known: Whether to re-raise known EnaamError instances
        log_errors: Whether to log errors
        operation: Operation name for logging (defaults to function name)
        
    Returns:
        Decorated function with error handling
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            logger = get_error_logger(func.__module__.split('.')[-1])
            
            try:
                return func(*args, **kwargs)
            except EnaamError:
                if log_errors:
                    logger.exception("Known error in %s", op_name)
                if reraise_known:
                    raise
                # Convert to default exception type
                return create_error_response(default_exception(f"Error in {op_name}"))
            except Exception as e:
                if log_errors:
                    logger.exception("Unexpected error in %s", op_name)
                
                # Convert specific exceptions to appropriate EnaamError types
                enaam_error = convert_to_enaam_error(e, op_name)
                raise enaam_error
        
        return wrapper
    return decorator


def handle_database_errors(operation: str = None) -> Callable[[F], F]:
    """Decorator specifically for database operations."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            logger = get_error_logger('database')
            
            try:
                return func(*args, **kwargs)
            except sqlite3.Error as e:
                logger.exception("Database error in %s", op_name)
                raise DatabaseError(
                    f"Database operation failed: {sanitize_error_message(str(e))}",
                    operation=op_name,
                    cause=e
                )
            except EnaamError:
                raise
            except Exception as e:
                logger.exception("Unexpected error in database operation %s", op_name)
                raise DatabaseError(
                    f"Unexpected database error in {op_name}",
                    operation=op_name,
                    cause=e
                )
        
        return wrapper
    return decorator


def handle_bridge_errors(skill_name: str = None) -> Callable[[F], F]:
    """Decorator specifically for Khursheed bridge operations."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_error_logger('bridge')
            op_name = func.__name__
            
            try:
                return func(*args, **kwargs)
            except EnaamError:
                raise
            except Exception as e:
                logger.exception("Bridge error in %s", op_name)
                raise KhursheedBridgeError(
                    f"Bridge operation failed: {sanitize_error_message(str(e))}",
                    skill_name=skill_name,
                    operation=op_name,
                    cause=e
                )
        
        return wrapper
    return decorator


def handle_mcp_errors(method: str = None) -> Callable[[F], F]:
    """Decorator specifically for MCP operations."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_error_logger('mcp')
            op_name = func.__name__
            
            try:
                return func(*args, **kwargs)
            except EnaamError:
                raise
            except Exception as e:
                logger.exception("MCP error in %s", op_name)
                raise MCPError(
                    f"MCP operation failed: {sanitize_error_message(str(e))}",
                    method=method,
                    operation=op_name,
                    cause=e
                )
        
        return wrapper
    return decorator


def log_and_suppress(
    exception_types: tuple = (Exception,),
    default_return: Any = None,
    log_level: int = logging.ERROR
) -> Callable[[F], F]:
    """
    Decorator to log exceptions and return a default value instead of raising.
    
    Use sparingly and only for non-critical operations where failure
    should not interrupt the main flow.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = get_error_logger(func.__module__.split('.')[-1])
            
            try:
                return func(*args, **kwargs)
            except exception_types as e:
                logger.log(
                    log_level,
                    "Suppressed error in %s: %s",
                    func.__name__,
                    sanitize_error_message(str(e))
                )
                return default_return
        
        return wrapper
    return decorator


def convert_to_enaam_error(exception: Exception, operation: str) -> EnaamError:
    """
    Convert a generic exception to an appropriate EnaamError.
    
    Args:
        exception: Original exception
        operation: Name of operation that failed
        
    Returns:
        Appropriate EnaamError subclass
    """
    error_msg = sanitize_error_message(str(exception))
    
    # Database errors
    if isinstance(exception, sqlite3.Error):
        return DatabaseError(
            f"Database error in {operation}: {error_msg}",
            operation=operation,
            cause=exception
        )
    
    # Network/HTTP errors
    if hasattr(exception, 'status_code') or 'http' in str(type(exception)).lower():
        status_code = getattr(exception, 'status_code', None)
        return ExternalServiceError(
            f"External service error in {operation}: {error_msg}",
            status_code=status_code,
            cause=exception
        )
    
    # Validation errors (ValueError, TypeError in validation context)
    if isinstance(exception, (ValueError, TypeError)):
        return ValidationError(
            f"Validation error in {operation}: {error_msg}",
            cause=exception
        )
    
    # Critical system errors (MemoryError, SystemError, etc.)
    if isinstance(exception, (MemoryError, SystemError, OSError)):
        return CriticalError(
            f"Critical system error in {operation}: {error_msg}",
            cause=exception
        )
    
    # Default to generic EnaamError
    return EnaamError(
        f"Unexpected error in {operation}: {error_msg}",
        cause=exception
    )


def safe_execute(
    operation: str,
    func: Callable,
    *args,
    default_on_error: Any = None,
    log_errors: bool = True,
    **kwargs
) -> Any:
    """
    Safely execute a function with error handling.
    
    Args:
        operation: Name of operation for logging
        func: Function to execute
        *args: Arguments for function
        default_on_error: Value to return on error
        log_errors: Whether to log errors
        **kwargs: Keyword arguments for function
        
    Returns:
        Function result or default_on_error on failure
    """
    logger = get_error_logger('safe_execute')
    
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            logger.exception("Error in safe_execute for %s", operation)
        
        if isinstance(e, EnaamError):
            # For known errors, you might want to handle differently
            pass
        
        return default_on_error


def create_structured_error_response(
    error: Union[Exception, EnaamError], 
    operation: str,
    include_details: bool = False
) -> Dict[str, Any]:
    """
    Create a structured error response for APIs.
    
    Args:
        error: Exception or EnaamError
        operation: Operation that failed
        include_details: Whether to include detailed error information
        
    Returns:
        Structured error response
    """
    if isinstance(error, EnaamError):
        enaam_error = error
    else:
        enaam_error = convert_to_enaam_error(error, operation)
    
    return create_error_response(enaam_error, include_details)


def setup_error_logging(
    logger: logging.Logger = None,
    log_level: int = logging.ERROR,
    log_file: Optional[str] = None
) -> None:
    """
    Setup error logging configuration.
    
    Args:
        logger: Logger instance to configure (creates default if None)
        log_level: Logging level for errors
        log_file: Optional log file path
    """
    # Use provided logger or create default error logger
    target_logger = logger or create_error_logger()
    target_logger.setLevel(log_level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    target_logger.addHandler(console_handler)
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        target_logger.addHandler(file_handler)


# Initialize error logging
setup_error_logging()