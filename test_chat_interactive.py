#!/usr/bin/env python3
"""
Interactive Chat Tester for Enaam Platform
Run this script to have a live chat session with your Enaam assistant
"""

import requests
import json
import time
from typing import Dict, Any

class EnaasomeChatTester:
    def __init__(self, server_url: str = "http://localhost:8092"):
        self.server_url = server_url
        self.session_id = f"interactive-session-{int(time.time())}"
        self.user_id = "test-user"
        
    def send_chat(self, query: str) -> Dict[str, Any]:
        """Send a chat message and return the response"""
        payload = {
            "method": "chat_query",
            "params": {
                "query": query,
                "context": {
                    "session_id": self.session_id,
                    "user_id": self.user_id
                }
            },
            "response_type": "chat",
            "id": f"chat-{int(time.time() * 1000)}"
        }
        
        try:
            response = requests.post(
                self.server_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}: {response.text}"}
                
        except requests.exceptions.RequestException as e:
            return {"error": f"Request failed: {e}"}
    
    def format_response(self, response: Dict[str, Any]) -> str:
        """Format the chat response for display"""
        if "error" in response:
            return f"❌ Error: {response['error']}"
        
        if response.get("error"):
            return f"❌ Server Error: {response['error']}"
            
        result = response.get("result", {})
        message = result.get("message", "No message")
        suggestions = result.get("suggestions", [])
        metadata = result.get("metadata", {})
        
        output = f"🤖 Enaam: {message}\n"
        
        if suggestions:
            output += f"\n💡 Suggestions:\n"
            for i, suggestion in enumerate(suggestions, 1):
                output += f"   {i}. {suggestion}\n"
        
        if metadata.get("action"):
            output += f"\n🔧 Action: {metadata['action']} (from {metadata.get('source', 'unknown')})"
            
        return output
    
    def interactive_session(self):
        """Start an interactive chat session"""
        print("🚀 Welcome to Enaam Interactive Chat!")
        print("🔗 Connected to:", self.server_url)
        print("📱 Session ID:", self.session_id)
        print("Type 'quit', 'exit', or 'bye' to end the session\n")
        
        # Test server connectivity
        print("🔄 Testing connection...")
        health_response = self.send_chat("Hello")
        if "error" in health_response:
            print(f"❌ Cannot connect to server: {health_response['error']}")
            return
        print("✅ Connection successful!\n")
        
        while True:
            try:
                user_input = input("👤 You: ").strip()
                
                if not user_input:
                    continue
                    
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    print("👋 Goodbye!")
                    break
                
                print("🔄 Processing...")
                response = self.send_chat(user_input)
                print(self.format_response(response))
                print()
                
            except KeyboardInterrupt:
                print("\n👋 Session ended by user")
                break
            except Exception as e:
                print(f"❌ Unexpected error: {e}")


def main():
    """Main function to run the interactive chat tester"""
    import sys
    
    # Allow custom server URL
    server_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8092"
    
    tester = EnaasomeChatTester(server_url)
    tester.interactive_session()


if __name__ == "__main__":
    main()