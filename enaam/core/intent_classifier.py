"""
Enhanced Intent Classifier - Natural language intent classification

Provides sophisticated intent classification using multiple techniques:
- Pattern matching
- Keyword analysis  
- Context awareness
- Confidence scoring
"""

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import Counter

from .enums import ActionType, IntentType
from .chat_context import ChatContextManager, ChatSession


class IntentClassifier:
    """
    Enhanced intent classifier with natural language understanding.
    
    Uses multiple classification techniques to understand user intent:
    - Pattern-based matching
    - Keyword scoring
    - Context-aware routing
    - Conversation flow analysis
    """
    
    def __init__(self, context_manager: Optional[ChatContextManager] = None):
        self.context_manager = context_manager
        
        # Core action patterns (from existing router)
        self.action_patterns = {
            ActionType.EMAIL_SUMMARY.value: {
                "patterns": [
                    r"check.*email", r"email.*summary", r"inbox.*status", r"mail.*check",
                    r"email.*triage", r"process.*email", r"email.*updates"
                ],
                "keywords": ["email", "inbox", "mail", "messages", "check", "summary", "triage"],
                "priority": 0.8
            },
            ActionType.LEAD_SCAN.value: {
                "patterns": [
                    r"find.*leads?", r"lead.*discovery", r"prospect.*search", r"business.*leads?",
                    r"lead.*scout", r"search.*prospects"
                ],
                "keywords": ["lead", "leads", "prospect", "business", "find", "discovery", "scout"],
                "priority": 0.8
            },
            ActionType.WEEKLY_DIGEST.value: {
                "patterns": [
                    r"weekly.*summary", r"weekly.*digest", r"week.*report", r"weekly.*update",
                    r"this.*week", r"week.*overview"
                ],
                "keywords": ["weekly", "week", "digest", "summary", "report", "overview"],
                "priority": 0.7
            },
            ActionType.EXECUTIVE_SUMMARY.value: {
                "patterns": [
                    r"executive.*summary", r"daily.*summary", r"status.*report", r"summary",
                    r"report", r"what.*happened", r"today.*summary", r"daily.*report"
                ],
                "keywords": ["executive", "summary", "status", "report", "daily", "today", "overview"],
                "priority": 0.6
            },
            ActionType.RUN_SCHEDULED_TASKS.value: {
                "patterns": [
                    r"run.*tasks?", r"execute.*tasks?", r"scheduled.*tasks?", r"run.*jobs?",
                    r"automation", r"scheduled.*run"
                ],
                "keywords": ["run", "execute", "tasks", "scheduled", "automation", "jobs"],
                "priority": 0.7
            },
            ActionType.WEEKLY_MONDAY_9AM_DIGEST.value: {
                "patterns": [
                    r"monday.*digest", r"9am.*digest", r"weekly.*monday", r"monday.*9am",
                    r"weekly.*cron", r"monday.*automation"
                ],
                "keywords": ["monday", "9am", "weekly", "digest", "automation", "cron"],
                "priority": 0.9
            },
            ActionType.LEAD_GENERATION_RUN.value: {
                "patterns": [
                    r"lead.*generation", r"generate.*leads?", r"lead.*automation", r"auto.*lead",
                    r"lead.*pipeline", r"lead.*workflow"
                ],
                "keywords": ["lead", "generation", "generate", "automation", "pipeline", "workflow"],
                "priority": 0.8
            },
            ActionType.EMAIL_TRIAGE_RUN.value: {
                "patterns": [
                    r"email.*triage", r"triage.*email", r"process.*email", r"email.*automation",
                    r"email.*workflow", r"organize.*email"
                ],
                "keywords": ["email", "triage", "process", "automation", "workflow", "organize"],
                "priority": 0.8
            }
        }
        
        # Conversation flow indicators
        self.conversation_indicators = {
            "followup": ["also", "and", "then", "next", "after", "additionally"],
            "clarification": ["what", "how", "why", "when", "where", "explain"],
            "continuation": ["continue", "more", "details", "expand", "elaborate"],
            "status": ["status", "progress", "update", "current", "now", "latest"]
        }
        
        # Intent modifiers that affect response style
        self.response_modifiers = {
            "urgency": {
                "high": ["urgent", "asap", "immediately", "now", "emergency", "critical"],
                "low": ["later", "when possible", "eventually", "sometime"]
            },
            "detail_level": {
                "brief": ["brief", "quick", "summary", "short", "overview"],
                "detailed": ["detailed", "full", "complete", "comprehensive", "thorough", "deep"]
            },
            "formality": {
                "casual": ["hey", "hi", "sup", "what's up"],
                "formal": ["please", "could you", "would you kindly", "I request"]
            }
        }
    
    def classify_intent(
        self, 
        request: str, 
        session_id: Optional[str] = None,
        conversation_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Classify intent with enhanced natural language understanding.
        
        Args:
            request: User input to classify
            session_id: Optional session ID for context
            conversation_context: Optional conversation context
        
        Returns:
            Dict containing intent classification with confidence and metadata
        """
        request_lower = request.lower().strip()
        
        # Get conversation context if available
        if not conversation_context and session_id and self.context_manager:
            conversation_context = self.context_manager.get_conversation_context(session_id)
        
        # Score each possible intent
        intent_scores = self._score_all_intents(request_lower)
        
        # Apply context-based boosting
        if conversation_context:
            intent_scores = self._apply_context_boost(intent_scores, conversation_context)
        
        # Get the best matching intent
        best_intent, confidence = self._get_best_intent(intent_scores)
        
        # Extract response modifiers
        modifiers = self._extract_response_modifiers(request_lower)
        
        # Analyze conversation flow
        flow_analysis = self._analyze_conversation_flow(request_lower, conversation_context)
        
        return {
            "type": IntentType.KHURSHEED_BRIDGE.value if best_intent != "general" else IntentType.GENERAL.value,
            "action": best_intent,
            "confidence": confidence,
            "modifiers": modifiers,
            "flow_analysis": flow_analysis,
            "alternative_intents": self._get_alternative_intents(intent_scores, 3),
            "extracted_entities": self._extract_entities(request)
        }
    
    def _score_all_intents(self, request_lower: str) -> Dict[str, float]:
        """Score all possible intents against the request."""
        scores = {}
        
        for action, config in self.action_patterns.items():
            score = 0.0
            
            # Pattern matching score
            pattern_matches = sum(
                1 for pattern in config["patterns"]
                if re.search(pattern, request_lower)
            )
            pattern_score = min(pattern_matches * 0.3, 0.9)
            
            # Keyword matching score
            keyword_matches = sum(
                1 for keyword in config["keywords"]
                if keyword in request_lower
            )
            keyword_score = min(keyword_matches * 0.2, 0.6)
            
            # Combined score with priority weighting
            base_score = pattern_score + keyword_score
            final_score = base_score * config["priority"]
            
            scores[action] = final_score
        
        return scores
    
    def _apply_context_boost(
        self, 
        intent_scores: Dict[str, float], 
        conversation_context: Dict[str, Any]
    ) -> Dict[str, float]:
        """Apply context-based boosting to intent scores."""
        boosted_scores = intent_scores.copy()
        
        # Boost based on recent actions
        recent_actions = conversation_context.get("recent_actions", [])
        if recent_actions:
            for action in recent_actions:
                if action in boosted_scores:
                    boosted_scores[action] *= 1.1  # Small boost for continuity
        
        # Boost based on conversation flow
        flow_info = conversation_context.get("conversation_flow", {})
        if flow_info.get("pattern") == "escalating":
            # Boost more detailed actions
            detail_actions = [
                ActionType.EXECUTIVE_SUMMARY.value,
                ActionType.WEEKLY_DIGEST.value
            ]
            for action in detail_actions:
                if action in boosted_scores:
                    boosted_scores[action] *= 1.2
        
        # Boost based on user preferences
        preferences = conversation_context.get("user_preferences", {})
        preferred_actions = preferences.get("preferred_actions", [])
        for action, _count in preferred_actions:
            if action in boosted_scores:
                boosted_scores[action] *= 1.15
        
        return boosted_scores
    
    def _get_best_intent(self, intent_scores: Dict[str, float]) -> Tuple[str, float]:
        """Get the best intent from scores."""
        if not intent_scores or max(intent_scores.values()) < 0.3:
            return ActionType.HANDLE_GENERAL.value, 0.3
        
        best_action = max(intent_scores.keys(), key=lambda k: intent_scores[k])
        confidence = min(intent_scores[best_action], 0.95)
        
        return best_action, confidence
    
    def _get_alternative_intents(self, intent_scores: Dict[str, float], limit: int) -> List[Dict[str, Any]]:
        """Get alternative intents sorted by score."""
        sorted_intents = sorted(
            intent_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        return [
            {"action": action, "confidence": score}
            for action, score in sorted_intents[:limit]
            if score > 0.2
        ]
    
    def _extract_response_modifiers(self, request_lower: str) -> Dict[str, str]:
        """Extract modifiers that affect response style."""
        modifiers = {}
        
        # Check urgency
        for level, keywords in self.response_modifiers["urgency"].items():
            if any(keyword in request_lower for keyword in keywords):
                modifiers["urgency"] = level
                break
        
        # Check detail level
        for level, keywords in self.response_modifiers["detail_level"].items():
            if any(keyword in request_lower for keyword in keywords):
                modifiers["detail_level"] = level
                break
        
        # Check formality
        for level, keywords in self.response_modifiers["formality"].items():
            if any(keyword in request_lower for keyword in keywords):
                modifiers["formality"] = level
                break
        
        return modifiers
    
    def _analyze_conversation_flow(
        self, 
        request_lower: str, 
        conversation_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze conversation flow indicators."""
        flow_info = {
            "type": "initial",
            "indicators": [],
            "suggested_response_style": "standard"
        }
        
        # Check for flow indicators
        for flow_type, keywords in self.conversation_indicators.items():
            if any(keyword in request_lower for keyword in keywords):
                flow_info["type"] = flow_type
                flow_info["indicators"].append(flow_type)
        
        # Determine response style based on flow and context
        if conversation_context:
            turn_count = conversation_context.get("turn_count", 0)
            
            if turn_count > 3:
                flow_info["suggested_response_style"] = "contextual"
            elif flow_info["type"] == "followup":
                flow_info["suggested_response_style"] = "continuation"
            elif flow_info["type"] == "clarification":
                flow_info["suggested_response_style"] = "explanatory"
        
        return flow_info
    
    def _extract_entities(self, request: str) -> Dict[str, List[str]]:
        """Extract named entities and key information from request."""
        entities = {
            "time_expressions": [],
            "business_terms": [],
            "action_objects": []
        }
        
        request_lower = request.lower()
        
        # Time expressions
        time_patterns = [
            r"\b(today|tomorrow|yesterday|this week|next week|last week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\b(\d{1,2}:\d{2}|morning|afternoon|evening|night)\b",
            r"\b(daily|weekly|monthly|quarterly)\b"
        ]
        
        for pattern in time_patterns:
            matches = re.findall(pattern, request_lower)
            entities["time_expressions"].extend(matches)
        
        # Business terms
        business_patterns = [
            r"\b(email|inbox|lead|prospect|client|customer|report|summary|task|project|meeting)\b",
            r"\b(CTO|CEO|manager|director|executive|sales|marketing|development)\b"
        ]
        
        for pattern in business_patterns:
            matches = re.findall(pattern, request_lower)
            entities["business_terms"].extend(matches)
        
        # Action objects (things being acted upon)
        object_patterns = [
            r"(email|emails)\s+(from|about|containing|with)\s+(\w+)",
            r"(leads?|prospects?)\s+(for|in|about)\s+(\w+)",
            r"(report|summary)\s+(for|about|on)\s+(\w+)"
        ]
        
        for pattern in object_patterns:
            matches = re.findall(pattern, request_lower)
            entities["action_objects"].extend([match[2] for match in matches])
        
        return entities


class ContextAwareRouter:
    """
    Enhanced router with context awareness and conversation memory.
    
    Integrates the enhanced intent classifier with conversation context
    to provide smarter routing and response personalization.
    """
    
    def __init__(self, context_manager: Optional[ChatContextManager] = None):
        self.context_manager = context_manager
        self.intent_classifier = IntentClassifier(context_manager)
    
    def route_request(
        self, 
        request: str, 
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Route request with enhanced context awareness."""
        
        # Get or create session if session management is available
        if self.context_manager and session_id:
            session = self.context_manager.get_or_create_session(session_id, user_id)
            conversation_context = self.context_manager.get_conversation_context(session_id)
        else:
            conversation_context = None
        
        # Enhanced intent classification
        intent = self.intent_classifier.classify_intent(
            request, 
            session_id, 
            conversation_context
        )
        
        # Determine handler
        handler = self._determine_handler(intent)
        
        # Extract parameters with context
        parameters = self._extract_parameters(request, intent, conversation_context)
        
        routing_info = {
            "original_request": request,
            "intent": intent,
            "handler": handler,
            "parameters": parameters,
            "conversation_context": conversation_context,
            "session_id": session_id,
            "routing_metadata": {
                "confidence": intent.get("confidence", 0.0),
                "alternatives": intent.get("alternative_intents", []),
                "response_style": intent.get("flow_analysis", {}).get("suggested_response_style", "standard"),
                "modifiers": intent.get("modifiers", {})
            }
        }
        
        return routing_info
    
    def _determine_handler(self, intent: Dict[str, Any]) -> str:
        """Determine which handler should process this intent."""
        intent_type = intent.get("type", IntentType.GENERAL.value)
        
        if intent_type == IntentType.KHURSHEED_BRIDGE.value:
            return "khursheed_bridge"
        elif intent_type == IntentType.GENERAL.value:
            return "general"
        else:
            return "unknown"
    
    def _extract_parameters(
        self, 
        request: str, 
        intent: Dict[str, Any], 
        conversation_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Extract parameters with context awareness."""
        parameters = {}
        
        # Basic parameter extraction
        entities = intent.get("extracted_entities", {})
        if entities:
            parameters["entities"] = entities
        
        # Context-aware parameter enhancement
        if conversation_context:
            # Add user preferences
            preferences = conversation_context.get("user_preferences", {})
            if preferences.get("detail_level"):
                parameters["detail_level"] = preferences["detail_level"]
        
        # Add response modifiers as parameters
        modifiers = intent.get("modifiers", {})
        if modifiers:
            parameters["response_modifiers"] = modifiers
        
        return parameters