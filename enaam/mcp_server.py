#!/usr/bin/env python3
"""
Enaam MCP Server CLI - Start/stop the MCP server

Provides command line interface to manage the MCP server.
"""

import logging
import sys
import time
from typing import Dict, List, Any

import requests

# Setup CLI logger
cli_logger = logging.getLogger('enaam.mcp_cli')

from .core.constants import (
    APIConstants,
    DefaultValues,
    MagicStringConstants,
    TestConstants,
    CLIConstants
)
from .core.enums import (
    ResponseStatus,
    DataFields
)
from .mcp.server import MCPServer
from .mcp.server import create_sample_requests
from .mcp.schemas import MCPMethod, ResponseType


def start_server(host: str = MagicStringConstants.LOCALHOST, port: int = DefaultValues.SERVER_PORT) -> None:
    """Start the MCP server"""
    cli_logger.info("Starting MCP server on %s:%d", host, port)
    print(f"🚀 Starting Enaam MCP Server on {host}:{port}...")
    
    server = MCPServer(host, port)
    result = server.start()
    
    if result[DataFields.STATUS.value] == ResponseStatus.SUCCESS.value:
        cli_logger.info("MCP server started successfully")
        print(f"✅ {result['message']}")
        print("\nEndpoints:")
        for endpoint in result["endpoints"]:
            print(f"  • {endpoint}")
        
        print("\n💡 Try these sample requests:")
        print("  curl -X POST http://localhost:8080/ \\")
        print(f"    -H '{APIConstants.CONTENT_TYPE_HEADER}: {APIConstants.APPLICATION_JSON}' \\")
        print("    -d '{\"method\": \"run_weekly_digest\", \"params\": {}, \"response_type\": \"json\"}'")
        
        # Keep server running
        try:
            print("\n⌨️  Press Ctrl+C to stop the server...")
            while server.is_active():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping server...")
            stop_result = server.stop()
            cli_logger.info("MCP server stopped")
            print(f"✅ {stop_result['message']}")
    else:
        cli_logger.error("Failed to start MCP server: %s", result['message'])
        print(f"❌ {result['message']}")
        sys.exit(1)


def test_server(host: str = MagicStringConstants.LOCALHOST, port: int = DefaultValues.SERVER_PORT) -> None:
    """Test the MCP server with sample requests"""
    server_url = f"http://{host}:{port}"
    
    cli_logger.info("Testing MCP server at %s", server_url)
    print(f"🧪 Testing Enaam MCP Server at {server_url}")
    
    # Test server health
    try:
        response = requests.get(f"{server_url}/health", timeout=APIConstants.HEALTH_CHECK_TIMEOUT)
        if response.status_code == 200:
            cli_logger.info("Server health check passed")
            print("✅ Server health check passed")
        else:
            cli_logger.error("Server health check failed with status %d", response.status_code)
            print("❌ Server health check failed")
            return
    except requests.RequestException as e:
        cli_logger.error("Cannot connect to server: %s", str(e))
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
                headers={APIConstants.CONTENT_TYPE_HEADER: APIConstants.APPLICATION_JSON},
                timeout=APIConstants.DEFAULT_HTTP_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"  ✅ Success")
                
                # Show preview of response
                if result.get("result"):
                    if request[DataFields.RESPONSE_TYPE.value] == ResponseType.EMAIL.value:
                        email_data = result["result"]
                        print(f"     Subject: {email_data.get('subject', 'N/A')}")
                        body = email_data.get('body', '')
                        preview = body[:100] + "..." if len(body) > 100 else body
                        print(f"     Body: {preview}")
                    elif request[DataFields.RESPONSE_TYPE.value] == ResponseType.CHAT.value:
                        chat_data = result["result"] 
                        message = chat_data.get('message', '')
                        preview = message[:100] + "..." if len(message) > 100 else message
                        print(f"     Message: {preview}")
                    else:
                        # JSON response
                        json_data = result["result"]["data"]
                        if DataFields.SUMMARY.value in json_data:
                            summary = json_data[DataFields.SUMMARY.value]
                            preview = summary[:100] + "..." if len(summary) > 100 else summary
                            print(f"     Data: {preview}")
                        else:
                            print(f"     Status: {json_data.get(DataFields.STATUS.value, MagicStringConstants.NOT_AVAILABLE)}")
            else:
                print(f"  ❌ Failed with status {response.status_code}")
                
        except requests.RequestException as e:
            print(f"  ❌ Request failed: {e}")


def show_help() -> None:
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


def main() -> None:
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        show_help()
        return
    
    command = sys.argv[1].lower()
    
    if command == MagicStringConstants.START_COMMAND:
        host = sys.argv[2] if len(sys.argv) > 2 else MagicStringConstants.LOCALHOST
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
        start_server(host, port)
    elif command == MagicStringConstants.TEST_COMMAND:
        host = sys.argv[2] if len(sys.argv) > 2 else MagicStringConstants.LOCALHOST
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
        test_server(host, port)
    elif command == MagicStringConstants.HELP_COMMAND:
        show_help()
    else:
        print(f"❌ Unknown command: {command}")
        show_help()
        sys.exit(1)


if __name__ == MagicStringConstants.MAIN_MODULE:
    main()