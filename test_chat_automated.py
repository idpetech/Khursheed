#!/usr/bin/env python3
"""
Automated Chat Test Suite for Enaam Platform
Comprehensive testing of chat functionality including intent detection, 
multi-turn conversations, and response quality.
"""

import requests
import json
import time
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class ChatTest:
    name: str
    query: str
    expected_action: str = None
    expected_keywords: List[str] = None
    session_id: str = "auto-test-session"

class EnaanChatTestSuite:
    def __init__(self, server_url: str = "http://localhost:8092"):
        self.server_url = server_url
        self.test_results = []
        
    def send_chat(self, query: str, session_id: str = "test-session") -> Dict[str, Any]:
        """Send a chat message and return the response"""
        payload = {
            "method": "chat_query", 
            "params": {
                "query": query,
                "context": {
                    "session_id": session_id,
                    "user_id": "automated-tester"
                }
            },
            "response_type": "chat",
            "id": f"auto-test-{int(time.time() * 1000)}"
        }
        
        response = requests.post(
            self.server_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        return response.json()
    
    def run_test(self, test: ChatTest) -> Dict[str, Any]:
        """Run a single chat test"""
        print(f"🧪 Testing: {test.name}")
        print(f"   Query: '{test.query}'")
        
        try:
            response = self.send_chat(test.query, test.session_id)
            
            if response.get("error"):
                result = {"status": "error", "message": response["error"]}
            else:
                result_data = response.get("result", {})
                message = result_data.get("message", "")
                metadata = result_data.get("metadata", {})
                action = metadata.get("action")
                
                # Check expected action
                action_match = True
                if test.expected_action:
                    action_match = action == test.expected_action
                
                # Check expected keywords
                keyword_matches = []
                if test.expected_keywords:
                    for keyword in test.expected_keywords:
                        if keyword.lower() in message.lower():
                            keyword_matches.append(keyword)
                
                result = {
                    "status": "success" if action_match else "partial",
                    "message": message,
                    "detected_action": action,
                    "expected_action": test.expected_action,
                    "action_match": action_match,
                    "keyword_matches": keyword_matches,
                    "response_time": response.get("response_time", "unknown")
                }
            
            print(f"   ✅ Result: {result['status']}")
            if result.get("detected_action"):
                print(f"   🎯 Action: {result['detected_action']}")
            
            return result
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            return {"status": "error", "message": str(e)}
    
    def run_full_suite(self):
        """Run the complete test suite"""
        print("🚀 Starting Enaam Chat Test Suite")
        print("=" * 50)
        
        # Define test cases
        test_cases = [
            # Basic functionality
            ChatTest("Basic Greeting", "Hello", expected_keywords=["help", "Enaam"]),
            ChatTest("Simple Question", "What can you do?", expected_keywords=["help"]),
            
            # Intent detection tests
            ChatTest("Email Intent", "Check my email", "email_summary"),
            ChatTest("Email Variation", "Show me my emails please", "email_summary"), 
            ChatTest("Weekly Summary", "Give me the weekly digest", "weekly_digest"),
            ChatTest("Weekly Variation", "I need this week's summary", "weekly_digest"),
            ChatTest("Executive Summary", "Show me the executive summary", "executive_summary"),
            
            # Urgency detection
            ChatTest("Urgent Email", "urgent! check emails immediately!", "email_summary", ["urgent"]),
            ChatTest("Quick Request", "quick status update please", expected_keywords=["status"]),
            
            # Lead generation
            ChatTest("Lead Discovery", "find new business leads", "lead_scan"),
            ChatTest("Lead Generation", "generate leads for consulting", "lead_generation_run"),
            
            # Conversation flow
            ChatTest("Follow-up Question", "what was in the summary?", session_id="follow-up-session"),
            ChatTest("Context Request", "tell me more details", session_id="follow-up-session"),
        ]
        
        # Run tests
        passed = 0
        failed = 0
        
        for test in test_cases:
            result = self.run_test(test)
            self.test_results.append({"test": test, "result": result})
            
            if result["status"] == "success":
                passed += 1
            else:
                failed += 1
            
            print()
            time.sleep(1)  # Rate limiting
        
        # Print summary
        total = passed + failed
        success_rate = (passed / total * 100) if total > 0 else 0
        
        print("=" * 50)
        print("📊 TEST SUMMARY")
        print(f"✅ Passed: {passed}/{total} ({success_rate:.1f}%)")
        print(f"❌ Failed: {failed}/{total}")
        print()
        
        # Print detailed results
        if failed > 0:
            print("❌ FAILED TESTS:")
            for item in self.test_results:
                if item["result"]["status"] != "success":
                    test = item["test"]
                    result = item["result"]
                    print(f"   • {test.name}: {result.get('message', 'Unknown error')}")
        
        print("🎉 Chat testing complete!")
        return {"passed": passed, "failed": failed, "success_rate": success_rate}


def main():
    """Run the automated chat test suite"""
    import sys
    
    server_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8092"
    
    suite = EnaanChatTestSuite(server_url)
    results = suite.run_full_suite()
    
    # Exit with error code if tests failed
    exit_code = 0 if results["failed"] == 0 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()