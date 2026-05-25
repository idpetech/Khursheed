"""
Service Factory - Create services with proper configuration injection

This module provides factory functions to create services with the correct
configuration and dependencies injected.
"""

from typing import Optional

from .config_loader import get_config, EnaamConfig
from .logging import EnaamLogger, create_logger
from .agent import EnaamAgent
from ..integrations.khursheed_bridge import KhursheedBridge
from ..mcp.handlers import MCPHandler


class ServiceFactory:
    """
    Factory for creating services with proper dependency injection.
    
    This factory ensures all services are created with the correct configuration
    and dependencies, eliminating the need for services to access configuration
    directly.
    """
    
    def __init__(self, config: Optional[EnaamConfig] = None):
        """
        Initialize service factory.
        
        Args:
            config: Configuration to use. If None, loads from global config.
        """
        self._config = config or get_config()
        self._logger_cache: Optional[EnaamLogger] = None
    
    @property
    def config(self) -> EnaamConfig:
        """Get the configuration instance"""
        return self._config
    
    def get_logger(self) -> EnaamLogger:
        """Get or create logger instance"""
        if self._logger_cache is None:
            self._logger_cache = create_logger()
        return self._logger_cache
    
    def create_agent(self, logger: Optional[EnaamLogger] = None) -> EnaamAgent:
        """
        Create agent instance with proper configuration.
        
        Args:
            logger: Logger instance. If None, uses factory logger.
            
        Returns:
            Configured agent instance
        """
        logger = logger or self.get_logger()
        return EnaamAgent(logger)
    
    def create_bridge(self, logger: Optional[EnaamLogger] = None) -> KhursheedBridge:
        """
        Create Khursheed bridge instance with proper configuration.
        
        Args:
            logger: Logger instance. If None, uses factory logger.
            
        Returns:
            Configured bridge instance
        """
        logger = logger or self.get_logger()
        return KhursheedBridge(logger, self._config.email)
    
    def create_mcp_handler(
        self,
        logger: Optional[EnaamLogger] = None,
        agent: Optional[EnaamAgent] = None,
        bridge: Optional[KhursheedBridge] = None
    ) -> MCPHandler:
        """
        Create MCP handler instance with proper configuration.
        
        Args:
            logger: Logger instance. If None, uses factory logger.
            agent: Agent instance. If None, creates new one.
            bridge: Bridge instance. If None, creates new one.
            
        Returns:
            Configured MCP handler instance
        """
        logger = logger or self.get_logger()
        agent = agent or self.create_agent(logger)
        bridge = bridge or self.create_bridge(logger)
        
        return MCPHandler(
            logger=logger,
            agent=agent,
            bridge=bridge,
            config=self._config
        )


# Global service factory instance
_service_factory: Optional[ServiceFactory] = None


def get_service_factory(config: Optional[EnaamConfig] = None, force_reload: bool = False) -> ServiceFactory:
    """
    Get the global service factory instance.
    
    Args:
        config: Configuration to use. If None, loads from global config.
        force_reload: Force creation of new factory instance.
        
    Returns:
        Service factory instance
    """
    global _service_factory
    
    if _service_factory is None or force_reload:
        _service_factory = ServiceFactory(config)
    
    return _service_factory


def reset_service_factory():
    """Reset cached service factory (useful for testing)"""
    global _service_factory
    _service_factory = None


# Convenience functions for common service creation
def create_mcp_handler(config: Optional[EnaamConfig] = None) -> MCPHandler:
    """Create MCP handler with default configuration"""
    factory = get_service_factory(config)
    return factory.create_mcp_handler()


def create_bridge(config: Optional[EnaamConfig] = None) -> KhursheedBridge:
    """Create Khursheed bridge with default configuration"""
    factory = get_service_factory(config)
    return factory.create_bridge()


def create_agent(config: Optional[EnaamConfig] = None) -> EnaamAgent:
    """Create agent with default configuration"""
    factory = get_service_factory(config)
    return factory.create_agent()