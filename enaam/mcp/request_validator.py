"""
MCP Request Validator - Focused validation logic

Handles parameter validation, method validation, and constraint checking.
Single responsibility: Request validation only.
"""

from typing import Any, Dict, List

from ..core.enums import (
    BridgeFunction,
    SkillName,
    ValidationFields,
    ErrorMessages,
    DataFields,
)
from ..core.constants import ValidationMessages
from ..core.exceptions import ValidationError
from .schemas import MCPRequest, ResponseType, MCPMethod


class RequestValidator:
    """
    Validates MCP requests with focused responsibility.
    
    Only handles validation logic - no routing, formatting, or execution.
    """
    
    def __init__(self):
        """Initialize validator with available skills and functions."""
        self._available_skills = {
            SkillName.SIFTER.value,
            SkillName.LEAD_SCOUT.value,
            SkillName.ECHO.value,
            SkillName.TIMESTAMP.value,
        }
        
        self._available_bridge_functions = {
            BridgeFunction.EMAIL_SUMMARY.value,
            BridgeFunction.LEAD_SCAN.value,
            BridgeFunction.WEEKLY_DIGEST.value,
            BridgeFunction.EXECUTIVE_SUMMARY.value,
            BridgeFunction.RUN_SCHEDULED_TASKS.value,
            BridgeFunction.WEEKLY_MONDAY_9AM_DIGEST.value,
            BridgeFunction.LEAD_GENERATION_RUN.value,
            BridgeFunction.EMAIL_TRIAGE_RUN.value,
            BridgeFunction.GET_EXECUTION_LOGS.value,
        }
    
    def validate_request(self, request: MCPRequest) -> None:
        """
        Validate MCP request structure and method.
        
        Args:
            request: The MCP request to validate
            
        Raises:
            ValidationError: If request is invalid
        """
        if not request.method:
            raise ValidationError(ErrorMessages.MISSING_METHOD.value)
        
        # Validate method-specific parameters
        if request.method == MCPMethod.RUN_SKILL:
            self._validate_skill_request(request.params)
        elif request.method == MCPMethod.RUN_BRIDGE:
            self._validate_bridge_request(request.params)
        elif request.method == MCPMethod.CHAT_QUERY:
            self._validate_chat_request(request.params)
        elif request.method in {
            MCPMethod.RUN_WEEKLY_DIGEST,
            MCPMethod.RUN_LEAD_SCAN,
        }:
            # These methods require no additional validation
            pass
        else:
            raise ValidationError(
                ValidationMessages.unsupported_method(request.method),
                field=ValidationFields.METHOD.value,
                value=request.method
            )
    
    def validate_response_type(self, response_type: ResponseType) -> None:
        """
        Validate response type is supported.
        
        Args:
            response_type: The response type to validate
            
        Raises:
            ValidationError: If response type is invalid
        """
        if response_type not in {ResponseType.JSON, ResponseType.EMAIL, ResponseType.CHAT}:
            raise ValidationError(
                ValidationMessages.unknown_response_type(str(response_type)),
                field=ValidationFields.RESPONSE_TYPE.value,
                value=response_type,
                constraint="must be one of: json, email, chat"
            )
    
    def _validate_skill_request(self, params: Dict[str, Any]) -> None:
        """Validate skill execution request parameters."""
        skill_name = params.get(DataFields.SKILL_NAME.value)
        
        if not skill_name:
            raise ValidationError(
                ErrorMessages.MISSING_SKILL_NAME.value,
                field=ValidationFields.SKILL_NAME.value
            )
        
        if skill_name not in self._available_skills:
            raise ValidationError(
                ValidationMessages.unknown_skill(skill_name, list(self._available_skills)),
                field=ValidationFields.SKILL_NAME.value,
                value=skill_name,
                constraint=f"must be one of: {', '.join(self._available_skills)}"
            )
    
    def _validate_bridge_request(self, params: Dict[str, Any]) -> None:
        """Validate bridge function request parameters."""
        function_name = params.get(DataFields.FUNCTION_NAME.value)
        
        if not function_name:
            raise ValidationError(
                ErrorMessages.MISSING_FUNCTION_NAME.value,
                field=ValidationFields.FUNCTION_NAME.value
            )
        
        if function_name not in self._available_bridge_functions:
            raise ValidationError(
                ValidationMessages.unknown_bridge_function(
                    function_name, list(self._available_bridge_functions)
                ),
                field=ValidationFields.FUNCTION_NAME.value,
                value=function_name,
                constraint=f"must be one of: {', '.join(self._available_bridge_functions)}"
            )
    
    def _validate_chat_request(self, params: Dict[str, Any]) -> None:
        """Validate chat query request parameters."""
        query = params.get(DataFields.QUERY.value)
        
        if not query:
            raise ValidationError(
                ErrorMessages.MISSING_QUERY.value,
                field=ValidationFields.QUERY.value
            )