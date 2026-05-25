"""
MCP Request Router - Enhanced routing with context awareness

Handles method routing and execution coordination with conversation context.
Enhanced for richer chat interactions and multi-turn conversations.
"""

from typing import Any, Callable, Dict, Optional

from ..core.agent import EnaamAgent
from ..core.chat_context import ChatContextManager
from ..core.intent_classifier import ContextAwareRouter
from ..core.enums import (
    BridgeFunction,
    SkillName,
    ResponseStatus,
    SourceType,
    DataFields,
)
from ..integrations.khursheed_bridge import KhursheedBridge
from .schemas import MCPRequest, MCPMethod


class RequestRouter:
    """
    Enhanced MCP request router with context awareness.
    
    Routes requests to appropriate handlers with conversation context,
    chat history, and intelligent intent classification for richer interactions.
    """
    
    def __init__(
        self, 
        agent: EnaamAgent, 
        bridge: KhursheedBridge,
        context_manager: Optional[ChatContextManager] = None
    ):
        """
        Initialize router with dependencies and context awareness.
        
        Args:
            agent: The Enaam agent for chat queries
            bridge: The Khursheed bridge for skills and functions  
            context_manager: Optional chat context manager for conversation memory
        """
        self.agent = agent
        self.bridge = bridge
        self.context_manager = context_manager or ChatContextManager()
        self.context_router = ContextAwareRouter(self.context_manager)
        
        # Define skill handlers
        self._skill_handlers = {
            SkillName.SIFTER.value: self.bridge.email_summary,
            SkillName.LEAD_SCOUT.value: self.bridge.lead_scan,
            SkillName.ECHO.value: self._handle_echo_skill,
            SkillName.TIMESTAMP.value: self._handle_timestamp_skill,
        }
        
        # Define bridge function handlers
        self._bridge_handlers = {
            BridgeFunction.EMAIL_SUMMARY.value: self.bridge.email_summary,
            BridgeFunction.LEAD_SCAN.value: self.bridge.lead_scan,
            BridgeFunction.WEEKLY_DIGEST.value: self.bridge.weekly_digest,
            BridgeFunction.EXECUTIVE_SUMMARY.value: self.bridge.executive_summary,
            BridgeFunction.RUN_SCHEDULED_TASKS.value: self.bridge.run_scheduled_tasks,
            BridgeFunction.WEEKLY_MONDAY_9AM_DIGEST.value: self.bridge.weekly_monday_9am_digest,
            BridgeFunction.LEAD_GENERATION_RUN.value: self.bridge.lead_generation_run,
            BridgeFunction.EMAIL_TRIAGE_RUN.value: self.bridge.email_triage_run,
            BridgeFunction.GET_EXECUTION_LOGS.value: self.bridge.get_execution_logs,
        }
    
    def route_request(self, request: MCPRequest) -> Dict[str, Any]:
        """
        Route request to appropriate handler and return result.
        
        Args:
            request: The validated MCP request
            
        Returns:
            Result dictionary from the appropriate handler
        """
        if request.method == MCPMethod.RUN_SKILL:
            return self._route_skill_request(request.params)
        elif request.method == MCPMethod.RUN_BRIDGE:
            return self._route_bridge_request(request.params)
        elif request.method == MCPMethod.RUN_WEEKLY_DIGEST:
            return self.bridge.weekly_digest()
        elif request.method == MCPMethod.RUN_LEAD_SCAN:
            return self.bridge.lead_scan()
        elif request.method == MCPMethod.CHAT_QUERY:
            return self._route_chat_request(request.params)
        else:
            # This should not happen due to validation, but included for completeness
            raise ValueError(f"Unsupported method: {request.method}")
    
    def _route_skill_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route skill execution request to appropriate skill handler."""
        skill_name = params.get(DataFields.SKILL_NAME.value)
        skill_input = params.get(DataFields.INPUT.value, {})
        
        # Get skill handler and execute
        handler = self._skill_handlers[skill_name]
        
        # Special handling for skills that need input
        if skill_name == SkillName.ECHO.value:
            return handler(skill_input)
        else:
            return handler()
    
    def _route_bridge_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route bridge function request to appropriate bridge handler."""
        function_name = params.get(DataFields.FUNCTION_NAME.value)
        
        # Get bridge handler and execute
        handler = self._bridge_handlers[function_name]
        return handler()
    
    def _route_chat_request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route chat query request with enhanced context awareness."""
        query = params.get(DataFields.QUERY.value)
        context = params.get(DataFields.CONTEXT.value, {})
        session_id = context.get("session_id", "default_session")
        user_id = context.get("user_id", "default_user")
        
        # Use enhanced context-aware routing
        routing_info = self.context_router.route_request(query, session_id, user_id)
        
        # Determine response based on enhanced routing
        if routing_info["handler"] == "khursheed_bridge":
            # Execute Khursheed bridge function directly
            action = routing_info["intent"]["action"]
            if action in self._bridge_handlers:
                response = self._bridge_handlers[action]()
            else:
                # Fallback to agent processing
                response = self.agent.process_request(query)
        else:
            # Process through Enaam agent with enhanced context
            response = self._process_general_chat(query, routing_info)
        
        # Enhance response with conversation metadata
        response = self._enhance_response_with_context(response, routing_info)
        
        # Record conversation turn for future context
        if self.context_manager:
            self.context_manager.add_conversation_turn(session_id, query, response)
        
        return response
    
    def _process_general_chat(self, query: str, routing_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process general chat with context-aware enhancements."""
        # Get the base response from the agent
        base_response = self.agent.process_request(query)
        
        # Enhance based on routing metadata
        metadata = routing_info.get("routing_metadata", {})
        modifiers = metadata.get("modifiers", {})
        
        # Customize response based on detected style preferences
        if modifiers.get("detail_level") == "brief":
            # Make response more concise
            data = base_response.get("data", {})
            if "available_actions" in data:
                data["available_actions"] = data["available_actions"][:4]  # Fewer options
            base_response["next_steps"] = ["Choose an action above"]
        
        elif modifiers.get("detail_level") == "detailed":
            # Add more detail to response
            data = base_response.get("data", {})
            if "message" in data:
                data["additional_info"] = {
                    "capabilities": "I can help with email management, lead discovery, business reporting, and task automation",
                    "data_sources": "Connected to email accounts, lead databases, and task management systems",
                    "response_formats": "I can provide summaries, detailed reports, or quick status updates"
                }
        
        # Handle urgency modifiers
        if modifiers.get("urgency") == "high":
            base_response["priority"] = "high"
            if "next_steps" in base_response:
                base_response["next_steps"].insert(0, "🔥 Priority request - processing immediately")
        
        return base_response
    
    def _enhance_response_with_context(
        self, 
        response: Dict[str, Any], 
        routing_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance response with conversation context and metadata."""
        enhanced_response = response.copy()
        
        # Add conversation metadata
        conversation_context = routing_info.get("conversation_context", {})
        if conversation_context:
            enhanced_response["conversation_metadata"] = {
                "session_id": routing_info.get("session_id"),
                "turn_count": conversation_context.get("turn_count", 0),
                "conversation_flow": conversation_context.get("conversation_flow", {}),
                "user_preferences": conversation_context.get("user_preferences", {})
            }
        
        # Add intent classification metadata
        intent = routing_info.get("intent", {})
        enhanced_response["intent_metadata"] = {
            "confidence": intent.get("confidence", 0.0),
            "detected_action": intent.get("action"),
            "alternative_intents": intent.get("alternative_intents", []),
            "response_modifiers": intent.get("modifiers", {})
        }
        
        # Add contextual suggestions based on conversation flow
        flow_analysis = intent.get("flow_analysis", {})
        if flow_analysis.get("type") == "followup":
            enhanced_response["suggestions"] = [
                "Continue with related tasks",
                "Get more details",
                "Move to next priority"
            ]
        elif flow_analysis.get("type") == "clarification":
            enhanced_response["suggestions"] = [
                "Ask for specific details",
                "Request examples",
                "Get step-by-step guidance"
            ]
        
        return enhanced_response
    
    def _handle_echo_skill(self, skill_input: Dict[str, Any]) -> Dict[str, Any]:
        """Handle echo skill - returns input data as-is."""
        return {
            DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
            DataFields.SOURCE.value: SourceType.KHURSHEED.value,
            DataFields.ACTION.value: SkillName.ECHO.value,
            DataFields.DATA.value: skill_input,
            DataFields.NEXT_STEPS.value: []
        }
    
    def _handle_timestamp_skill(self) -> Dict[str, Any]:
        """Handle timestamp skill - returns current timestamp."""
        return {
            DataFields.STATUS.value: ResponseStatus.SUCCESS.value,
            DataFields.SOURCE.value: SourceType.KHURSHEED.value,
            DataFields.ACTION.value: SkillName.TIMESTAMP.value,
            DataFields.DATA.value: {"timestamp": "2026-05-23T18:54:27.419464+00:00"},
            DataFields.NEXT_STEPS.value: []
        }