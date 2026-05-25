"""
MCP Response Formatter - Focused response formatting logic

Handles different response format types (JSON, Email, Chat).
Single responsibility: Response formatting only.
"""

from typing import Any, Dict

from ..core.enums import (
    BridgeFunction,
    ResponseStatus,
    SourceType,
    EmailSubjects,
    DataFields,
)
from ..core.constants import DefaultValues
from ..core.exceptions import ValidationError
from ..core.constants import ValidationMessages
from ..core.enums import ValidationFields
from .schemas import (
    ResponseType,
    create_json_response,
    create_email_response,
    create_chat_response,
)


class ResponseFormatter:
    """
    Formats MCP responses into different output types.
    
    Single responsibility: Response formatting only.
    No validation, routing, or business logic.
    """
    
    def __init__(self):
        """Initialize formatter with subject mappings."""
        self._subject_map = {
            BridgeFunction.WEEKLY_DIGEST.value: EmailSubjects.WEEKLY_DIGEST.value,
            BridgeFunction.WEEKLY_MONDAY_9AM_DIGEST.value: EmailSubjects.WEEKLY_MONDAY_DIGEST.value,
            BridgeFunction.EXECUTIVE_SUMMARY.value: EmailSubjects.EXECUTIVE_SUMMARY.value,
            BridgeFunction.LEAD_SCAN.value: EmailSubjects.LEAD_SCAN.value,
            BridgeFunction.LEAD_GENERATION_RUN.value: EmailSubjects.LEAD_GENERATION.value,
            BridgeFunction.EMAIL_SUMMARY.value: EmailSubjects.EMAIL_SUMMARY.value,
            BridgeFunction.EMAIL_TRIAGE_RUN.value: EmailSubjects.EMAIL_TRIAGE.value,
            BridgeFunction.RUN_SCHEDULED_TASKS.value: EmailSubjects.SCHEDULED_TASKS.value
        }
    
    def format_response(self, result: Dict[str, Any], response_type: ResponseType) -> Dict[str, Any]:
        """
        Format response based on requested type.
        
        Args:
            result: The result data to format
            response_type: The desired response format
            
        Returns:
            Formatted response as dictionary
            
        Raises:
            ValidationError: If response type is unsupported
        """
        if response_type == ResponseType.JSON:
            return self.format_as_json(result)
        elif response_type == ResponseType.EMAIL:
            return self.format_as_email(result)
        elif response_type == ResponseType.CHAT:
            return self.format_as_chat(result)
        else:
            raise ValidationError(
                ValidationMessages.unknown_response_type(str(response_type)),
                field=ValidationFields.RESPONSE_TYPE.value,
                value=response_type,
                constraint="must be one of: json, email, chat"
            )
    
    def format_as_json(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format response as JSON structure.
        
        Args:
            result: The result data to format
            
        Returns:
            JSON-formatted response dictionary
        """
        return create_json_response(
            data=result,
            status=result.get(DataFields.STATUS.value, ResponseStatus.SUCCESS.value),
            source=result.get(DataFields.SOURCE.value, SourceType.ENAAM.value)
        ).__dict__
    
    def format_as_email(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format response as email structure.
        
        Args:
            result: The result data to format
            
        Returns:
            Email-formatted response dictionary
        """
        action = result.get(DataFields.ACTION.value, "unknown")
        data = result.get(DataFields.DATA.value, {})
        
        # Generate email subject based on action
        subject = self._subject_map.get(action, f"Enaam Report: {action}")
        
        # Generate email body
        body = self._generate_email_body(result, action, data)
        
        return create_email_response(subject=subject, body=body).__dict__
    
    def format_as_chat(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format response as chat message structure.
        
        Args:
            result: The result data to format
            
        Returns:
            Chat-formatted response dictionary
        """
        action = result.get(DataFields.ACTION.value, "unknown")
        data = result.get(DataFields.DATA.value, {})
        status = result.get(DataFields.STATUS.value, "unknown")
        
        # Generate chat message and suggestions
        message, suggestions = self._generate_chat_content(result, action, data, status)
        
        # Add metadata
        metadata = {
            DataFields.ACTION.value: action,
            DataFields.SOURCE.value: result.get(DataFields.SOURCE.value, SourceType.ENAAM.value),
            DataFields.STATUS.value: status,
            "execution_time": data.get(DataFields.EXECUTION_TIME_MS.value)
        }
        
        return create_chat_response(message=message, suggestions=suggestions, metadata=metadata).__dict__
    
    def _generate_email_body(self, result: Dict[str, Any], action: str, data: Dict[str, Any]) -> str:
        """Generate email body content from result data."""
        # Use existing summary or message if available
        if DataFields.SUMMARY.value in data:
            return data[DataFields.SUMMARY.value]
        elif DataFields.MESSAGE.value in data:
            return data[DataFields.MESSAGE.value]
        
        # Create structured email body
        body_parts = [f"Action: {action}"]
        
        # Add status indicator
        if result.get(DataFields.STATUS.value) == ResponseStatus.SUCCESS.value:
            body_parts.append("Status: ✅ Success")
        else:
            body_parts.append("Status: ❌ Error")
        
        # Add key data points
        for key, value in data.items():
            if key not in {DataFields.SUMMARY.value, DataFields.MESSAGE.value, DataFields.ERROR.value}:
                body_parts.append(f"{key.replace('_', ' ').title()}: {value}")
        
        # Add next steps
        next_steps = result.get(DataFields.NEXT_STEPS.value, [])
        if next_steps:
            body_parts.append("\nNext Steps:")
            for step in next_steps:
                body_parts.append(f"• {step}")
        
        return "\n".join(body_parts)
    
    def _generate_chat_content(
        self, 
        result: Dict[str, Any], 
        action: str, 
        data: Dict[str, Any], 
        status: str
    ) -> tuple[str, list[str]]:
        """Generate chat message and suggestions from result data."""
        # Handle error status
        if status == ResponseStatus.ERROR.value:
            message = f"❌ Error in {action}: {data.get(DataFields.ERROR.value, 'Unknown error')}"
            suggestions = ["Try again", "Check configuration", "Contact support"]
            return message, suggestions
        
        # Generate success message
        if DataFields.SUMMARY.value in data:
            # For summaries, provide a condensed version
            summary = data[DataFields.SUMMARY.value]
            if len(summary) > DefaultValues.MAX_SUMMARY_PREVIEW:
                message = f"✅ {action} completed:\n\n{summary[:DefaultValues.MAX_SUMMARY_PREVIEW]}..."
            else:
                message = f"✅ {action} completed:\n\n{summary}"
        elif DataFields.MESSAGE.value in data:
            message = f"✅ {data[DataFields.MESSAGE.value]}"
        else:
            message = f"✅ {action} completed successfully"
        
        # Add suggestions based on next steps
        suggestions = result.get(DataFields.NEXT_STEPS.value, [])[:DefaultValues.MAX_SUGGESTIONS]
        
        return message, suggestions