#!/usr/bin/env python3
"""
Enaam MCP Server CLI - Start/stop the MCP server

Provides command line interface to manage the MCP server.
"""

import sys
import time
import json
import requests
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from enaam.mcp.server import MCPServer, create_sample_requests
from enaam.config import config


def start_server(host: str = "localhost", port: int = 8080):
    """Start the MCP server"""
    print(f"🚀 Starting Enaam MCP Server on {host}:{port}...")
    
    server = MCPServer(host, port)
    result = server.start()
    
    if result["status"] == "success":
        print(f"✅ {result['message']}")
        print("\nEndpoints:")
        for endpoint in result["endpoints"]:
            print(f"  • {endpoint}")
        
        print("\n💡 Try these sample requests:")
        print("  curl -X POST http://localhost:8080/ \\")
        print("    -H 'Content-Type: application/json' \\")
        print("    -d '{\"method\": \"run_weekly_digest\", \"params\": {}, \"response_type\": \"json\"}'")
        
        # Keep server running
        try:
            print("\n⌨️  Press Ctrl+C to stop the server...")
            while server.is_active():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping server...")
            stop_result = server.stop()
            print(f"✅ {stop_result['message']}")
    else:
        print(f"❌ {result['message']}")
        sys.exit(1)


def test_server(host: str = "localhost", port: int = 8080):
    """Test the MCP server with sample requests"""
    server_url = f"http://{host}:{port}"
    
    print(f"🧪 Testing Enaam MCP Server at {server_url}")
    
    # Test server health
    try:
        response = requests.get(f"{server_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Server health check passed")
        else:
            print("❌ Server health check failed")
            return
    except requests.RequestException as e:
        print(f"❌ Cannot connect to server: {e}")
        return
    
    # Test sample requests
    sample_requests = create_sample_requests()
    
    for i, request in enumerate(sample_requests, 1):
        print(f"\n📋 Test {i}: {request['method']} ({request['response_type']})")
        
        try:
            response = requests.post(
                server_url,
                json=request,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Success")
                
                # Show preview of response
                if result.get("result"):
                    if request["response_type"] == "email":
                        email_data = result["result"]
                        print(f"     Subject: {email_data.get('subject', 'N/A')}")
                        body = email_data.get('body', '')
                        preview = body[:100] + "..." if len(body) > 100 else body
                        print(f"     Body: {preview}")
                    elif request["response_type"] == "chat":
                        chat_data = result["result"] 
                        message = chat_data.get('message', '')
                        preview = message[:100] + "..." if len(message) > 100 else message
                        print(f"     Message: {preview}")
                    else:
                        # JSON response
                        json_data = result["result"]["data"]
                        if "summary" in json_data:
                            summary = json_data["summary"]
                            preview = summary[:100] + "..." if len(summary) > 100 else summary
                            print(f"     Data: {preview}")
                        else:
                            print(f"     Status: {json_data.get('status', 'N/A')}")
            else:
                print(f"  ❌ Failed with status {response.status_code}")
                
        except requests.RequestException as e:
            print(f"  ❌ Request failed: {e}")


def show_help():
    """Show help information"""
    help_text = """
🤖 Enaam MCP Server CLI

Usage:
  python enaam/mcp_server.py start [host] [port]    Start the MCP server
  python enaam/mcp_server.py test [host] [port]     Test the MCP server
  python enaam/mcp_server.py help                   Show this help

Examples:
  python enaam/mcp_server.py start                  # Start on localhost:8080
  python enaam/mcp_server.py start 0.0.0.0 9000     # Start on all interfaces, port 9000
  python enaam/mcp_server.py test                   # Test localhost:8080
  
API Usage:
  GET  /                    - Server information
  GET  /health             - Health check
  GET  /capabilities       - Available capabilities
  POST /                   - MCP method calls

Sample curl request:
  curl -X POST http://localhost:8080/ \\
    -H 'Content-Type: application/json' \\
    -d '{
      "method": "chat_query",
      "params": {"query": "What are my priorities this week?"},
      "response_type": "chat",
      "id": "test-1"
    }'

Available methods:
  • run_skill              - Execute a Khursheed skill
  • run_bridge            - Execute a Khursheed bridge function
  • run_weekly_digest     - Generate weekly digest
  • run_lead_scan         - Run lead discovery
  • chat_query            - Process chat-style queries

Response types:
  • json                  - Structured JSON response
  • email                 - Email-formatted response
  • chat                  - Chat-formatted response
"""
    print(help_text)


def main():
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == "start":
        host = sys.argv[2] if len(sys.argv) > 2 else "localhost"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
        start_server(host, port)
    elif command == "test":
        host = sys.argv[2] if len(sys.argv) > 2 else "localhost"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
        test_server(host, port)
    elif command == "help":
        show_help()
    else:
        print(f"❌ Unknown command: {command}")
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()