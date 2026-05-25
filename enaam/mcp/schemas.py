"""
MCP Schemas - Data structures and validation for MCP server

Defines the request/response schemas for all MCP endpoints.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
from typing import Literal

from ..core.constants import MagicStringConstants, ValidationMessages, APIConstants
from ..core.enums import DataFields, ResponseStatus, SourceType
from ..core.exceptions import ValidationError


class ResponseType(str, Enum):
    """Response format types"""
    JSON = "json"
    EMAIL = "email"
    CHAT = "chat"


class MCPMethod(str, Enum):
    """Available MCP methods"""
    RUN_SKILL = "run_skill"
    RUN_BRIDGE = "run_bridge" 
    RUN_WEEKLY_DIGEST = "run_weekly_digest"
    RUN_LEAD_SCAN = "run_lead_scan"
    CHAT_QUERY = "chat_query"


@dataclass
class MCPRequest:
    """Base MCP request structure"""
    method: str
    params: Dict[str, Any]
    response_type: ResponseType = ResponseType.JSON
    id: Optional[str] = None


@dataclass
class MCPResponse:
    """Base MCP response structure"""
    id: Optional[str]
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class SkillRequest:
    """Request to run a specific skill"""
    skill_name: str
    input: dict[str, Any]


@dataclass
class BridgeRequest:
    """Request to run a Khursheed bridge function"""
    function_name: str
    params: dict[str, Any] | None = None


@dataclass
class ChatQueryRequest:
    """Request for chat-style query processing"""
    query: str
    context: dict[str, Any] | None = None


@dataclass
class EmailResponse:
    """Email-formatted response"""
    type: Literal["email"] = MagicStringConstants.EMAIL_LITERAL
    subject: str = ""
    body: str = ""
    to: str | None = None
    priority: str = MagicStringConstants.NORMAL_PRIORITY


@dataclass
class ChatResponse:
    """Chat-formatted response"""
    type: Literal["chat"] = MagicStringConstants.CHAT_LITERAL
    message: str = ""
    suggestions: list | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class JSONResponse:
    """JSON-formatted response"""
    type: Literal["json"] = MagicStringConstants.JSON_LITERAL
    data: Optional[Dict[str, Any]] = None
    status: str = ResponseStatus.SUCCESS.value
    source: str = SourceType.ENAAM.value


def validate_mcp_request(data: Dict[str, Any]) -> MCPRequest:
    """Validate and convert incoming MCP request with enhanced security checks"""
    if not isinstance(data, dict):
        raise ValidationError(ValidationMessages.INVALID_REQUEST)
    
    # Validate required method field
    method = data.get(DataFields.METHOD.value)
    if not method:
        raise ValidationError(ValidationMessages.MISSING_REQUIRED_FIELD)
    
    if not isinstance(method, str):
        raise ValidationError("Method must be a string")
    
    if len(method) > 50:
        raise ValidationError("Method name too long")
    
    if method not in [m.value for m in MCPMethod]:
        raise ValidationError(ValidationMessages.unsupported_method(method))
    
    # Validate params
    params = data.get(DataFields.PARAMS.value, {})
    if params is not None and not isinstance(params, dict):
        raise ValidationError("Params must be an object")
    
    if isinstance(params, dict) and len(params) > APIConstants.MAX_PARAMS_COUNT:
        raise ValidationError(f"Params exceed maximum count of {APIConstants.MAX_PARAMS_COUNT}")
    
    # Validate response type
    response_type_str = data.get(DataFields.RESPONSE_TYPE.value, MagicStringConstants.JSON_LITERAL)
    if not isinstance(response_type_str, str):
        raise ValidationError("Response type must be a string")
    
    if response_type_str not in [rt.value for rt in ResponseType]:
        raise ValidationError(ValidationMessages.unknown_response_type(response_type_str))
    
    response_type = ResponseType(response_type_str)
    
    # Validate optional request ID
    request_id = data.get(DataFields.ID.value)
    if request_id is not None:
        if not isinstance(request_id, str):
            raise ValidationError("Request ID must be a string")
        if len(request_id) > 100:
            raise ValidationError("Request ID too long")
    
    return MCPRequest(
        method=method,
        params=params or {},
        response_type=response_type,
        id=request_id
    )


def create_mcp_response(request_id: Optional[str], result: Any = None, error: Any = None) -> MCPResponse:
    """Create standardized MCP response"""
    return MCPResponse(
        id=request_id,
        result=result,
        error=error
    )


def create_email_response(subject: str, body: str, to: Optional[str] = None) -> EmailResponse:
    """Create email-formatted response"""
    return EmailResponse(
        subject=subject,
        body=body,
        to=to
    )


def create_chat_response(message: str, suggestions: Optional[List] = None, metadata: Optional[Dict[str, Any]] = None) -> ChatResponse:
    """Create chat-formatted response"""
    return ChatResponse(
        message=message,
        suggestions=suggestions,
        metadata=metadata
    )


def create_json_response(data: Dict[str, Any], status: str = ResponseStatus.SUCCESS.value, source: str = SourceType.ENAAM.value) -> JSONResponse:
    """Create JSON-formatted response"""
    return JSONResponse(
        data=data,
        status=status,
        source=source
    )