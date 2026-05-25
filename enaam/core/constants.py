"""
Constants for Enaam system - Configuration keys and default values

This module defines all configuration constants to eliminate magic strings
in configuration access and provide centralized constant management.

This file consolidates magic strings that aren't appropriate for enums
but should still be centralized as constants.
"""

from enum import Enum
from pathlib import Path
from typing import Final, Dict, List


class ConfigKey(str, Enum):
    """Configuration key paths using dot notation"""
    # Agent configuration
    AGENT_NAME = "agent.name"
    AGENT_VERSION = "agent.version"
    AGENT_MODE = "agent.mode"
    
    # Khursheed integration
    KHURSHEED_ENABLED = "khursheed.enabled"
    KHURSHEED_PRESERVE_CRON = "khursheed.preserve_cron"
    KHURSHEED_DATABASE_PATH = "khursheed.database_path"
    KHURSHEED_TASKS_PATH = "khursheed.tasks_path"
    
    # MCP configuration
    MCP_ENABLED = "mcp.enabled"
    MCP_SERVER_PORT = "mcp.server_port"
    MCP_TOOLS_ENABLED = "mcp.tools_enabled"
    
    # Logging configuration
    LOGGING_LEVEL = "logging.level"
    LOGGING_FILE = "logging.file"
    
    # API configuration
    API_OPENAI_KEY = "api.openai_key"
    API_TAVILY_KEY = "api.tavily_key"


class DefaultValues:
    """Default configuration values"""
    
    # Agent defaults
    AGENT_NAME = "Enaam"
    AGENT_VERSION = "1.0.0"
    AGENT_MODE = "chief_of_staff"
    
    # Khursheed defaults
    KHURSHEED_ENABLED = True
    KHURSHEED_PRESERVE_CRON = True
    
    # Chat and conversation defaults
    CHAT_SESSION_TIMEOUT = 3600  # 1 hour in seconds
    MAX_CONVERSATION_HISTORY = 100  # Maximum turns to keep in memory
    CONTEXT_MEMORY_LIMIT = 50  # Maximum context items to remember
    
    # MCP defaults
    MCP_ENABLED = False
    MCP_SERVER_PORT = 8080
    MCP_TOOLS_ENABLED = []
    
    # Logging defaults
    LOGGING_LEVEL = "INFO"
    
    # Server defaults
    SERVER_HOST = "localhost"
    SERVER_PORT = 8080
    TIMEOUT_SECONDS = 5
    
    # Response limits
    MAX_SUMMARY_PREVIEW = 100
    MAX_MESSAGE_PREVIEW = 100
    MAX_SUGGESTIONS = 3
    
    # Email defaults
    EMAIL_PRIORITY_NORMAL = "normal"
    
    # HTTP defaults
    HTTP_STATUS_OK = 200
    
    # Execution defaults
    DEFAULT_LOG_LIMIT = 10


class PathConstants:
    """File and directory path constants"""
    
    # Directory names
    DATA_DIR_NAME: Final[str] = "data"
    LOGS_DIR_NAME: Final[str] = "logs" 
    CONFIG_DIR_NAME: Final[str] = "config"
    
    @staticmethod
    def get_base_dir() -> Path:
        """Get base directory path"""
        return Path(__file__).parent.parent.parent
    
    @staticmethod
    def get_data_dir() -> Path:
        """Get data directory path"""
        return PathConstants.get_base_dir() / PathConstants.DATA_DIR_NAME
    
    @staticmethod
    def get_logs_dir() -> Path:
        """Get logs directory path"""
        return PathConstants.get_base_dir() / PathConstants.LOGS_DIR_NAME
    
    @staticmethod
    def get_config_dir() -> Path:
        """Get config directory path"""
        return PathConstants.get_base_dir() / PathConstants.CONFIG_DIR_NAME
    
    @staticmethod
    def get_khursheed_db_path() -> Path:
        """Get Khursheed database path"""
        return PathConstants.get_base_dir() / "khursheed.db"
    
    @staticmethod
    def get_tasks_path() -> Path:
        """Get tasks.json path"""
        return PathConstants.get_base_dir() / "tasks.json"
    
    @staticmethod
    def get_enaam_log_path() -> Path:
        """Get Enaam log file path"""
        return PathConstants.get_logs_dir() / "enaam.log"


class URLConstants:
    """URL and endpoint constants"""
    
    @staticmethod
    def get_server_url(host: str = DefaultValues.SERVER_HOST, port: int = DefaultValues.SERVER_PORT) -> str:
        """Get server URL"""
        return f"http://{host}:{port}"
    
    @staticmethod
    def get_health_url(host: str = DefaultValues.SERVER_HOST, port: int = DefaultValues.SERVER_PORT) -> str:
        """Get health check URL"""
        return f"http://{host}:{port}/health"


class ValidationMessages:
    """Validation error message templates"""
    
    # Generic validation messages (sanitized for security)
    INVALID_REQUEST: Final[str] = "Invalid request format"
    REQUEST_TOO_LARGE: Final[str] = "Request size exceeds limit"
    RATE_LIMIT_EXCEEDED: Final[str] = "Rate limit exceeded, please try again later"
    INVALID_JSON: Final[str] = "Invalid JSON format"
    MISSING_REQUIRED_FIELD: Final[str] = "Missing required field"
    INVALID_PARAMETER: Final[str] = "Invalid parameter value"
    UNSUPPORTED_METHOD: Final[str] = "Unsupported method"
    INTERNAL_SERVER_ERROR: Final[str] = "Internal server error"
    
    @staticmethod
    def unknown_skill(skill_name: str, available_skills: list[str]) -> str:
        """Generate unknown skill error message"""
        # Sanitize skill name to prevent injection
        safe_skill = str(skill_name)[:50] if skill_name else "unknown"
        return f"Unknown skill: {safe_skill}, must be one of: {', '.join(available_skills)}"
    
    @staticmethod
    def unknown_bridge_function(function_name: str, available_functions: list[str]) -> str:
        """Generate unknown bridge function error message"""
        # Sanitize function name to prevent injection
        safe_function = str(function_name)[:50] if function_name else "unknown"
        return f"Unknown bridge function: {safe_function}, must be one of: {', '.join(available_functions)}"
    
    @staticmethod
    def unsupported_method(method: str) -> str:
        """Generate unsupported method error message"""
        # Sanitize method name to prevent injection
        safe_method = str(method)[:50] if method else "unknown"
        return f"Unsupported method: {safe_method}"
    
    @staticmethod
    def unknown_response_type(response_type: str) -> str:
        """Generate unknown response type error message"""
        # Sanitize response type to prevent injection
        safe_type = str(response_type)[:20] if response_type else "unknown"
        return f"Unknown response type: {safe_type}, must be one of: json, email, chat"
    
    @staticmethod
    def field_too_long(field_name: str, max_length: int) -> str:
        """Generate field too long error message"""
        safe_field = str(field_name)[:20] if field_name else "field"
        return f"Field '{safe_field}' exceeds maximum length of {max_length}"
    
    @staticmethod
    def array_too_long(field_name: str, max_length: int) -> str:
        """Generate array too long error message"""
        safe_field = str(field_name)[:20] if field_name else "array"
        return f"Array '{safe_field}' exceeds maximum length of {max_length}"
    
    @staticmethod
    def object_too_deep() -> str:
        """Generate object too deep error message"""
        return "JSON object nesting exceeds maximum depth"


class TaskConstants:
    """Task-related constants"""
    
    # Default lead generation queries
    DEFAULT_LEAD_QUERIES = [
        "Fractional CTO roles in Jacksonville",
        "Warehouse optimization consulting"
    ]
    
    # Common next steps
    EMAIL_NEXT_STEPS = ["Review flagged emails", "Process expense items"]
    LEAD_NEXT_STEPS = ["Review discovered leads", "Prioritize outreach", "Update CRM"]
    WEEKLY_DIGEST_NEXT_STEPS = ["Review weekly summary", "Plan upcoming tasks"]
    EXECUTIVE_SUMMARY_NEXT_STEPS = ["Review daily activities", "Plan next actions"]
    SCHEDULED_TASKS_NEXT_STEPS = ["Review task results", "Generate executive summary"]
    LEAD_GENERATION_NEXT_STEPS = ["Review discovered leads", "Qualify prospects", "Update CRM", "Plan outreach"]
    EMAIL_TRIAGE_NEXT_STEPS = ["Review flagged emails", "Process expenses", "Update financial records", "Respond to urgent messages"]
    WEEKLY_MONDAY_NEXT_STEPS = ["Check email for delivery", "Review weekly summary"]
    EXECUTION_LOGS_NEXT_STEPS = ["Review execution patterns", "Analyze performance metrics"]


class EmailConstants:
    """Email-related constants"""
    
    # Subject templates
    SUBJECT_TEMPLATES = {
        "weekly_digest": "Weekly Executive Summary",
        "weekly_monday_9am_digest": "Weekly Monday Digest", 
        "executive_summary": "Daily Executive Summary",
        "lead_scan": "Lead Discovery Results",
        "lead_generation_run": "Lead Generation Report",
        "email_summary": "Email Triage Summary",
        "email_triage_run": "Email Processing Report",
        "run_scheduled_tasks": "Scheduled Tasks Completed"
    }
    
    # Status emojis
    SUCCESS_EMOJI = "✅"
    ERROR_EMOJI = "❌"
    
    # Default subject for unknown actions
    DEFAULT_SUBJECT_PREFIX = "Enaam Report"


class ServerConstants:
    """Server-related constants"""
    
    # Unicode emojis for server output
    ROCKET_EMOJI = "🚀"
    CHECK_EMOJI = "✅"
    CROSS_EMOJI = "❌"
    BULB_EMOJI = "💡"
    KEYBOARD_EMOJI = "⌨️"
    STOP_EMOJI = "🛑"
    TEST_EMOJI = "🧪"
    CLIPBOARD_EMOJI = "📋"
    
    # Server startup messages
    STARTUP_MESSAGE_TEMPLATE = "{emoji} Starting Enaam MCP Server on {host}:{port}..."
    TEST_MESSAGE_TEMPLATE = "{emoji} Testing Enaam MCP Server at {url}"
    
    # Sample curl command template
    CURL_TEMPLATE = """curl -X POST http://localhost:8080/ \\
    -H 'Content-Type: application/json' \\
    -d '{{"method": "run_weekly_digest", "params": {{}}, "response_type": "json"}}'"""


class APIConstants:
    """API and service related constants"""
    
    # HTTP headers
    CONTENT_TYPE_HEADER: Final[str] = "Content-Type"
    ACCEPT_HEADER: Final[str] = "Accept"
    ACCESS_CONTROL_ALLOW_HEADERS: Final[str] = "Access-Control-Allow-Headers"
    ACCESS_CONTROL_ALLOW_METHODS: Final[str] = "Access-Control-Allow-Methods"
    
    # Content types
    APPLICATION_JSON: Final[str] = "application/json"
    TEXT_HTML: Final[str] = "text/html"
    TEXT_PLAIN: Final[str] = "text/plain"
    
    # HTTP timeout values
    DEFAULT_HTTP_TIMEOUT: Final[int] = 30
    HEALTH_CHECK_TIMEOUT: Final[int] = 5
    SERVER_STOP_TIMEOUT: Final[int] = 5
    
    # Request validation limits
    MAX_REQUEST_SIZE: Final[int] = 10 * 1024 * 1024  # 10MB
    MAX_JSON_DEPTH: Final[int] = 32
    MAX_STRING_LENGTH: Final[int] = 100000  # 100KB
    MAX_ARRAY_LENGTH: Final[int] = 1000
    MAX_PARAMS_COUNT: Final[int] = 50
    
    # Rate limiting
    MAX_REQUESTS_PER_MINUTE: Final[int] = 60
    RATE_LIMIT_WINDOW: Final[int] = 60  # seconds
    RATE_LIMIT_BURST: Final[int] = 10
    
    # CORS headers values
    CORS_ALLOW_METHODS: Final[str] = "PUT, OPTIONS, DELETE"
    CORS_ALLOW_HEADERS_BASIC: Final[str] = "Content-Type"
    CORS_ALLOW_HEADERS_XSRF: Final[str] = "X-Xsrftoken, Content-Type"


class MagicStringConstants:
    """
    Magic string constants that appear frequently in the codebase.
    These are not enums because they represent literal values used in various contexts.
    """
    
    # Network and server constants
    LOCALHOST: Final[str] = "localhost"
    LOCAL_HOST_IP: Final[str] = "127.0.0.1"
    
    # Common status values (complement ResponseStatus enum for literal usage)
    SUCCESS_LITERAL: Final[str] = "success"
    ERROR_LITERAL: Final[str] = "error"
    UNKNOWN_LITERAL: Final[str] = "unknown"
    HEALTHY_LITERAL: Final[str] = "healthy"
    
    
    # Method names (complement MCPMethod enum)
    METHOD_LITERAL: Final[str] = "method"
    CHAT_QUERY_LITERAL: Final[str] = "chat_query"
    RUN_WEEKLY_DIGEST_LITERAL: Final[str] = "run_weekly_digest"
    RUN_BRIDGE_LITERAL: Final[str] = "run_bridge"
    
    # Response type literals (complement ResponseType enum)
    JSON_LITERAL: Final[str] = "json"
    EMAIL_LITERAL: Final[str] = "email"
    CHAT_LITERAL: Final[str] = "chat"
    RESPONSE_TYPE_LITERAL: Final[str] = "response_type"
    
    # Data field literals (complement DataFields enum)
    STATUS_LITERAL: Final[str] = "status"
    RESULT_LITERAL: Final[str] = "result"
    ERROR_LITERAL: Final[str] = "error"
    DATA_LITERAL: Final[str] = "data"
    MESSAGE_LITERAL: Final[str] = "message"
    SUMMARY_LITERAL: Final[str] = "summary"
    SUBJECT_LITERAL: Final[str] = "subject"
    BODY_LITERAL: Final[str] = "body"
    SOURCE_LITERAL: Final[str] = "source"
    
    # Source values (complement SourceType enum)
    ENAAM_LITERAL: Final[str] = "enaam"
    KHURSHEED_LITERAL: Final[str] = "khursheed"
    
    # Command line arguments
    START_COMMAND: Final[str] = "start"
    TEST_COMMAND: Final[str] = "test"
    HELP_COMMAND: Final[str] = "help"
    STOP_COMMAND: Final[str] = "stop"
    
    # Special identifiers
    MAIN_MODULE: Final[str] = "__main__"
    
    # Default values for missing data
    NOT_AVAILABLE: Final[str] = "N/A"
    NORMAL_PRIORITY: Final[str] = "normal"
    
    # Logging context names
    MCP_HANDLERS_CONTEXT: Final[str] = "mcp_handlers"
    MCP_SERVER_CONTEXT: Final[str] = "mcp_server"
    KHURSHEED_BRIDGE_CONTEXT: Final[str] = "khursheed_bridge"


class DatabaseConstants:
    """Database-related constants and queries"""
    
    # SQLite constants
    CHECK_SAME_THREAD_FALSE: Final[str] = "check_same_thread"
    PRAGMA_FOREIGN_KEYS: Final[str] = "PRAGMA foreign_keys = ON"
    PRAGMA_JOURNAL_MODE_WAL: Final[str] = "PRAGMA journal_mode=WAL"
    PRAGMA_SYNCHRONOUS_NORMAL: Final[str] = "PRAGMA synchronous=NORMAL"
    
    # Connection and transaction settings
    DEFERRED_ISOLATION: Final[str] = "DEFERRED"
    WAL_MODE: Final[str] = "WAL"
    NORMAL_SYNC: Final[str] = "NORMAL"
    DEFAULT_TIMEOUT: Final[float] = 30.0
    
    # Table creation queries
    CREATE_ENAAM_RUNS_TABLE: Final[str] = """
        CREATE TABLE IF NOT EXISTS enaam_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            function_name TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            input_data TEXT,
            output_summary TEXT,
            execution_time_ms INTEGER,
            error_message TEXT
        )
    """
    
    CREATE_TIMESTAMP_INDEX: Final[str] = """
        CREATE INDEX IF NOT EXISTS idx_timestamp 
        ON enaam_runs(timestamp)
    """
    
    CREATE_FUNCTION_NAME_INDEX: Final[str] = """
        CREATE INDEX IF NOT EXISTS idx_function_name 
        ON enaam_runs(function_name)
    """
    
    # Insert and select queries
    INSERT_ENAAM_RUN: Final[str] = """
        INSERT INTO enaam_runs (
            timestamp, function_name, source, status,
            input_data, output_summary, execution_time_ms, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    SELECT_RECENT_RUNS: Final[str] = """
        SELECT id, timestamp, function_name, source, status, 
               output_summary, execution_time_ms, error_message
        FROM enaam_runs
        ORDER BY timestamp DESC
        LIMIT ?
    """
    
    SELECT_FUNCTION_STATS: Final[str] = """
        SELECT function_name, COUNT(*) as count,
               SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes,
               SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
               AVG(execution_time_ms) as avg_time_ms
        FROM enaam_runs
        GROUP BY function_name
        ORDER BY count DESC
    """
    
    # Common query patterns
    SELECT_ALL: Final[str] = "SELECT * FROM {table}"
    INSERT_OR_REPLACE: Final[str] = "INSERT OR REPLACE INTO {table} {fields} VALUES {values}"
    COUNT_QUERY: Final[str] = "SELECT COUNT(*) FROM {table}"
    
    # Database filenames
    ENAAM_RUNS_DB: Final[str] = "enaam_runs.db"


class TestConstants:
    """Constants used in testing"""
    
    # Test identifiers
    TEST_REQUEST_ID: Final[str] = "test-1"
    TEST_SUCCESS_ID: Final[str] = "test-success"
    TEST_ERROR_ID: Final[str] = "test-error"
    
    # Test queries and data
    TEST_QUERY: Final[str] = "What are my priorities this week?"
    TEST_SKILL_NAME: Final[str] = "echo"
    TEST_FUNCTION_NAME: Final[str] = "weekly_digest"
    
    # Test server endpoints
    HEALTH_CHECK_PATH: Final[str] = "/health"
    ROOT_PATH: Final[str] = "/"


class CLIConstants:
    """Command line interface constants"""
    
    # Help and usage text fragments
    HOST_OPTION: Final[str] = "--host"
    PORT_OPTION: Final[str] = "--port"
    TEST_OPTION: Final[str] = "--test"
    HELP_OPTION: Final[str] = "--help"
    
    # Default values for CLI
    DEFAULT_HOST: Final[str] = "localhost"
    DEFAULT_PORT: Final[int] = 8080


class MessageTemplates:
    """Message templates with placeholders"""
    
    # Server status messages
    STARTING_SERVER: Final[str] = "Starting Enaam MCP Server on {host}:{port}..."
    TESTING_SERVER: Final[str] = "Testing Enaam MCP Server at {url}"
    SERVER_ERROR: Final[str] = "Server error: {error}"
    REQUEST_FAILED: Final[str] = "Request failed: {error}"
    
    # Test output templates  
    TEST_CASE: Final[str] = "Test {i}: {method} ({response_type})"
    TEST_RESULT: Final[str] = "Status: {status}"
    
    # Email templates
    EMAIL_SUBJECT: Final[str] = "Subject: {subject}"
    EMAIL_PREVIEW: Final[str] = "Body preview: {preview}..."
    
    # Response templates
    RESPONSE_SUMMARY: Final[str] = "Summary: {summary}"
    RESPONSE_MESSAGE: Final[str] = "Message: {message}"


class RegexPatterns:
    """Regular expression patterns used throughout the codebase"""
    
    # File path patterns
    FILE_PATH_PATTERN: Final[str] = r'/[^\s]+'
    
    # Credential patterns (for sanitization)
    PASSWORD_PATTERN: Final[str] = r'password[=:]\s*[^\s]+'
    TOKEN_PATTERN: Final[str] = r'token[=:]\s*[^\s]+'
    KEY_PATTERN: Final[str] = r'key[=:]\s*[^\s]+'
    SECRET_PATTERN: Final[str] = r'secret[=:]\s*[^\s]+'
    AUTH_PATTERN: Final[str] = r'auth[=:]\s*[^\s]+'
    
    # Replacement values for sanitization
    PASSWORD_REPLACEMENT: Final[str] = "password=<hidden>"
    TOKEN_REPLACEMENT: Final[str] = "token=<hidden>"
    KEY_REPLACEMENT: Final[str] = "key=<hidden>"
    SECRET_REPLACEMENT: Final[str] = "secret=<hidden>"
    AUTH_REPLACEMENT: Final[str] = "auth=<hidden>"
    
    # Input validation patterns
    ALPHANUMERIC_PATTERN: Final[str] = r'^[a-zA-Z0-9_-]+$'
    METHOD_NAME_PATTERN: Final[str] = r'^[a-zA-Z][a-zA-Z0-9_]*$'
    SKILL_NAME_PATTERN: Final[str] = r'^[a-zA-Z][a-zA-Z0-9_]*$'
    FUNCTION_NAME_PATTERN: Final[str] = r'^[a-zA-Z][a-zA-Z0-9_]*$'


class HelpConstants:
    """Help text and documentation constants"""
    
    HELP_TEXT = """
Enaam MCP Server - Chief of Staff AI Assistant

USAGE:
    python -m enaam.mcp_server [OPTIONS]

OPTIONS:
    --host HOST     Server host (default: localhost)
    --port PORT     Server port (default: 8080)
    --test         Run server tests
    --help         Show this help

AVAILABLE METHODS:
    run_weekly_digest    - Generate weekly executive summary
    run_lead_scan        - Discover new business leads
    chat_query          - Process conversational queries
    run_bridge          - Execute Khursheed bridge functions

RESPONSE TYPES:
    json    - Structured JSON response (default)
    email   - Email-formatted response
    chat    - Chat-formatted response

EXAMPLES:
    # Start server
    python -m enaam.mcp_server

    # Start on custom port
    python -m enaam.mcp_server --port 9000

    # Run tests
    python -m enaam.mcp_server --test

    # Sample request
    curl -X POST http://localhost:8080/ \\
      -H 'Content-Type: application/json' \\
      -d '{
        "method": "chat_query",
        "params": {"query": "What are my priorities this week?"},
        "response_type": "chat"
      }'
"""