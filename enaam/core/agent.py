"""
Enaam Core Agent

Chief-of-Staff orchestration layer that routes requests and manages execution.
"""

from typing import Dict, Any
from .router import EnaamRouter
from .state import EnaamState
from ..integrations.khursheed_bridge import KhursheedBridge


class EnaamAgent:
    """Core agent for Enaam Chief-of-Staff system"""
    
    def __init__(self):
        self.router = EnaamRouter()
        self.state = EnaamState()
        self.khursheed_bridge = KhursheedBridge()
    
    def process_request(self, request: str) -> Dict[str, Any]:
        """
        Main agent loop:
        1. Receive request
        2. Classify intent  
        3. Route to skill OR Khursheed bridge
        4. Return structured JSON response
        """
        # Update state
        self.state.update_request(request)
        
        # Route the request
        routing = self.router.route_request(request)
        
        # Execute based on routing
        if routing["handler"] == "khursheed_bridge":
            response = self._execute_khursheed_action(routing)
        elif routing["handler"] == "general":
            response = self._handle_general_request(routing)
        else:
            response = self._handle_unknown_request(routing)
        
        # Update state with last action
        self.state.set_last_action(response.get("action", "unknown"))
        
        return response
    
    def _execute_khursheed_action(self, routing: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action via Khursheed bridge"""
        action = routing["intent"]["action"]
        
        # Map to Khursheed bridge methods
        action_map = {
            "email_summary": self.khursheed_bridge.email_summary,
            "lead_scan": self.khursheed_bridge.lead_scan,
            "weekly_digest": self.khursheed_bridge.weekly_digest,
            "executive_summary": self.khursheed_bridge.executive_summary,
            "run_scheduled_tasks": self.khursheed_bridge.run_scheduled_tasks,
            # NEW REQUIRED WRAPPER FUNCTIONS
            "weekly_monday_9am_digest": self.khursheed_bridge.weekly_monday_9am_digest,
            "lead_generation_run": self.khursheed_bridge.lead_generation_run,
            "email_triage_run": self.khursheed_bridge.email_triage_run
        }
        
        if action in action_map:
            return action_map[action]()
        else:
            return {
                "status": "error",
                "source": "enaam",
                "action": "unknown_khursheed_action",
                "data": {"error": f"Unknown Khursheed action: {action}"},
                "next_steps": ["Check available Khursheed bridge actions"]
            }
    
    def _handle_general_request(self, routing: Dict[str, Any]) -> Dict[str, Any]:
        """Handle general requests not routed to Khursheed"""
        return {
            "status": "success",
            "source": "enaam", 
            "action": "general_response",
            "data": {
                "message": "I'm Enaam, your Chief of Staff AI. I can help you with:",
                "available_actions": [
                    "Check emails - 'check email' or 'email summary'",
                    "Find leads - 'find leads' or 'lead discovery'", 
                    "Weekly report - 'weekly digest' or 'weekly summary'",
                    "Daily summary - 'executive summary' or 'status report'",
                    "Run tasks - 'run scheduled tasks' or 'execute tasks'",
                    "Monday digest - 'monday digest' or '9am digest'",
                    "Lead generation - 'lead generation' or 'generate leads'",
                    "Email triage - 'email triage' or 'process email'"
                ]
            },
            "next_steps": ["Choose an action from the available options"]
        }
    
    def _handle_unknown_request(self, routing: Dict[str, Any]) -> Dict[str, Any]:
        """Handle unknown/unroutable requests"""
        return {
            "status": "error",
            "source": "enaam",
            "action": "unknown_request",
            "data": {
                "error": "Unable to route request", 
                "routing_info": routing
            },
            "next_steps": ["Rephrase request", "Use specific action keywords"]
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status"""
        return {
            "status": "success",
            "source": "enaam",
            "action": "status_check", 
            "data": {
                "agent_state": self.state.to_dict(),
                "available_bridges": ["khursheed"],
                "system_ready": True
            },
            "next_steps": ["Send a request to begin processing"]
        }