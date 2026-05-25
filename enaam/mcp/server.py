"""
Enaam MCP Server - Lightweight MCP server exposing all skills and bridges

Provides API access to Khursheed skills and Enaam bridges via MCP protocol.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from typing import Any, Optional, Set

from ..core.constants import APIConstants, MagicStringConstants, ValidationMessages
from ..core.error_handler import get_error_logger
from ..core.exceptions import (
    ValidationError, 
    create_safe_error_response,
    sanitize_error_for_client,
    log_error_safely
)
from ..core.validation import (
    RateLimiter, 
    InputValidator, 
    SecurityValidator,
    create_rate_limiter, 
    create_input_validator,
    create_security_validator
)
from .handlers import MCPHandler
from .registry import MCPRegistry
from .schemas import MCPMethod
from .schemas import ResponseType
from .schemas import validate_mcp_request


# Removed global logger - use dependency injection instead


def create_mcp_logger() -> logging.Logger:
    """Factory function to create MCP logger - eliminates global state."""
    return logging.getLogger(__name__)


class MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MCP server"""
    
    def __init__(self, mcp_handler: MCPHandler, rate_limiter: RateLimiter, 
                 input_validator: InputValidator, security_validator: SecurityValidator,
                 *args, **kwargs):
        self.mcp_handler = mcp_handler
        self.rate_limiter = rate_limiter
        self.input_validator = input_validator
        self.security_validator = security_validator
        
        # Define allowed values
        self.allowed_methods = {method.value for method in MCPMethod}
        self.allowed_response_types = {resp_type.value for resp_type in ResponseType}
        self.allowed_skills = {"echo", "sifter", "lead_scout", "timestamp"}
        self.allowed_functions = {
            "email_summary", "lead_scan", "weekly_digest", "executive_summary",
            "run_scheduled_tasks", "weekly_monday_9am_digest", 
            "lead_generation_run", "email_triage_run", "get_execution_logs"
        }
        
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
            # Get client IP for rate limiting
            client_ip = self.client_address[0]
            error_logger = get_error_logger('mcp_server')
            
            # Check rate limiting
            if not self.rate_limiter.is_allowed(client_ip):
                error_logger.warning("Rate limit exceeded for IP: %s", client_ip)
                self._send_error(429, ValidationMessages.RATE_LIMIT_EXCEEDED)
                return
            
            # Validate request size
            content_length = int(self.headers.get('Content-Length', 0))
            self.input_validator.validate_request_size(content_length)
            
            # Parse request with size limit protection
            post_data = self.rfile.read(content_length)
            if len(post_data) != content_length:
                raise ValidationError(ValidationMessages.INVALID_REQUEST)
            
            # Parse JSON with security validation
            try:
                request_data = json.loads(post_data.decode('utf-8'))
            except UnicodeDecodeError:
                raise ValidationError(ValidationMessages.INVALID_REQUEST)
            
            # Validate JSON structure and detect injection attempts
            self.input_validator.validate_json_structure(request_data)
            self.security_validator.validate_safe_input(request_data)
            
            # Comprehensive parameter validation
            self._validate_mcp_request(request_data)
            
            # Validate and process request
            mcp_request = validate_mcp_request(request_data)
            mcp_response = self.mcp_handler.handle_request(mcp_request)
            
            # Send response
            self._send_json_response(200, mcp_response.__dict__)
            
            # Log successful request (sanitized)
            sanitized_data = self.input_validator.sanitize_log_data(request_data)
            error_logger.info("Processed MCP request from %s: %s", client_ip, sanitized_data.get('method', 'unknown'))
            
        except json.JSONDecodeError as e:
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'client_ip': client_ip, 'operation': 'json_decode'}
            )
            self._send_safe_error(400, e, correlation_id)
            
        except ValidationError as e:
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'client_ip': client_ip, 'operation': 'validation'}
            )
            self._send_safe_error(400, e, correlation_id)
            
        except ValueError as e:
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'client_ip': client_ip, 'operation': 'value_processing'}
            )
            self._send_safe_error(400, e, correlation_id)
            
        except Exception as e:
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'client_ip': client_ip, 'operation': 'request_processing'}
            )
            self._send_safe_error(500, e, correlation_id)
    
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
            "status": MagicStringConstants.HEALTHY_LITERAL,
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
    
    def _send_json_response(self, status_code: int, data: dict[str, Any]):
        """Send JSON response with security headers"""
        self.send_response(status_code)
        self.send_header(APIConstants.CONTENT_TYPE_HEADER, APIConstants.APPLICATION_JSON)
        
        # CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header(APIConstants.ACCESS_CONTROL_ALLOW_HEADERS, APIConstants.CORS_ALLOW_HEADERS_BASIC)
        
        # Security headers
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        
        # Rate limiting headers
        client_ip = self.client_address[0]
        remaining = self.rate_limiter.get_remaining(client_ip)
        self.send_header('X-RateLimit-Remaining', str(remaining))
        self.send_header('X-RateLimit-Limit', str(APIConstants.MAX_REQUESTS_PER_MINUTE))
        
        self.end_headers()
        
        response_json = json.dumps(data, indent=2)
        self.wfile.write(response_json.encode('utf-8'))
    
    def _validate_mcp_request(self, request_data: dict) -> None:
        """Comprehensive validation of MCP request parameters"""
        # Validate method
        method = request_data.get('method')
        self.input_validator.validate_method_name(method, self.allowed_methods)
        
        # Validate response type
        response_type = request_data.get('response_type', 'json')
        self.input_validator.validate_response_type(response_type, self.allowed_response_types)
        
        # Validate params based on method
        params = request_data.get('params', {})
        self.input_validator.validate_dict_parameter('params', params)
        
        # Method-specific validation
        if method == 'run_skill':
            skill_name = params.get('skill_name')
            self.input_validator.validate_skill_name(skill_name, self.allowed_skills)
            
            # Validate skill input
            skill_input = params.get('input', {})
            self.input_validator.validate_dict_parameter('input', skill_input)
            
        elif method == 'run_bridge':
            function_name = params.get('function_name')
            self.input_validator.validate_function_name(function_name, self.allowed_functions)
            
            # Validate bridge params
            bridge_params = params.get('params', {})
            self.input_validator.validate_dict_parameter('bridge_params', bridge_params)
            
        elif method == 'chat_query':
            query = params.get('query')
            self.input_validator.validate_string_parameter('query', query, required=True, max_length=10000)
            
            # Validate optional context
            context = params.get('context')
            self.input_validator.validate_dict_parameter('context', context)
        
        # Validate optional id field
        request_id = request_data.get('id')
        if request_id is not None:
            self.input_validator.validate_string_parameter('id', request_id, max_length=100)
    
    def _send_error(self, status_code: int, message: str):
        """Legacy error sending - use _send_safe_error for new code"""
        error_data = {
            MagicStringConstants.ERROR_LITERAL: {
                "code": status_code,
                "message": message
            }
        }
        self._send_error_response(status_code, error_data)
    
    def _send_safe_error(self, status_code: int, error: Exception, correlation_id: str):
        """Send safe error response that prevents information leakage"""
        # Get sanitized error response
        safe_response = sanitize_error_for_client(error, correlation_id)
        
        # Use the provided status code or the one from sanitizer
        final_status_code = safe_response.get('error', {}).get('code', status_code)
        
        self._send_error_response(final_status_code, safe_response)
    
    def _send_error_response(self, status_code: int, error_data: dict):
        """Send error response with proper headers and security measures"""
        # Add rate limiting headers
        self.send_response(status_code)
        self.send_header(APIConstants.CONTENT_TYPE_HEADER, APIConstants.APPLICATION_JSON)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header(APIConstants.ACCESS_CONTROL_ALLOW_HEADERS, APIConstants.CORS_ALLOW_HEADERS_BASIC)
        
        # Security headers
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('X-XSS-Protection', '1; mode=block')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        
        # Rate limiting headers
        client_ip = self.client_address[0]
        remaining = self.rate_limiter.get_remaining(client_ip)
        self.send_header('X-RateLimit-Remaining', str(remaining))
        self.send_header('X-RateLimit-Limit', str(APIConstants.MAX_REQUESTS_PER_MINUTE))
        
        self.end_headers()
        
        response_json = json.dumps(error_data, indent=2)
        self.wfile.write(response_json.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr"""
        # Use get_error_logger for request logging to avoid global dependency
        request_logger = get_error_logger('mcp_server')
        request_logger.info(f"{self.address_string()} - {format % args}")


class MCPServer:
    """Lightweight MCP server for Enaam with comprehensive security validation"""
    
    def __init__(self, host: str = MagicStringConstants.LOCALHOST, port: int = 8080, 
                 logger: Optional[logging.Logger] = None,
                 rate_limiter: Optional[RateLimiter] = None,
                 input_validator: Optional[InputValidator] = None,
                 security_validator: Optional[SecurityValidator] = None) -> None:
        self.host = host
        self.port = port
        self.logger = logger or create_mcp_logger()
        
        # Security components
        self.rate_limiter = rate_limiter or create_rate_limiter()
        self.input_validator = input_validator or create_input_validator()
        self.security_validator = security_validator or create_security_validator()
        
        # Core components
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
    
    def start(self) -> dict[str, Any]:
        """Start the MCP server"""
        if self.active:
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": "Server already running",
                "host": self.host,
                "port": self.port
            }
        
        try:
            # Create HTTP server with comprehensive validation
            def handler_factory(*args, **kwargs):
                return MCPRequestHandler(
                    self.handler, 
                    self.rate_limiter,
                    self.input_validator,
                    self.security_validator,
                    *args, **kwargs
                )
            
            self.server = HTTPServer((self.host, self.port), handler_factory)
            
            # Start server in separate thread
            self.server_thread = threading.Thread(
                target=self.server.serve_forever,
                daemon=True,
                name="MCPServerThread"
            )
            self.server_thread.start()
            self.active = True
            
            self.logger.info(f"MCP server started on {self.host}:{self.port}")
            
            return {
                "status": MagicStringConstants.SUCCESS_LITERAL,
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
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'operation': 'server_start', 'host': self.host, 'port': self.port}
            )
            
            # Return safe error response
            safe_response = sanitize_error_for_client(e, correlation_id)
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": safe_response.get('error', {}).get('message', 'Failed to start server'),
                "correlation_id": correlation_id
            }
    
    def stop(self) -> dict[str, Any]:
        """Stop the MCP server"""
        if not self.active:
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": "Server not running"
            }
        
        try:
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            
            if self.server_thread:
                self.server_thread.join(timeout=APIConstants.SERVER_STOP_TIMEOUT)
            
            self.active = False
            self.server = None
            self.server_thread = None
            
            self.logger.info("MCP server stopped")
            
            return {
                "status": MagicStringConstants.SUCCESS_LITERAL,
                "message": "MCP server stopped"
            }
            
        except Exception as e:
            error_logger = get_error_logger('mcp_server')
            correlation_id = log_error_safely(
                e, 
                error_logger, 
                context={'operation': 'server_stop'}
            )
            
            # Return safe error response
            safe_response = sanitize_error_for_client(e, correlation_id)
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": safe_response.get('error', {}).get('message', 'Error stopping server'),
                "correlation_id": correlation_id
            }
    
    def is_active(self) -> bool:
        """Check if server is active"""
        return self.active
    
    def get_status(self) -> dict[str, Any]:
        """Get server status"""
        return {
            "active": self.active,
            "host": self.host,
            "port": self.port,
            "thread_alive": self.server_thread.is_alive() if self.server_thread else False,
            "capabilities": self.list_capabilities()
        }
    
    def list_capabilities(self) -> list[str]:
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
def create_sample_requests() -> list[dict[str, Any]]:
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