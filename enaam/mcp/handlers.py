"""
MCP Handlers - Request processing and response formatting

Handles routing, formatting, and response generation.
NO BUSINESS LOGIC - only routing, formatting, and exposing.
"""

from typing import Dict, Any, Optional
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from .schemas import (
    MCPRequest, MCPResponse, ResponseType, MCPMethod,
    SkillRequest, BridgeRequest, ChatQueryRequest,
    create_mcp_response, create_email_response, create_chat_response, create_json_response
)

# Import Enaam components
from enaam.core.agent import EnaamAgent
from enaam.integrations.khursheed_bridge import KhursheedBridge


class MCPHandler:
    """MCP request handler - routes and formats only"""
    
    def __init__(self):
        self.agent = EnaamAgent()
        self.bridge = KhursheedBridge()
    
    def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Route MCP request to appropriate handler"""
        try:
            # Route based on method
            if request.method == MCPMethod.RUN_SKILL:
                result = self._handle_run_skill(request.params)
            elif request.method == MCPMethod.RUN_BRIDGE:
                result = self._handle_run_bridge(request.params)
            elif request.method == MCPMethod.RUN_WEEKLY_DIGEST:
                result = self._handle_run_weekly_digest()
            elif request.method == MCPMethod.RUN_LEAD_SCAN:
                result = self._handle_run_lead_scan()
            elif request.method == MCPMethod.CHAT_QUERY:
                result = self._handle_chat_query(request.params)
            else:
                raise ValueError(f"Unsupported method: {request.method}")
            
            # Format response based on requested type
            formatted_result = self._format_response(result, request.response_type)
            
            return create_mcp_response(request.id, formatted_result)
            
        except Exception as e:
            error = {
                "code": "HANDLER_ERROR",
                "message": str(e),
                "method": request.method
            }
            return create_mcp_response(request.id, error=error)
    
    def _handle_run_skill(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle skill execution request"""
        skill_name = params.get("skill_name")
        skill_input = params.get("input", {})
        
        if not skill_name:
            raise ValueError("Missing 'skill_name' parameter")
        
        # Available skills from Khursheed bridge
        available_skills = {
            "sifter": lambda: self.bridge.email_summary(),
            "lead_scout": lambda: self.bridge.lead_scan(),
            "echo": lambda: {"status": "success", "source": "khursheed", "action": "echo", "data": skill_input, "next_steps": []},
            "timestamp": lambda: {"status": "success", "source": "khursheed", "action": "timestamp", "data": {"timestamp": "2026-05-23T18:54:27.419464+00:00"}, "next_steps": []}
        }
        
        if skill_name not in available_skills:
            raise ValueError(f"Unknown skill: {skill_name}")
        
        return available_skills[skill_name]()
    
    def _handle_run_bridge(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Khursheed bridge function request"""
        function_name = params.get("function_name")
        
        if not function_name:
            raise ValueError("Missing 'function_name' parameter")
        
        # Available bridge functions
        bridge_functions = {
            "email_summary": self.bridge.email_summary,
            "lead_scan": self.bridge.lead_scan,
            "weekly_digest": self.bridge.weekly_digest,
            "executive_summary": self.bridge.executive_summary,
            "run_scheduled_tasks": self.bridge.run_scheduled_tasks,
            "weekly_monday_9am_digest": self.bridge.weekly_monday_9am_digest,
            "lead_generation_run": self.bridge.lead_generation_run,
            "email_triage_run": self.bridge.email_triage_run,
            "get_execution_logs": self.bridge.get_execution_logs
        }
        
        if function_name not in bridge_functions:
            raise ValueError(f"Unknown bridge function: {function_name}")
        
        return bridge_functions[function_name]()
    
    def _handle_run_weekly_digest(self) -> Dict[str, Any]:
        """Handle weekly digest request - direct shortcut"""
        return self.bridge.weekly_digest()
    
    def _handle_run_lead_scan(self) -> Dict[str, Any]:
        """Handle lead scan request - direct shortcut"""
        return self.bridge.lead_scan()
    
    def _handle_chat_query(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle chat query request"""
        query = params.get("query")
        context = params.get("context", {})
        
        if not query:
            raise ValueError("Missing 'query' parameter")
        
        # Process through Enaam agent
        agent_response = self.agent.process_request(query)
        
        # Add context if provided
        if context:
            agent_response["context"] = context
        
        return agent_response
    
    def _format_response(self, result: Dict[str, Any], response_type: ResponseType) -> Dict[str, Any]:
        """Format response based on requested type"""
        if response_type == ResponseType.JSON:
            return self._format_as_json(result)
        elif response_type == ResponseType.EMAIL:
            return self._format_as_email(result)
        elif response_type == ResponseType.CHAT:
            return self._format_as_chat(result)
        else:
            raise ValueError(f"Unknown response type: {response_type}")
    
    def _format_as_json(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format response as JSON"""
        return create_json_response(
            data=result,
            status=result.get("status", "success"),
            source=result.get("source", "enaam")
        ).__dict__
    
    def _format_as_email(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format response as email"""
        action = result.get("action", "unknown")
        data = result.get("data", {})
        
        # Generate email subject based on action
        subject_map = {
            "weekly_digest": "Weekly Executive Summary",
            "weekly_monday_9am_digest": "Weekly Monday Digest",
            "executive_summary": "Daily Executive Summary",
            "lead_scan": "Lead Discovery Results",
            "lead_generation_run": "Lead Generation Report",
            "email_summary": "Email Triage Summary",
            "email_triage_run": "Email Processing Report",
            "run_scheduled_tasks": "Scheduled Tasks Completed"
        }
        
        subject = subject_map.get(action, f"Enaam Report: {action}")
        
        # Generate email body
        if "summary" in data:
            body = data["summary"]
        elif "message" in data:
            body = data["message"]
        else:
            # Create structured email body
            body_parts = [f"Action: {action}"]
            
            if result.get("status") == "success":
                body_parts.append("Status: ✅ Success")
            else:
                body_parts.append("Status: ❌ Error")
            
            # Add key data points
            for key, value in data.items():
                if key not in ["summary", "message", "error"]:
                    body_parts.append(f"{key.replace('_', ' ').title()}: {value}")
            
            # Add next steps
            next_steps = result.get("next_steps", [])
            if next_steps:
                body_parts.append("\nNext Steps:")
                for step in next_steps:
                    body_parts.append(f"• {step}")
            
            body = "\n".join(body_parts)
        
        return create_email_response(subject=subject, body=body).__dict__
    
    def _format_as_chat(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Format response as chat message"""
        action = result.get("action", "unknown")
        data = result.get("data", {})
        status = result.get("status", "unknown")
        
        # Generate chat message
        if status == "error":
            message = f"❌ Error in {action}: {data.get('error', 'Unknown error')}"
            suggestions = ["Try again", "Check configuration", "Contact support"]
        else:
            if "summary" in data:
                # For summaries, provide a condensed version
                summary = data["summary"]
                if len(summary) > 300:
                    message = f"✅ {action} completed:\n\n{summary[:300]}..."
                else:
                    message = f"✅ {action} completed:\n\n{summary}"
            elif "message" in data:
                message = f"✅ {data['message']}"
            else:
                message = f"✅ {action} completed successfully"
            
            # Add suggestions based on next steps
            suggestions = result.get("next_steps", [])[:3]  # Limit to 3 suggestions
        
        # Add metadata
        metadata = {
            "action": action,
            "source": result.get("source", "enaam"),
            "status": status,
            "execution_time": data.get("execution_time_ms")
        }
        
        return create_chat_response(message=message, suggestions=suggestions, metadata=metadata).__dict__