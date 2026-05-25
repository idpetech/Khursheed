"""
Enaam Router - Intent classification and routing

Routes requests to appropriate handlers based on intent classification.
"""

import re
from typing import Any, Dict, List

from .enums import (
    ActionType,
    IntentType,
    HandlerType,
)
from .constants import DefaultValues


class EnaamRouter:
    """Simple intent-based router for Enaam requests"""
    
    def __init__(self) -> None:
        self.khursheed_patterns = {
            ActionType.EMAIL_SUMMARY.value: [
                r"check.*email",
                r"email.*summary", 
                r"inbox.*status",
                r"mail.*check"
            ],
            ActionType.LEAD_SCAN.value: [
                r"find.*leads?",
                r"lead.*discovery",
                r"prospect.*search",
                r"business.*leads?"
            ],
            ActionType.WEEKLY_DIGEST.value: [
                r"weekly.*summary",
                r"weekly.*digest", 
                r"week.*report",
                r"weekly.*update"
            ],
            ActionType.EXECUTIVE_SUMMARY.value: [
                r"executive.*summary",
                r"daily.*summary",
                r"status.*report",
                r"summary",
                r"report"
            ],
            ActionType.RUN_SCHEDULED_TASKS.value: [
                r"run.*tasks?",
                r"execute.*tasks?",
                r"scheduled.*tasks?",
                r"run.*jobs?"
            ],
            # NEW REQUIRED WRAPPER PATTERNS
            ActionType.WEEKLY_MONDAY_9AM_DIGEST.value: [
                r"monday.*digest",
                r"9am.*digest",
                r"weekly.*monday",
                r"monday.*9am",
                r"weekly.*cron"
            ],
            ActionType.LEAD_GENERATION_RUN.value: [
                r"lead.*generation",
                r"generate.*leads?",
                r"lead.*automation",
                r"auto.*lead"
            ],
            ActionType.EMAIL_TRIAGE_RUN.value: [
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
                        "type": IntentType.KHURSHEED_BRIDGE.value,
                        "action": action,
                        "confidence": 0.8
                    }
        
        # Default to general query
        return {
            "type": IntentType.GENERAL.value,
            "action": ActionType.HANDLE_GENERAL.value, 
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
        if intent["type"] == IntentType.KHURSHEED_BRIDGE.value:
            return HandlerType.KHURSHEED_BRIDGE.value
        elif intent["type"] == IntentType.GENERAL.value:
            return HandlerType.GENERAL.value
        else:
            return HandlerType.UNKNOWN.value
    
    def _extract_parameters(self, request: str, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Extract parameters from the request based on intent"""
        parameters = {}
        
        # For now, keep it simple - no parameter extraction
        # This can be expanded as needed
        
        return parameters