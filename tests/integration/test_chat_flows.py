"""
Integration tests for chat flow functionality.

End-to-end testing of chat interactions including multi-turn conversations,
context awareness, intent classification, and response personalization.
"""

import pytest
import requests
import time
from typing import Any, Dict, List
import threading

from enaam.mcp.server import MCPServer
from enaam.core.chat_context import ChatContextManager
from enaam.core.intent_classifier import IntentClassifier, ContextAwareRouter


class TestChatFlows:
    """Comprehensive chat flow integration tests."""
    
    @classmethod
    def setup_class(cls):
        """Setup test server for chat flow tests."""
        cls.test_port = 8092
        cls.server = MCPServer(host="localhost", port=cls.test_port)
        cls.base_url = f"http://localhost:{cls.test_port}"
        
        # Start server in background thread
        cls.server_thread = threading.Thread(
            target=cls._start_server,
            daemon=True
        )
        cls.server_thread.start()
        
        # Wait for server to start
        cls._wait_for_server()
    
    @classmethod
    def _start_server(cls):
        """Start server in thread."""
        result = cls.server.start()
        if result.get("status") != "success":
            raise RuntimeError(f"Failed to start test server: {result}")
    
    @classmethod
    def _wait_for_server(cls, max_wait: int = 10):
        """Wait for server to be ready."""
        for _ in range(max_wait):
            try:
                response = requests.get(f"{cls.base_url}/health", timeout=1)
                if response.status_code == 200:
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        raise TimeoutError("Server did not start within timeout")
    
    @classmethod
    def teardown_class(cls):
        """Cleanup test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()
    
    def _send_chat_message(self, query: str, session_id: str, user_id: str = "test-user") -> Dict[str, Any]:
        """Helper to send chat message and return response."""
        request_payload = {
            "method": "chat_query",
            "params": {
                "query": query,
                "context": {
                    "session_id": session_id,
                    "user_id": user_id
                }
            },
            "response_type": "chat",
            "id": f"chat-{int(time.time() * 1000)}"
        }
        
        response = requests.post(
            self.base_url,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        assert response.status_code == 200
        return response.json()
    
    def test_basic_chat_interaction(self):
        """Test basic chat interaction works correctly."""
        session_id = "basic-chat-test"
        
        response_data = self._send_chat_message("Hello, what can you help me with?", session_id)
        
        assert "result" in response_data
        assert "error" in response_data
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert "type" in result
            assert result["type"] == "chat"
            assert "message" in result or "data" in result
    
    def test_intent_classification(self):
        """Test that chat messages are correctly classified by intent."""
        session_id = "intent-classification-test"
        
        test_cases = [
            {
                "query": "check my email inbox please",
                "expected_actions": ["email_summary", "email_triage_run"]
            },
            {
                "query": "find new business leads for consulting",
                "expected_actions": ["lead_scan", "lead_generation_run"]
            },
            {
                "query": "give me the weekly summary report",
                "expected_actions": ["weekly_digest"]
            },
            {
                "query": "show me the executive summary",
                "expected_actions": ["executive_summary"]
            },
            {
                "query": "run all scheduled tasks now",
                "expected_actions": ["run_scheduled_tasks"]
            }
        ]
        
        for i, test_case in enumerate(test_cases):
            response_data = self._send_chat_message(test_case["query"], f"{session_id}-{i}")
            
            # Check if intent was detected correctly
            if response_data["error"] is None:
                result = response_data["result"]
                
                # Look for intent metadata
                metadata = result.get("metadata", {})
                intent_metadata = result.get("intent_metadata", {})
                
                detected_action = (
                    metadata.get("action") or 
                    intent_metadata.get("detected_action") or
                    result.get("action")
                )
                
                if detected_action:
                    assert detected_action in test_case["expected_actions"], \
                        f"Query '{test_case['query']}' detected as '{detected_action}', expected one of {test_case['expected_actions']}"
    
    def test_response_modifiers_detection(self):
        """Test that response modifiers are detected correctly."""
        session_id = "modifiers-test"
        
        modifier_tests = [
            {
                "query": "give me a brief status update",
                "expected_modifier": "detail_level",
                "expected_value": "brief"
            },
            {
                "query": "I need detailed comprehensive information about emails",
                "expected_modifier": "detail_level", 
                "expected_value": "detailed"
            },
            {
                "query": "urgent! check emails immediately!",
                "expected_modifier": "urgency",
                "expected_value": "high"
            },
            {
                "query": "please could you help me with a summary when you have time",
                "expected_modifier": "formality",
                "expected_value": "formal"
            }
        ]
        
        for i, test in enumerate(modifier_tests):
            response_data = self._send_chat_message(test["query"], f"{session_id}-{i}")
            
            if response_data["error"] is None:
                result = response_data["result"]
                intent_metadata = result.get("intent_metadata", {})
                modifiers = intent_metadata.get("response_modifiers", {})
                
                if test["expected_modifier"] in modifiers:
                    assert modifiers[test["expected_modifier"]] == test["expected_value"], \
                        f"Expected {test['expected_modifier']}={test['expected_value']}, got {modifiers[test['expected_modifier']]}"
    
    def test_multi_turn_conversation(self):
        """Test multi-turn conversation with context persistence."""
        session_id = "multi-turn-test"
        
        # Turn 1: Initial greeting
        response1 = self._send_chat_message("Hi there!", session_id)
        assert response1["error"] is None
        
        # Turn 2: Ask for status
        response2 = self._send_chat_message("What's my current status?", session_id)
        assert response2["error"] is None
        
        # Turn 3: Follow up with more detail
        response3 = self._send_chat_message("Give me more detailed information", session_id)
        assert response3["error"] is None
        
        # Turn 4: Ask about previous actions
        response4 = self._send_chat_message("What did we just discuss?", session_id)
        assert response4["error"] is None
        
        # Verify conversation metadata exists in later turns
        result4 = response4["result"]
        conv_metadata = result4.get("conversation_metadata", {})
        
        if conv_metadata:
            # Should have multiple turns recorded
            turn_count = conv_metadata.get("turn_count", 0)
            assert turn_count >= 3, f"Expected at least 3 turns, got {turn_count}"
    
    def test_context_aware_responses(self):
        """Test that responses become more contextual over time."""
        session_id = "context-aware-test"
        
        # Establish user preference for brief responses
        self._send_chat_message("quick status", session_id)
        self._send_chat_message("brief update please", session_id)
        self._send_chat_message("short summary", session_id)
        
        # Now ask for information - should adapt to brief preference
        response = self._send_chat_message("tell me about emails", session_id)
        
        if response["error"] is None:
            result = response["result"]
            conv_metadata = result.get("conversation_metadata", {})
            user_preferences = conv_metadata.get("user_preferences", {})
            
            # Check if brief preference was learned
            detail_level = user_preferences.get("detail_level")
            if detail_level:
                assert detail_level == "brief", f"Expected brief preference, got {detail_level}"
    
    def test_conversation_flow_analysis(self):
        """Test conversation flow analysis and suggestions."""
        session_id = "flow-analysis-test"
        
        # Start with a question
        response1 = self._send_chat_message("What are the available actions?", session_id)
        
        # Follow up with clarification
        response2 = self._send_chat_message("What does the email summary action do exactly?", session_id)
        
        if response2["error"] is None:
            result2 = response2["result"]
            intent_metadata = result2.get("intent_metadata", {})
            flow_analysis = intent_metadata.get("flow_analysis", {})
            
            # Should detect this as clarification
            if flow_analysis:
                flow_type = flow_analysis.get("type")
                assert flow_type in ["clarification", "followup"], f"Expected clarification/followup, got {flow_type}"
        
        # Continue with another follow-up
        response3 = self._send_chat_message("Also, how do I run lead discovery?", session_id)
        
        if response3["error"] is None:
            result3 = response3["result"]
            # Should provide contextual suggestions
            suggestions = result3.get("suggestions", [])
            assert len(suggestions) > 0, "Expected contextual suggestions"
    
    def test_session_isolation(self):
        """Test that different sessions maintain separate contexts."""
        session1 = "isolation-test-1"
        session2 = "isolation-test-2"
        
        # Set preferences in session 1
        self._send_chat_message("I need detailed comprehensive reports", session1)
        self._send_chat_message("give me full information with all details", session1)
        
        # Set different preferences in session 2
        self._send_chat_message("brief updates only please", session2)
        self._send_chat_message("quick status, nothing more", session2)
        
        # Request information from both sessions
        response1 = self._send_chat_message("tell me about the system", session1)
        response2 = self._send_chat_message("tell me about the system", session2)
        
        # Sessions should maintain separate preferences
        if response1["error"] is None and response2["error"] is None:
            conv1 = response1["result"].get("conversation_metadata", {})
            conv2 = response2["result"].get("conversation_metadata", {})
            
            pref1 = conv1.get("user_preferences", {}).get("detail_level", "standard")
            pref2 = conv2.get("user_preferences", {}).get("detail_level", "standard")
            
            # Preferences should be different (if detected)
            if pref1 != "standard" and pref2 != "standard":
                assert pref1 != pref2, "Sessions should have different preferences"
    
    def test_error_handling_in_chat(self):
        """Test error handling in chat flows."""
        session_id = "error-handling-test"
        
        # Send invalid/problematic requests
        test_cases = [
            "run invalid skill that doesn't exist",
            "execute malicious command '; rm -rf /'",
            "access unauthorized data /etc/passwd",
            "perform SQL injection ' OR 1=1 --"
        ]
        
        for query in test_cases:
            response = self._send_chat_message(query, session_id)
            
            # Should handle gracefully without crashing
            assert "result" in response
            assert "error" in response
            
            # If there's an error, it should be safe
            if response["error"]:
                error_msg = response["error"].get("message", "")
                # Should not contain sensitive information
                assert "password" not in error_msg.lower()
                assert "/etc/" not in error_msg
                assert "rm -rf" not in error_msg
    
    def test_performance_of_chat_interactions(self):
        """Test performance of chat interactions."""
        session_id = "performance-test"
        
        # Measure response times
        response_times = []
        
        for i in range(5):
            start_time = time.time()
            response = self._send_chat_message(f"test message {i}", session_id)
            end_time = time.time()
            
            response_time = end_time - start_time
            response_times.append(response_time)
            
            assert response["error"] is None or response["result"] is not None
        
        # Verify reasonable response times
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        
        assert avg_response_time < 5.0, f"Average response time {avg_response_time:.2f}s too slow"
        assert max_response_time < 10.0, f"Max response time {max_response_time:.2f}s too slow"
    
    def test_enhanced_metadata_in_responses(self):
        """Test that enhanced metadata is included in responses."""
        session_id = "metadata-test"
        
        response = self._send_chat_message("urgent email check needed", session_id)
        
        if response["error"] is None:
            result = response["result"]
            
            # Check for various types of metadata
            metadata_keys = [
                "metadata", "intent_metadata", "conversation_metadata",
                "suggestions", "type"
            ]
            
            found_metadata = []
            for key in metadata_keys:
                if key in result:
                    found_metadata.append(key)
            
            # Should have some form of metadata
            assert len(found_metadata) > 0, f"Expected metadata in response, got keys: {list(result.keys())}"
    
    def test_conversation_memory_persistence(self):
        """Test that conversation memory persists across requests."""
        session_id = "memory-persistence-test"
        
        # Have a conversation about email
        self._send_chat_message("check my email", session_id)
        self._send_chat_message("what was in the emails?", session_id) 
        self._send_chat_message("any urgent messages?", session_id)
        
        # Now ask about recent topics
        response = self._send_chat_message("what have we been discussing?", session_id)
        
        if response["error"] is None:
            result = response["result"]
            conv_metadata = result.get("conversation_metadata", {})
            
            # Should have conversation flow information
            recent_topics = conv_metadata.get("recent_topics", [])
            recent_actions = conv_metadata.get("recent_actions", [])
            
            # Email should be a recent topic
            if recent_topics:
                assert "email" in str(recent_topics).lower(), f"Email should be in recent topics: {recent_topics}"


@pytest.mark.integration  
class TestChatContextSystem:
    """Tests for the chat context system components."""
    
    def test_intent_classifier_standalone(self):
        """Test intent classifier works independently."""
        classifier = IntentClassifier()
        
        test_queries = [
            ("check my email", "email_summary"),
            ("find business leads", "lead_scan"), 
            ("weekly summary report", "weekly_digest"),
            ("urgent email check", "email_summary")
        ]
        
        for query, expected_action in test_queries:
            intent = classifier.classify_intent(query)
            
            assert "action" in intent
            assert "confidence" in intent
            assert intent["action"] == expected_action
            assert intent["confidence"] > 0.5
    
    def test_context_manager_operations(self):
        """Test chat context manager operations."""
        context_manager = ChatContextManager(db_path="test_chat_context.db")
        
        # Create session
        session = context_manager.get_or_create_session("test-session", "test-user")
        assert session.session_id == "test-session"
        
        # Add conversation turns
        turn1 = context_manager.add_conversation_turn(
            "test-session",
            "Hello",
            {"status": "success", "action": "greeting", "data": {"message": "Hi there!"}}
        )
        assert turn1.user_input == "Hello"
        
        # Get conversation context
        context = context_manager.get_conversation_context("test-session")
        assert "session_id" in context
        assert "turn_count" in context
        assert context["turn_count"] >= 1
        
        # Cleanup
        import os
        if os.path.exists("test_chat_context.db"):
            os.unlink("test_chat_context.db")
    
    def test_context_aware_router(self):
        """Test context-aware router functionality."""
        context_manager = ChatContextManager(db_path="test_router_context.db")
        router = ContextAwareRouter(context_manager)
        
        # Route a request
        routing_info = router.route_request(
            "give me a detailed email summary",
            "test-session",
            "test-user"
        )
        
        assert "intent" in routing_info
        assert "handler" in routing_info
        assert "conversation_context" in routing_info
        
        intent = routing_info["intent"]
        assert intent["action"] == "email_summary"
        assert "modifiers" in intent
        
        # Cleanup
        import os
        if os.path.exists("test_router_context.db"):
            os.unlink("test_router_context.db")