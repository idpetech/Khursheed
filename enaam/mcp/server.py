"""
Enaam MCP Server - Lightweight MCP server exposing all skills and bridges

Provides API access to Khursheed skills and Enaam bridges via MCP protocol.
"""

import json
from typing import Dict, Any, List, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
from urllib.parse import urlparse, parse_qs

from .handlers import MCPHandler
from .schemas import validate_mcp_request, MCPMethod, ResponseType
from .registry import MCPRegistry


logger = logging.getLogger(__name__)


class MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server"""
    
    def __init__(self, mcp_handler: MCPHandler, *args, **kwargs):
        self.mcp_handler = mcp_handler
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests - server info and health checks"""
        if self.path == "/":
            self._send_server_info()
        elif self.path == "/health":
            self._send_health_check()
        elif self.path == "/capabilities":
            self._send_capabilities()
        else:
            self._send_error(404, "Endpoint not found")
    
    def do_POST(self):
        """Handle POST requests - MCP method calls"""
        try:
            # Parse request
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            request_data = json.loads(post_data.decode('utf-8'))
            
            # Validate and process request
            mcp_request = validate_mcp_request(request_data)
            mcp_response = self.mcp_handler.handle_request(mcp_request)
            
            # Send response
            self._send_json_response(200, mcp_response.__dict__)
            
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
        except ValueError as e:
            self._send_error(400, str(e))
        except Exception as e:
            logger.error(f"Server error: {e}")
            self._send_error(500, "Internal server error")
    
    def _send_server_info(self):
        """Send server information"""
        info = {
            "name": "Enaam MCP Server",
            "version": "1.0.0",
            "description": "Lightweight MCP server exposing Khursheed skills and Enaam bridges",
            "endpoints": {
                "/": "Server information",
                "/health": "Health check",
                "/capabilities": "Available capabilities",
                "POST /": "MCP method calls"
            }
        }
        self._send_json_response(200, info)
    
    def _send_health_check(self):
        """Send health check response"""
        health = {
            "status": "healthy",
            "timestamp": "2026-05-23T18:54:27.419464+00:00",
            "services": {
                "mcp_handler": "active",
                "khursheed_bridge": "active",
                "enaam_agent": "active"
            }
        }
        self._send_json_response(200, health)
    
    def _send_capabilities(self):
        """Send server capabilities"""
        capabilities = {
            "methods": [method.value for method in MCPMethod],
            "response_types": [resp_type.value for resp_type in ResponseType],
            "bridge_functions": [
                "email_summary", "lead_scan", "weekly_digest", "executive_summary",
                "run_scheduled_tasks", "weekly_monday_9am_digest", 
                "lead_generation_run", "email_triage_run", "get_execution_logs"
            ],
            "skills": ["sifter", "lead_scout", "echo", "timestamp"]
        }
        self._send_json_response(200, capabilities)
    
    def _send_json_response(self, status_code: int, data: Dict[str, Any]):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        
        response_json = json.dumps(data, indent=2)
        self.wfile.write(response_json.encode('utf-8'))
    
    def _send_error(self, status_code: int, message: str):
        """Send error response"""
        error_data = {
            "error": {
                "code": status_code,
                "message": message
            }
        }
        self._send_json_response(status_code, error_data)
    
    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr"""
        logger.info(f"{self.address_string()} - {format % args}")


class MCPServer:
    """Lightweight MCP server for Enaam"""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.handler = MCPHandler()
        self.registry = MCPRegistry()
        self.server = None
        self.server_thread = None
        self.active = False
        
        # Register capabilities
        self._register_capabilities()
    
    def _register_capabilities(self):
        """Register server capabilities in registry"""
        # Register MCP methods
        for method in MCPMethod:
            self.registry.register_tool(method.value, method)
        
        # Register bridge functions
        bridge_functions = [
            "email_summary", "lead_scan", "weekly_digest", "executive_summary",
            "run_scheduled_tasks", "weekly_monday_9am_digest", 
            "lead_generation_run", "email_triage_run", "get_execution_logs"
        ]
        
        for func in bridge_functions:
            self.registry.register_resource(f"bridge:{func}", func)
    
    def start(self) -> Dict[str, Any]:
        """Start the MCP server"""
        if self.active:
            return {
                "status": "error",
                "message": "Server already running",
                "host": self.host,
                "port": self.port
            }
        
        try:
            # Create HTTP server with custom handler
            def handler_factory(*args, **kwargs):
                return MCPRequestHandler(self.handler, *args, **kwargs)
            
            self.server = HTTPServer((self.host, self.port), handler_factory)
            
            # Start server in separate thread
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                daemon=True,
                name="MCPServerThread"
            )
            self.server_thread.start()
            self.active = True
            
            logger.info(f"MCP server started on {self.host}:{self.port}")
            
            return {
                "status": "success",
                "message": f"MCP server started on {self.host}:{self.port}",
                "host": self.host,
                "port": self.port,
                "endpoints": [
                    f"http://{self.host}:{self.port}/",
                    f"http://{self.host}:{self.port}/health",
                    f"http://{self.host}:{self.port}/capabilities"
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return {
                "status": "error",
                "message": f"Failed to start server: {str(e)}"
            }
    
    def stop(self) -> Dict[str, Any]:
        """Stop the MCP server"""
        if not self.active:
            return {
                "status": "error",
                "message": "Server not running"
            }
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            
            if self.server_thread:
                self.server_thread.join(timeout=5)
            
            self.active = False
            self.server = None
            self.server_thread = None
            
            logger.info("MCP server stopped")
            
            return {
                "status": "success",
                "message": "MCP server stopped"
            }
            
        except Exception as e:
            logger.error(f"Error stopping MCP server: {e}")
            return {
                "status": "error",
                "message": f"Error stopping server: {str(e)}"
            }
    
    def is_active(self) -> bool:
        """Check if server is active"""
        return self.active
    
    def get_status(self) -> Dict[str, Any]:
        """Get server status"""
        return {
            "active": self.active,
            "host": self.host,
            "port": self.port,
            "thread_alive": self.server_thread.is_alive() if self.server_thread else False,
            "capabilities": self.list_capabilities()
        }
    
    def list_capabilities(self) -> List[str]:
        """List MCP server capabilities"""
        return [
            "run_skill",
            "run_bridge", 
            "run_weekly_digest",
            "run_lead_scan",
            "chat_query",
            "email_output",
            "json_output",
            "chat_output"
        ]


# Example usage functions for testing
def create_sample_requests() -> List[Dict[str, Any]]:
    """Create sample MCP requests for testing"""
    return [
        {
            "method": "run_weekly_digest",
            "params": {},
            "response_type": "json",
            "id": "test-1"
        },
        {
            "method": "chat_query",
            "params": {"query": "What are my priorities this week?"},
            "response_type": "chat",
            "id": "test-2"
        },
        {
            "method": "run_bridge",
            "params": {"function_name": "executive_summary"},
            "response_type": "email",
            "id": "test-3"
        }
    ]