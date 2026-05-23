"""
Enaam Router - Intent classification and routing

Routes requests to appropriate handlers based on intent classification.
"""

from typing import Dict, Any, Optional
import re


class EnaamRouter:
    """Simple intent-based router for Enaam requests"""
    
    def __init__(self):
        self.khursheed_patterns = {
            "email_summary": [
                r"check.*email",
                r"email.*summary", 
                r"inbox.*status",
                r"mail.*check"
            ],
            "lead_scan": [
                r"find.*leads?",
                r"lead.*discovery",
                r"prospect.*search",
                r"business.*leads?"
            ],
            "weekly_digest": [
                r"weekly.*summary",
                r"weekly.*digest", 
                r"week.*report",
                r"weekly.*update"
            ],
            "executive_summary": [
                r"executive.*summary",
                r"daily.*summary",
                r"status.*report",
                r"summary",
                r"report"
            ],
            "run_scheduled_tasks": [
                r"run.*tasks?",
                r"execute.*tasks?",
                r"scheduled.*tasks?",
                r"run.*jobs?"
            ],
            # NEW REQUIRED WRAPPER PATTERNS
            "weekly_monday_9am_digest": [
                r"monday.*digest",
                r"9am.*digest",
                r"weekly.*monday",
                r"monday.*9am",
                r"weekly.*cron"
            ],
            "lead_generation_run": [
                r"lead.*generation",
                r"generate.*leads?",
                r"lead.*automation",
                r"auto.*lead"
            ],
            "email_triage_run": [
                r"email.*triage",
                r"triage.*email",
                r"process.*email",
                r"email.*automation"
            ]
        }
    
    def classify_intent(self, request: str) -> Dict[str, Any]:
        """Classify the intent of the incoming request"""
        request_lower = request.lower().strip()
        
        # Check for Khursheed bridge actions
        for action, patterns in self.khursheed_patterns.items():
            for pattern in patterns:
                if re.search(pattern, request_lower):
                    return {
                        "type": "khursheed_bridge",
                        "action": action,
                        "confidence": 0.8
                    }
        
        # Default to general query
        return {
            "type": "general",
            "action": "handle_general", 
            "confidence": 0.3
        }
    
    def route_request(self, request: str) -> Dict[str, Any]:
        """Route request based on classified intent"""
        intent = self.classify_intent(request)
        
        routing_info = {
            "original_request": request,
            "intent": intent,
            "handler": self._determine_handler(intent),
            "parameters": self._extract_parameters(request, intent)
        }
        
        return routing_info
    
    def _determine_handler(self, intent: Dict[str, Any]) -> str:
        """Determine which handler should process this intent"""
        if intent["type"] == "khursheed_bridge":
            return "khursheed_bridge"
        elif intent["type"] == "general":
            return "general"
        else:
            return "unknown"
    
    def _extract_parameters(self, request: str, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters from the request based on intent"""
        parameters = {}
        
        # For now, keep it simple - no parameter extraction
        # This can be expanded as needed
        
        return parameters