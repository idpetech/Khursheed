"""
MCP Schemas - Data structures and validation for MCP server

Defines the request/response schemas for all MCP endpoints.
"""

from typing import Dict, Any, Optional, Union, Literal
from dataclasses import dataclass
from enum import Enum


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
    input: Dict[str, Any]


@dataclass
class BridgeRequest:
    """Request to run a Khursheed bridge function"""
    function_name: str
    params: Optional[Dict[str, Any]] = None


@dataclass
class ChatQueryRequest:
    """Request for chat-style query processing"""
    query: str
    context: Optional[Dict[str, Any]] = None


@dataclass
class EmailResponse:
    """Email-formatted response"""
    type: Literal["email"] = "email"
    subject: str = ""
    body: str = ""
    to: Optional[str] = None
    priority: str = "normal"


@dataclass
class ChatResponse:
    """Chat-formatted response"""
    type: Literal["chat"] = "chat"
    message: str = ""
    suggestions: Optional[list] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class JSONResponse:
    """JSON-formatted response"""
    type: Literal["json"] = "json"
    data: Dict[str, Any] = None
    status: str = "success"
    source: str = "enaam"


def validate_mcp_request(data: Dict[str, Any]) -> MCPRequest:
    """Validate and convert incoming MCP request"""
    method = data.get("method")
    if not method:
        raise ValueError("Missing 'method' field")
    
    if method not in [m.value for m in MCPMethod]:
        raise ValueError(f"Unknown method: {method}")
    
    params = data.get("params", {})
    response_type = ResponseType(data.get("response_type", "json"))
    request_id = data.get("id")
    
    return MCPRequest(
        method=method,
        params=params,
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


def create_chat_response(message: str, suggestions: Optional[list] = None, metadata: Optional[Dict[str, Any]] = None) -> ChatResponse:
    """Create chat-formatted response"""
    return ChatResponse(
        message=message,
        suggestions=suggestions,
        metadata=metadata
    )


def create_json_response(data: Dict[str, Any], status: str = "success", source: str = "enaam") -> JSONResponse:
    """Create JSON-formatted response"""
    return JSONResponse(
        data=data,
        status=status,
        source=source
    )