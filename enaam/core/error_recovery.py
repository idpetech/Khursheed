"""
Error Recovery System

Implements automatic error recovery strategies for different error types.
Provides retry mechanisms, fallback strategies, and error handling patterns.
"""

import asyncio
import time
import logging
from typing import Any, Callable, Dict, Optional, Union, TypeVar, Generic
from functools import wraps
from dataclasses import dataclass

from .errors import (
    EnaamBaseError,
    ErrorRecoveryStrategy,
    ErrorSeverity,
    ErrorCategory,
    EnaamExternalServiceError,
    EnaamDatabaseError,
    EnaamSystemError,
    EnaamCriticalError,
)

T = TypeVar('T')


@dataclass
class RecoveryConfig:
    """Configuration for error recovery strategies."""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    fallback_enabled: bool = True
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for preventing cascading failures.
    """
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function through circuit breaker."""
        if self.state == "open":
            if time.time() - self.last_failure_time > self.timeout:
                self.state = "half-open"
            else:
                raise EnaamSystemError(
                    "Circuit breaker is open",
                    component="circuit_breaker",
                    context={"state": self.state, "failure_count": self.failure_count}
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        """Handle successful execution."""
        self.failure_count = 0
        self.state = "closed"
    
    def _on_failure(self):
        """Handle failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"


class ErrorRecoveryManager:
    """
    Manages error recovery strategies for different error types.
    """
    
    def __init__(self, config: Optional[RecoveryConfig] = None, logger: Optional[logging.Logger] = None):
        self.config = config or RecoveryConfig()
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.logger = logger or self._create_default_logger()
    
    def _create_default_logger(self) -> logging.Logger:
        """Create default logger when none provided"""
        return logging.getLogger(__name__)
    
    def get_circuit_breaker(self, key: str) -> CircuitBreaker:
        """Get or create circuit breaker for a specific operation."""
        if key not in self.circuit_breakers:
            self.circuit_breakers[key] = CircuitBreaker(
                self.config.circuit_breaker_threshold,
                self.config.circuit_breaker_timeout
            )
        return self.circuit_breakers[key]
    
    def execute_with_recovery(
        self,
        func: Callable[[], T],
        operation_name: str,
        fallback_func: Optional[Callable[[], T]] = None,
        recovery_config: Optional[RecoveryConfig] = None
    ) -> T:
        """
        Execute function with automatic error recovery.
        
        Args:
            func: Function to execute
            operation_name: Name for logging and circuit breaker identification
            fallback_func: Optional fallback function
            recovery_config: Optional custom recovery configuration
            
        Returns:
            Result from successful execution
            
        Raises:
            EnaamBaseError: When all recovery strategies fail
        """
        config = recovery_config or self.config
        circuit_breaker = self.get_circuit_breaker(operation_name)
        
        last_error = None
        
        for attempt in range(config.max_retries + 1):
            try:
                # Execute through circuit breaker
                result = circuit_breaker.call(func)
                
                if attempt > 0:
                    self.logger.info(f"Operation '{operation_name}' succeeded after {attempt} retries")
                
                return result
                
            except EnaamBaseError as e:
                last_error = e
                
                # Don't retry critical errors
                if e.severity == ErrorSeverity.CRITICAL:
                    break
                
                # Don't retry if strategy doesn't support it
                if e.recovery_strategy != ErrorRecoveryStrategy.RETRY:
                    break
                
                # Don't retry if max attempts reached
                if attempt >= config.max_retries:
                    break
                
                # Calculate delay
                delay = self._calculate_delay(attempt, config)
                self.logger.warning(
                    f"Operation '{operation_name}' failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.2f}s: {str(e)}"
                )
                
                time.sleep(delay)
                
            except Exception as e:
                # Convert generic exception to Enaam error
                last_error = EnaamSystemError(
                    f"Unexpected error in {operation_name}: {str(e)}",
                    cause=e,
                    operation=operation_name
                )
                break
        
        # All retries failed, try fallback
        if fallback_func and config.fallback_enabled:
            try:
                self.logger.info(f"Attempting fallback for operation '{operation_name}'")
                return fallback_func()
            except Exception as e:
                self.logger.error(f"Fallback also failed for operation '{operation_name}': {str(e)}")
        
        # Recovery failed
        if last_error:
            raise last_error
        else:
            raise EnaamSystemError(f"Operation '{operation_name}' failed without error details")
    
    def _calculate_delay(self, attempt: int, config: RecoveryConfig) -> float:
        """Calculate retry delay with exponential backoff and jitter."""
        delay = config.base_delay * (config.exponential_base ** attempt)
        delay = min(delay, config.max_delay)
        
        if config.jitter:
            import random
            # Add up to 25% jitter
            jitter = random.uniform(0, delay * 0.25)
            delay += jitter
        
        return delay


def with_retry(
    max_retries: int = 3,
    operation_name: Optional[str] = None,
    fallback_func: Optional[Callable] = None,
    config: Optional[RecoveryConfig] = None
):
    """
    Decorator for automatic retry on errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        operation_name: Name for logging (uses function name if not provided)
        fallback_func: Optional fallback function
        config: Optional recovery configuration
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal operation_name
            if operation_name is None:
                operation_name = func.__name__
            
            recovery_manager = ErrorRecoveryManager(config)
            
            return recovery_manager.execute_with_recovery(
                lambda: func(*args, **kwargs),
                operation_name,
                fallback_func
            )
        
        return wrapper
    return decorator


def with_circuit_breaker(
    failure_threshold: int = 5,
    timeout: int = 60,
    operation_name: Optional[str] = None
):
    """
    Decorator for circuit breaker pattern.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        timeout: Time in seconds to wait before trying again
        operation_name: Name for circuit breaker identification
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal operation_name
            if operation_name is None:
                operation_name = func.__name__
            
            circuit_breaker = CircuitBreaker(failure_threshold, timeout)
            return circuit_breaker.call(func, *args, **kwargs)
        
        return wrapper
    return decorator


def with_fallback(fallback_func: Callable):
    """
    Decorator to provide fallback function on error.
    
    Args:
        fallback_func: Function to call if main function fails
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logging.warning(f"Function {func.__name__} failed, using fallback: {str(e)}")
                return fallback_func(*args, **kwargs)
        
        return wrapper
    return decorator


class BulkOperationRecovery:
    """
    Handles recovery for bulk operations where partial success is acceptable.
    """
    
    def __init__(self, config: Optional[RecoveryConfig] = None, logger: Optional[logging.Logger] = None):
        self.config = config or RecoveryConfig()
        self.logger = logger or self._create_default_logger()
    
    def _create_default_logger(self) -> logging.Logger:
        """Create default logger when none provided"""
        return logging.getLogger(__name__)
    
    def execute_bulk_with_recovery(
        self,
        items: list,
        operation_func: Callable[[Any], Any],
        operation_name: str,
        partial_success_threshold: float = 0.5
    ) -> Dict[str, Any]:
        """
        Execute bulk operation with partial success handling.
        
        Args:
            items: List of items to process
            operation_func: Function to apply to each item
            operation_name: Name for logging
            partial_success_threshold: Minimum success ratio (0.0-1.0)
            
        Returns:
            Dictionary with success/failure results
        """
        results = {
            "successful": [],
            "failed": [],
            "errors": [],
            "total_count": len(items),
            "success_count": 0,
            "failure_count": 0,
            "success_ratio": 0.0
        }
        
        for item in items:
            try:
                result = operation_func(item)
                results["successful"].append({"item": item, "result": result})
                results["success_count"] += 1
            except EnaamBaseError as e:
                results["failed"].append({"item": item, "error": str(e)})
                results["errors"].append(e)
                results["failure_count"] += 1
                
                self.logger.warning(f"Bulk operation item failed in '{operation_name}': {str(e)}")
            except Exception as e:
                # Convert to Enaam error
                enaam_error = EnaamSystemError(
                    f"Unexpected error in bulk operation '{operation_name}': {str(e)}",
                    cause=e,
                    operation=operation_name
                )
                
                results["failed"].append({"item": item, "error": str(enaam_error)})
                results["errors"].append(enaam_error)
                results["failure_count"] += 1
                
                self.logger.error(f"Unexpected error in bulk operation '{operation_name}': {str(e)}")
        
        # Calculate success ratio
        if results["total_count"] > 0:
            results["success_ratio"] = results["success_count"] / results["total_count"]
        
        # Check if operation meets success threshold
        if results["success_ratio"] < partial_success_threshold:
            raise EnaamSystemError(
                f"Bulk operation '{operation_name}' failed to meet success threshold "
                f"({results['success_ratio']:.2%} < {partial_success_threshold:.2%})",
                operation=operation_name,
                context={
                    "success_count": results["success_count"],
                    "failure_count": results["failure_count"],
                    "total_count": results["total_count"],
                    "success_ratio": results["success_ratio"],
                    "threshold": partial_success_threshold
                }
            )
        
        self.logger.info(
            f"Bulk operation '{operation_name}' completed: "
            f"{results['success_count']}/{results['total_count']} successful "
            f"({results['success_ratio']:.2%})"
        )
        
        return results


# Convenience functions for common recovery patterns
def retry_on_failure(func: Callable, max_attempts: int = 3, delay: float = 1.0) -> Any:
    """Simple retry function with linear backoff."""
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            time.sleep(delay * (attempt + 1))


def execute_with_timeout(func: Callable, timeout_seconds: int) -> Any:
    """Execute function with timeout (for sync operations)."""
    import signal
    
    def timeout_handler(signum, frame):
        raise EnaamSystemError(
            f"Operation timed out after {timeout_seconds} seconds",
            context={"timeout": timeout_seconds}
        )
    
    # Set up timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout_seconds)
    
    try:
        result = func()
        signal.alarm(0)  # Clear alarm
        return result
    except Exception as e:
        signal.alarm(0)  # Clear alarm
        raise e