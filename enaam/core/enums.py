"""
Enums for Enaam system - Replace magic strings with type-safe enums

This module defines all method names, function names, and other string
constants as enums to ensure type safety and eliminate magic strings.
"""

from enum import Enum


class BridgeFunction(str, Enum):
    """Available Khursheed bridge functions"""
    EMAIL_SUMMARY = "email_summary"
    LEAD_SCAN = "lead_scan"
    WEEKLY_DIGEST = "weekly_digest"
    EXECUTIVE_SUMMARY = "executive_summary"
    RUN_SCHEDULED_TASKS = "run_scheduled_tasks"
    WEEKLY_MONDAY_9AM_DIGEST = "weekly_monday_9am_digest"
    LEAD_GENERATION_RUN = "lead_generation_run"
    EMAIL_TRIAGE_RUN = "email_triage_run"
    GET_EXECUTION_LOGS = "get_execution_logs"


class SkillName(str, Enum):
    """Available skills from Khursheed manager"""
    SIFTER = "sifter"
    LEAD_SCOUT = "lead_scout"
    ECHO = "echo"
    TIMESTAMP = "timestamp"


class ActionType(str, Enum):
    """Action types for router classification"""
    EMAIL_SUMMARY = "email_summary"
    LEAD_SCAN = "lead_scan"
    WEEKLY_DIGEST = "weekly_digest"
    EXECUTIVE_SUMMARY = "executive_summary"
    RUN_SCHEDULED_TASKS = "run_scheduled_tasks"
    WEEKLY_MONDAY_9AM_DIGEST = "weekly_monday_9am_digest"
    LEAD_GENERATION_RUN = "lead_generation_run"
    EMAIL_TRIAGE_RUN = "email_triage_run"
    HANDLE_GENERAL = "handle_general"


class IntentType(str, Enum):
    """Intent classification types"""
    KHURSHEED_BRIDGE = "khursheed_bridge"
    GENERAL = "general"


class HandlerType(str, Enum):
    """Handler types for request routing"""
    KHURSHEED_BRIDGE = "khursheed_bridge"
    GENERAL = "general"
    UNKNOWN = "unknown"


class ResponseStatus(str, Enum):
    """Response status values"""
    SUCCESS = "success"
    ERROR = "error"
    UNKNOWN = "unknown"


class SourceType(str, Enum):
    """Source types for responses"""
    ENAAM = "enaam"
    KHURSHEED = "khursheed"


class ValidationFields(str, Enum):
    """Common validation field names"""
    METHOD = "method"
    SKILL_NAME = "skill_name"
    FUNCTION_NAME = "function_name"
    QUERY = "query"
    RESPONSE_TYPE = "response_type"


class ValidationConstraints(str, Enum):
    """Common validation constraint messages"""
    REQUIRED = "required"
    MUST_BE_ONE_OF = "must be one of"


class LogLevel(str, Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EmailSubjects(str, Enum):
    """Email subject templates"""
    WEEKLY_DIGEST = "Weekly Executive Summary"
    WEEKLY_MONDAY_DIGEST = "Weekly Monday Digest"
    EXECUTIVE_SUMMARY = "Daily Executive Summary"
    LEAD_SCAN = "Lead Discovery Results"
    LEAD_GENERATION = "Lead Generation Report"
    EMAIL_SUMMARY = "Email Triage Summary"
    EMAIL_TRIAGE = "Email Processing Report"
    SCHEDULED_TASKS = "Scheduled Tasks Completed"


class ErrorMessages(str, Enum):
    """Common error message templates"""
    MISSING_METHOD = "Missing request method"
    MISSING_SKILL_NAME = "Missing 'skill_name' parameter"
    MISSING_FUNCTION_NAME = "Missing 'function_name' parameter"
    MISSING_QUERY = "Missing 'query' parameter"
    UNKNOWN_SKILL = "Unknown skill"
    UNKNOWN_BRIDGE_FUNCTION = "Unknown bridge function"
    UNKNOWN_METHOD = "Unsupported method"
    UNKNOWN_RESPONSE_TYPE = "Unknown response type"
    REQUEST_HANDLING_FAILED = "Request handling failed"


class EnvironmentKeys(str, Enum):
    """Environment variable keys"""
    GMAIL_EMAIL = "GMAIL_EMAIL"
    GMAIL_PASSWORD = "GMAIL_PASSWORD"
    SUMMARY_TO = "SUMMARY_TO"
    ENAAM_LOG_LEVEL = "ENAAM_LOG_LEVEL"
    OPENAI_API_KEY = "OPENAI_API_KEY"
    TAVILY_API_KEY = "TAVILY_API_KEY"


class TaskNames(str, Enum):
    """Task execution names"""
    ENAAM_EMAIL_CHECK = "enaam-email-check"
    ENAAM_LEAD_GENERATION = "enaam-lead-generation"
    ENAAM_EMAIL_TRIAGE = "enaam-email-triage"
    ENAAM_LEAD_SCAN = "enaam-lead-scan"


class DefaultQueries(str, Enum):
    """Default search queries"""
    FRACTIONAL_CTO_JACKSONVILLE = "Fractional CTO roles in Jacksonville"
    WAREHOUSE_OPTIMIZATION = "Warehouse optimization consulting"


class FileNames(str, Enum):
    """Common file names"""
    TASKS_JSON = "tasks.json"
    KHURSHEED_DB = "khursheed.db"
    ENAAM_LOG = "enaam.log"


class HTTPMethods(str, Enum):
    """HTTP method names"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class ContentTypes(str, Enum):
    """HTTP content types"""
    APPLICATION_JSON = "application/json"
    TEXT_HTML = "text/html"
    TEXT_PLAIN = "text/plain"


class ServerEndpoints(str, Enum):
    """Server endpoint paths"""
    ROOT = "/"
    HEALTH = "/health"


class ServerMessages(str, Enum):
    """Server status messages"""
    STARTING = "Starting Enaam MCP Server"
    HEALTH_PASSED = "Server health check passed"
    HEALTH_FAILED = "Server health check failed"
    CANNOT_CONNECT = "Cannot connect to server"
    STOPPING = "Stopping server"


class TestMessages(str, Enum):
    """Test output messages"""
    TESTING = "Testing Enaam MCP Server"
    TEST_CASE = "Test"
    SUCCESS_EMOJI = "✅ Success"
    FAILED_EMOJI = "❌ Failed"
    REQUEST_FAILED = "Request failed"


class DataFields(str, Enum):
    """Common data field names"""
    SUMMARY = "summary"
    MESSAGE = "message"
    ERROR = "error"
    STATUS = "status"
    ACTION = "action"
    SOURCE = "source"
    DATA = "data"
    NEXT_STEPS = "next_steps"
    RESULT = "result"
    METHOD = "method"
    PARAMS = "params"
    RESPONSE_TYPE = "response_type"
    ID = "id"
    QUERIES = "queries"
    INPUT = "input"
    CONTEXT = "context"
    SUBJECT = "subject"
    BODY = "body"
    TO = "to"
    SUGGESTIONS = "suggestions"
    METADATA = "metadata"
    EXECUTION_TIME_MS = "execution_time_ms"
    EMAILS_PROCESSED = "emails_processed"
    EXPENSES_EXTRACTED = "expenses_extracted"
    EMAIL_SENT = "email_sent"
    RECIPIENT = "recipient"
    NOTE = "note"
    TASKS_EXECUTED = "tasks_executed"
    RECENT_RUNS = "recent_runs"
    FUNCTION_STATS = "function_stats"
    TOTAL_RUNS = "total_runs"
    TRIAGE_SUMMARY = "triage_summary"
    EXPENSE_SUMMARY = "expense_summary"
    SKILL_NAME = "skill_name"
    FUNCTION_NAME = "function_name"
    QUERY = "query"