"""
MCP Handlers - Orchestrates focused components for request processing

Uses composition to coordinate validation, routing, and formatting.
Single responsibility: Request orchestration only.
"""

from typing import Any, Optional

# Import Enaam components
from ..core.agent import EnaamAgent
from ..core.chat_context import ChatContextManager
from ..core.container import resolve_optional
from ..core.config_loader import get_config, EnaamConfig
from ..core.error_handler import get_error_logger
from ..core.exceptions import (
    MCPError, 
    ValidationError, 
    create_error_response,
    create_safe_error_response,
    log_error_safely,
    safe_handle_external_error
)
from ..core.logging import EnaamLogger
from ..integrations.khursheed_bridge import KhursheedBridge
from .schemas import MCPRequest, MCPResponse, create_mcp_response
from .request_validator import RequestValidator
from .response_formatter import ResponseFormatter
from .request_router import RequestRouter


class MCPHandler:
    """
    MCP request handler - orchestrates focused components.
    
    Uses composition to coordinate validation, routing, and formatting.
    Single responsibility: Request orchestration only.
    """
    
    def __init__(
        self, 
        logger: Optional[EnaamLogger] = None,
        agent: Optional[EnaamAgent] = None,
        bridge: Optional[KhursheedBridge] = None,
        config: Optional[EnaamConfig] = None,
        validator: Optional[RequestValidator] = None,
        formatter: Optional[ResponseFormatter] = None,
        router: Optional[RequestRouter] = None,
        context_manager: Optional[ChatContextManager] = None
    ) -> None:
        """
        Initialize MCPHandler with dependency injection and chat context.
        
        Args:
            logger: Logger instance. If None, resolves from container.
            agent: Agent instance. If None, creates with logger.
            bridge: Bridge instance. If None, creates with logger.
            config: Configuration instance. If None, loads from global config.
            validator: Request validator. If None, creates new instance.
            formatter: Response formatter. If None, creates new instance.
            router: Request router. If None, creates with agent and bridge.
            context_manager: Chat context manager. If None, creates new instance.
        """
        self._config = config or get_config()
        self._logger = logger or resolve_optional(EnaamLogger) or self._create_fallback_logger()
        self._error_logger = get_error_logger('mcp_handlers')
        self.agent = agent or EnaamAgent(self._logger)
        self.bridge = bridge or KhursheedBridge(self._logger, self._config.email)
        
        # Initialize chat context management
        self._context_manager = context_manager or ChatContextManager(logger=self._logger)
        
        # Initialize focused components with context awareness
        self._validator = validator or RequestValidator()
        self._formatter = formatter or ResponseFormatter()
        self._router = router or RequestRouter(self.agent, self.bridge, self._context_manager)
    
    def _create_fallback_logger(self) -> EnaamLogger:
        """Create fallback logger when container resolution fails."""
        from enaam.core.logging import create_logger
        return create_logger()
    
    def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Orchestrate request processing through focused components"""
        try:
            self._error_logger.debug("Handling MCP request: %s", request.method)
            
            # Step 1: Validate request using focused validator
            self._validator.validate_request(request)
            self._validator.validate_response_type(request.response_type)
            
            # Step 2: Route request to appropriate handler
            result = self._router.route_request(request)
            
            # Step 3: Format response using focused formatter
            formatted_result = self._formatter.format_response(result, request.response_type)
            
            return create_mcp_response(request.id, formatted_result)
            
        except (ValidationError, MCPError) as e:
            # Known errors - log safely and return sanitized error response
            correlation_id = log_error_safely(
                e, 
                self._error_logger, 
                context={
                    'method': getattr(request, 'method', 'unknown'),
                    'request_id': getattr(request, 'id', None),
                    'response_type': getattr(request, 'response_type', None)
                }
            )
            
            # Create safe error response
            correlation_id, safe_response = create_safe_error_response(
                e, 
                context={'operation': 'mcp_request_handling'}
            )
            
            return create_mcp_response(request.id, error=safe_response.get('error'))
            
        except Exception as e:
            # Unexpected errors - log safely with full context
            correlation_id = log_error_safely(
                e, 
                self._error_logger, 
                context={
                    'method': getattr(request, 'method', 'unknown'),
                    'request_id': getattr(request, 'id', None),
                    'operation': 'mcp_request_handling_unexpected'
                }
            )
            
            # Create safe error response for unexpected errors
            correlation_id, safe_response = create_safe_error_response(
                e, 
                context={'operation': 'mcp_unexpected_error'}
            )
            
            return create_mcp_response(request.id, error=safe_response.get('error'))
    
    # All handler methods removed - logic moved to RequestRouter
    # All formatting methods removed - logic moved to ResponseFormatter
    # Validation logic removed - moved to RequestValidator