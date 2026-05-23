# 🔧 Enaam System Refactoring Prompts

## Overview
This document provides detailed, actionable prompts for eliminating the critical code smells identified in the Enaam system. Each prompt is designed to be fed to Claude Code or any ADE for systematic refactoring.

---

## 🚨 Critical Issues (Fix Immediately)

### PROMPT 1: Eliminate Threading & Concurrency Violations

**Objective**: Fix SQLite threading issues and implement proper concurrency handling.

**Files**: `enaam/core/logging.py`, `enaam/mcp/server.py`

```
TASK: Fix threading and concurrency violations in the Enaam logging system.

CURRENT ISSUES:
1. SQLite connection with check_same_thread=False (line 27 in logging.py)
2. Global logger instance causing thread safety issues
3. No connection pooling or thread-local storage

REQUIREMENTS:
1. Remove check_same_thread=False hack
2. Implement proper thread-local database connections
3. Create connection pool for MCP server threading
4. Add proper locking mechanisms where needed

IMPLEMENTATION APPROACH:
1. Create ThreadLocalConnection class that manages per-thread SQLite connections
2. Replace global logger with dependency injection pattern
3. Implement connection pooling for the MCP server
4. Add proper error handling for database connection failures
5. Ensure all database operations are atomic

CONSTRAINTS:
- Must maintain existing API surface
- No breaking changes to public interfaces
- Preserve all existing functionality
- Must be testable with unit tests

SUCCESS CRITERIA:
- All SQLite operations work correctly in multi-threaded environment
- No more check_same_thread=False usage
- Ruff checks pass for concurrency-related rules
- MCP server handles concurrent requests safely

FILES TO MODIFY:
- enaam/core/logging.py
- enaam/mcp/server.py
- enaam/integrations/khursheed_bridge.py (update logging calls)

EXAMPLE PATTERN:
```python
class ThreadLocalLogger:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
    
    def _get_connection(self):
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(self._db_path)
        return self._local.connection
```
```

### PROMPT 2: Eliminate Global State Pollution

**Objective**: Remove all global mutable state and implement dependency injection.

**Files**: `enaam/core/logging.py`, all modules using global instances

```
TASK: Eliminate global state pollution throughout the Enaam system.

CURRENT ISSUES:
1. Global logger instance in logging.py (line 147)
2. Global state makes testing impossible
3. Hidden dependencies between modules
4. Violates inversion of control principle

REQUIREMENTS:
1. Remove all global mutable instances
2. Implement dependency injection container
3. Create factory functions for service creation
4. Make all dependencies explicit through constructor injection

IMPLEMENTATION APPROACH:
1. Create ServiceContainer class for dependency management
2. Convert all global instances to factory functions
3. Update all consuming classes to accept dependencies
4. Create configuration-based service registration
5. Implement lazy loading for expensive services

CONSTRAINTS:
- Maintain backward compatibility in public APIs
- No performance regression
- Clear separation of concerns
- Easy to mock for testing

SUCCESS CRITERIA:
- Zero global mutable state in the codebase
- All dependencies explicit through constructors
- Easy unit testing with mocked dependencies
- Ruff global state checks pass

FILES TO MODIFY:
- enaam/core/logging.py (remove global logger)
- enaam/core/container.py (new dependency injection container)
- enaam/core/agent.py (accept injected dependencies)
- enaam/mcp/handlers.py (accept injected dependencies)
- enaam/integrations/khursheed_bridge.py (accept injected dependencies)

EXAMPLE PATTERN:
```python
class ServiceContainer:
    def __init__(self):
        self._services = {}
        self._factories = {}
    
    def register(self, service_type: Type[T], factory: Callable[[], T]):
        self._factories[service_type] = factory
    
    def get(self, service_type: Type[T]) -> T:
        if service_type not in self._services:
            self._services[service_type] = self._factories[service_type]()
        return self._services[service_type]
```
```

### PROMPT 3: Fix Path Manipulation Chaos

**Objective**: Eliminate all sys.path manipulation and implement proper Python packaging.

**Files**: All files with sys.path imports

```
TASK: Eliminate sys.path manipulation and implement proper Python packaging.

CURRENT ISSUES:
1. sys.path.insert() scattered across 12+ files
2. Brittle import system that breaks in different environments
3. No proper package structure
4. Relative import failures

REQUIREMENTS:
1. Remove ALL sys.path manipulation
2. Implement proper __init__.py structure
3. Use relative imports within packages
4. Create proper package entry points
5. Set up PYTHONPATH correctly

IMPLEMENTATION APPROACH:
1. Add proper __init__.py files to create package hierarchy
2. Convert all absolute imports to relative imports within packages
3. Create setup.py or pyproject.toml for proper package installation
4. Update all import statements to use package-relative imports
5. Create proper package structure with clear boundaries

CONSTRAINTS:
- No sys.path manipulation anywhere
- All imports must work in any environment
- Maintain existing functionality
- Must work with editable installs (pip install -e .)

SUCCESS CRITERIA:
- Zero sys.path.insert() or sys.path.append() calls
- All imports work without environment setup
- Package can be installed with pip
- Ruff import checks pass

FILES TO MODIFY:
- All __init__.py files (add proper exports)
- enaam/mcp/handlers.py (fix imports)
- enaam/mcp/server.py (fix imports)
- enaam/integrations/khursheed_bridge.py (fix imports)
- enaam/run.py (fix imports)
- enaam/mcp_server.py (fix imports)
- setup.py or pyproject.toml (new)

EXAMPLE PATTERN:
```python
# In enaam/__init__.py
from .core.agent import EnaamAgent
from .core.state import EnaamState

__all__ = ["EnaamAgent", "EnaamState"]

# In enaam/mcp/handlers.py
from ..core.agent import EnaamAgent  # Relative import
from ..integrations.khursheed_bridge import KhursheedBridge
```
```

---

## 🔧 High Priority Fixes

### PROMPT 4: Implement Proper Exception Handling

**Objective**: Replace exception swallowing with proper error handling strategy.

**Files**: `enaam/integrations/khursheed_bridge.py`, all modules

```
TASK: Implement consistent exception handling throughout the system.

CURRENT ISSUES:
1. Silent exception swallowing in logging (line 57, khursheed_bridge.py)
2. Mix of exceptions, return values, and silent failures
3. No consistent error handling strategy
4. Information leakage in error responses

REQUIREMENTS:
1. Create hierarchy of custom exception types
2. Implement consistent error handling strategy
3. Remove all silent exception catching
4. Add proper logging for all exceptions
5. Sanitize error messages for external APIs

IMPLEMENTATION APPROACH:
1. Define exception hierarchy with base EnaamError class
2. Create specific exception types for different error categories
3. Implement error handler decorators for consistent handling
4. Add structured logging for all exceptions
5. Create error response formatter for external APIs

CONSTRAINTS:
- No silent failures
- Consistent error response format
- Proper logging of all errors
- No sensitive information leakage

SUCCESS CRITERIA:
- All exceptions properly logged and handled
- Consistent error response format across all APIs
- No bare except clauses
- Clear error messages for debugging

FILES TO MODIFY:
- enaam/core/exceptions.py (new custom exception hierarchy)
- enaam/core/error_handler.py (new error handling decorators)
- enaam/integrations/khursheed_bridge.py (fix silent catching)
- enaam/mcp/handlers.py (consistent error responses)
- All other modules (replace exception handling)

EXAMPLE PATTERN:
```python
class EnaamError(Exception):
    """Base exception for all Enaam errors."""

class ConfigurationError(EnaamError):
    """Configuration-related errors."""

class KhursheedBridgeError(EnaamError):
    """Khursheed bridge operation errors."""

def handle_errors(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except EnaamError:
            logger.exception("Known error in %s", func.__name__)
            raise
        except Exception as e:
            logger.exception("Unexpected error in %s", func.__name__)
            raise EnaamError(f"Unexpected error: {type(e).__name__}")
    return wrapper
```
```

### PROMPT 5: Eliminate Magic String Dependencies

**Objective**: Replace magic strings with enums and constants.

**Files**: `enaam/mcp/handlers.py`, all modules with string literals

```
TASK: Replace magic strings with proper constants and enums.

CURRENT ISSUES:
1. Magic strings for function names in handlers.py (line 45+)
2. Hardcoded method names throughout codebase
3. String literals for configuration keys
4. No central place for constants

REQUIREMENTS:
1. Create enums for all method/function names
2. Create constants module for configuration keys
3. Replace all magic strings with named constants
4. Ensure type safety with enums

IMPLEMENTATION APPROACH:
1. Create enums.py with all method and function name enums
2. Create constants.py with configuration constants
3. Update all usages to reference enums/constants
4. Add validation that ensures enum values match actual functions
5. Create type hints that enforce enum usage

CONSTRAINTS:
- No string literals for identifiers
- Type-safe enum usage
- Backward compatibility in JSON APIs
- Clear naming conventions

SUCCESS CRITERIA:
- All method/function names defined as enums
- All configuration keys as constants
- No magic string literals in code
- Type hints enforce enum usage

FILES TO MODIFY:
- enaam/core/enums.py (new enum definitions)
- enaam/core/constants.py (new constant definitions)
- enaam/mcp/handlers.py (replace magic strings)
- enaam/mcp/schemas.py (use enums)
- enaam/core/router.py (use enums)
- All modules (replace string literals)

EXAMPLE PATTERN:
```python
from enum import Enum

class BridgeFunction(str, Enum):
    EMAIL_SUMMARY = "email_summary"
    LEAD_SCAN = "lead_scan"
    WEEKLY_DIGEST = "weekly_digest"
    EXECUTIVE_SUMMARY = "executive_summary"

class ConfigKey(str, Enum):
    SERVER_HOST = "server.host"
    SERVER_PORT = "server.port"
    DATABASE_URL = "database.url"

# Usage
bridge_functions = {
    BridgeFunction.EMAIL_SUMMARY: self.bridge.email_summary,
    BridgeFunction.LEAD_SCAN: self.bridge.lead_scan,
}
```
```

### PROMPT 6: Fix Configuration Management

**Objective**: Centralize and secure configuration management.

**Files**: `enaam/config.py`, all modules with os.getenv() calls

```
TASK: Implement centralized and secure configuration management.

CURRENT ISSUES:
1. Environment variable access scattered throughout code
2. No validation of configuration values
3. No default values or required field checks
4. Configuration mixed with business logic

REQUIREMENTS:
1. Centralize all configuration in config module
2. Add validation for all configuration values
3. Support different environments (dev, test, prod)
4. Implement secure handling of sensitive data
5. Add configuration schema with defaults

IMPLEMENTATION APPROACH:
1. Create comprehensive configuration classes with validation
2. Implement environment-specific configuration files
3. Add configuration loading with validation
4. Create configuration injection for all services
5. Add secure storage for sensitive configuration

CONSTRAINTS:
- No environment variable access outside config module
- All configuration validated at startup
- Support for different environments
- Secure handling of secrets

SUCCESS CRITERIA:
- Single source of truth for configuration
- All config values validated
- Clear separation of config and business logic
- Support for environment overrides

FILES TO MODIFY:
- enaam/config.py (comprehensive configuration classes)
- enaam/core/config_loader.py (new configuration loading)
- enaam/integrations/khursheed_bridge.py (use injected config)
- All modules (remove direct env access)
- config/ directory (new environment-specific configs)

EXAMPLE PATTERN:
```python
@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 8080
    
    def __post_init__(self):
        if not 1024 <= self.port <= 65535:
            raise ValueError(f"Invalid port: {self.port}")

@dataclass
class DatabaseConfig:
    url: str
    pool_size: int = 5
    
    def __post_init__(self):
        if not self.url:
            raise ValueError("Database URL is required")

class ConfigLoader:
    @staticmethod
    def load(env: str = "dev") -> Config:
        # Load from environment-specific files
        # Validate all values
        # Return immutable config object
```
```

---

## 🧹 Medium Priority Improvements

### PROMPT 7: Break Up God Classes

**Objective**: Split large classes into focused, single-responsibility components.

**Files**: `enaam/mcp/handlers.py`, large classes throughout codebase

```
TASK: Refactor god classes into focused, single-responsibility components.

CURRENT ISSUES:
1. MCPHandler class handles routing, validation, formatting, and execution
2. Classes violate single responsibility principle
3. Hard to test and maintain large classes
4. Tight coupling within classes

REQUIREMENTS:
1. Split each large class into focused components
2. Each class should have single responsibility
3. Use composition over inheritance
4. Implement proper interfaces/protocols

IMPLEMENTATION APPROACH:
1. Identify responsibilities within large classes
2. Create separate classes for each responsibility
3. Define interfaces for communication between components
4. Use dependency injection to compose services
5. Ensure each class has single, clear purpose

CONSTRAINTS:
- Maintain existing public APIs
- No functionality changes
- Improved testability
- Clear separation of concerns

SUCCESS CRITERIA:
- Each class has single responsibility
- No class over 100 lines
- Easy to mock and test
- Clear interfaces between components

FILES TO MODIFY:
- enaam/mcp/handlers.py (split MCPHandler)
- enaam/mcp/request_validator.py (new)
- enaam/mcp/response_formatter.py (new)
- enaam/mcp/request_router.py (new)
- Other large classes as needed

EXAMPLE PATTERN:
```python
class RequestValidator:
    def validate(self, request: MCPRequest) -> None:
        # Only validation logic

class ResponseFormatter:
    def format(self, result: Dict, format_type: str) -> Dict:
        # Only formatting logic

class RequestRouter:
    def route(self, method: str) -> Callable:
        # Only routing logic

class MCPHandler:
    def __init__(self, validator: RequestValidator, 
                 formatter: ResponseFormatter, 
                 router: RequestRouter):
        # Composition of focused components
```
```

### PROMPT 8: Implement Consistent Error Types

**Objective**: Create a comprehensive error type system.

**Files**: All modules

```
TASK: Implement comprehensive error type system with proper inheritance hierarchy.

CURRENT ISSUES:
1. Mix of generic exceptions and return value errors
2. No consistent error format across modules
3. Hard to distinguish error types programmatically
4. Poor error debugging experience

REQUIREMENTS:
1. Create error type hierarchy with base classes
2. Implement error codes for programmatic handling
3. Add contextual information to all errors
4. Create error serialization for APIs

IMPLEMENTATION APPROACH:
1. Define base error classes with common attributes
2. Create domain-specific error types
3. Add error codes and categories
4. Implement error serialization/deserialization
5. Add error recovery strategies where appropriate

CONSTRAINTS:
- Backward compatible error handling
- Rich error context for debugging
- Consistent error format across all APIs
- Proper error logging

SUCCESS CRITERIA:
- Clear error type hierarchy
- Consistent error handling across all modules
- Rich error context for debugging
- Easy error handling for API consumers

FILES TO MODIFY:
- enaam/core/errors.py (new comprehensive error system)
- All modules (use proper error types)

EXAMPLE PATTERN:
```python
class EnaamError(Exception):
    def __init__(self, message: str, code: str = None, context: Dict = None):
        super().__init__(message)
        self.code = code
        self.context = context or {}

class ValidationError(EnaamError):
    def __init__(self, field: str, value: Any, message: str):
        super().__init__(f"Validation failed for {field}: {message}", 
                        code="VALIDATION_ERROR",
                        context={"field": field, "value": value})

class ConfigurationError(EnaamError):
    def __init__(self, key: str, message: str):
        super().__init__(f"Configuration error for {key}: {message}",
                        code="CONFIG_ERROR", 
                        context={"config_key": key})
```
```

---

## 🎯 Quick Win Prompts (1-2 hours each)

### PROMPT 9: Eliminate sys.path Manipulation

```
TASK: Remove ALL sys.path manipulation and fix imports.

Find and replace all instances of:
- sys.path.insert()
- sys.path.append()

Replace with proper relative imports or package installation.

FILES: All Python files
TIME: 1 hour
VALIDATION: grep -r "sys.path" should return no results
```

### PROMPT 10: Create Constants File

```
TASK: Extract all magic strings to constants.

1. Create enaam/core/constants.py
2. Find all string literals used as identifiers
3. Replace with named constants
4. Add type hints to constants

FILES: All Python files with string literals
TIME: 2 hours  
VALIDATION: Ruff magic literal checks should pass
```

### PROMPT 11: Add Type Hints

```
TASK: Add comprehensive type hints to all public methods.

1. Add type hints to all function signatures
2. Import necessary types from typing module
3. Use generics where appropriate
4. Add return type annotations

FILES: All Python files
TIME: 2 hours
VALIDATION: mypy --strict should pass
```

### PROMPT 12: Remove Global Logger

```
TASK: Eliminate global logger instance.

1. Remove global logger from enaam/core/logging.py
2. Update all imports to use dependency injection
3. Add logger parameter to all relevant functions
4. Use factory function for logger creation

FILES: enaam/core/logging.py, all files importing logger
TIME: 1 hour
VALIDATION: No global mutable state
```

### PROMPT 13: Fix Print Statements

```
TASK: Replace all print() calls with proper logging.

1. Find all print() statements
2. Replace with appropriate log levels
3. Add structured logging where useful
4. Remove debug prints

FILES: All Python files
TIME: 1 hour
VALIDATION: No print() calls in production code
```

---

## 🔒 Security Fix Prompts

### PROMPT 14: Fix Input Validation

```
TASK: Add comprehensive input validation to all external interfaces.

CURRENT ISSUES:
1. No input size limits in HTTP handlers
2. Unvalidated JSON parsing
3. No rate limiting

REQUIREMENTS:
1. Add request size limits
2. Validate all input parameters
3. Implement rate limiting
4. Sanitize error messages

FILES: enaam/mcp/server.py, all API endpoints
TIME: 4 hours
```

### PROMPT 15: Sanitize Error Messages

```
TASK: Prevent information leakage in error responses.

1. Create error message sanitizer
2. Remove internal details from external errors
3. Log full details internally
4. Return safe error messages to clients

FILES: All modules that return errors to external callers
TIME: 2 hours
```

---

## 📊 Validation Commands

After each refactoring session, run these commands to validate success:

```bash
# Code quality
ruff check enaam/ --fix
ruff format enaam/

# Type checking (after adding type hints)
mypy enaam/ --strict

# Security checks
bandit -r enaam/

# Test coverage
pytest enaam/tests/ --cov=enaam --cov-report=html

# Import validation
python -c "import enaam; print('Imports work!')"

# Architecture validation
python scripts/validate_architecture.py  # Create this script
```

---

## 🎯 Priority Order for Tomorrow

1. **Start with Critical Issues (Prompts 1-3)** - These break the system
2. **Then High Priority (Prompts 4-6)** - These make it maintainable  
3. **Pick Quick Wins (Prompts 9-13)** - These show immediate progress
4. **Security Fixes (Prompts 14-15)** - These make it production-ready
5. **Medium Priority (Prompts 7-8)** - These make it elegant

Each prompt is designed to be completed in 1-4 hours and can be tackled independently by any ADE.