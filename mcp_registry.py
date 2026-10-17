"""
MCP Registry - Manages MCP server connections and health monitoring

Provides handles to MCP services with health checking, TTL caching,
and graceful degradation when services are unavailable.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from enaam_mcp_client import EnaamMCPClient

logger = logging.getLogger(__name__)


class MCPUnavailable(Exception):
    """Raised when an MCP service is unavailable"""
    pass


class MCPHandle:
    """
    Handle for a single MCP service with health monitoring and graceful degradation.
    """
    
    def __init__(self, alias: str, config: Dict[str, Any]):
        self.alias = alias
        self.config = config
        self.base_url = config["base_url"]
        self.timeout = config.get("timeout_seconds", 30)
        self.health_path = config.get("health_path", "/health")
        
        # Create MCP client
        self._client = EnaamMCPClient(
            base_url=self.base_url,
            timeout=self.timeout
        )
        
        # Health check caching (60s TTL)
        self._health_cache = None
        self._health_cache_time = 0
        self._health_ttl = 60
        
    def available(self) -> bool:
        """
        Check if MCP service is available (with TTL caching).
        
        Returns:
            True if service is healthy, False otherwise
        """
        current_time = time.time()
        
        # Return cached result if still valid
        if (self._health_cache is not None and 
            current_time - self._health_cache_time < self._health_ttl):
            return self._health_cache
        
        # Perform health check
        try:
            health_result = self._client.health()
            is_healthy = health_result.get("status") == "healthy"
            
            # Cache the result
            self._health_cache = is_healthy
            self._health_cache_time = current_time
            
            if not is_healthy:
                logger.warning(f"MCP service '{self.alias}' reports unhealthy: {health_result}")
            
            return is_healthy
            
        except Exception as e:
            logger.warning(f"MCP service '{self.alias}' health check failed: {e}")
            
            # Cache negative result
            self._health_cache = False
            self._health_cache_time = current_time
            
            # Log to notification_log
            self._log_unavailable(str(e))
            
            return False

    def capabilities(self) -> Dict[str, Any]:
        """
        Get service capabilities.
        
        Returns:
            Capabilities dict
            
        Raises:
            MCPUnavailable: If service is down and caller wants to handle it
        """
        if not self.available():
            raise MCPUnavailable(f"MCP service '{self.alias}' is unavailable")
        
        try:
            return self._client.capabilities()
        except Exception as e:
            logger.error(f"Failed to get capabilities from '{self.alias}': {e}")
            self._log_unavailable(str(e))
            raise MCPUnavailable(f"MCP service '{self.alias}' failed: {e}") from e

    def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Make a request to the MCP service.
        
        Args:
            method: MCP method name
            params: Method parameters
            
        Returns:
            Response from the service
            
        Raises:
            MCPUnavailable: If service is down and caller wants to handle it
        """
        if not self.available():
            raise MCPUnavailable(f"MCP service '{self.alias}' is unavailable")
        
        try:
            return self._client.request(method, params)
        except Exception as e:
            logger.error(f"MCP request to '{self.alias}' failed: {e}")
            self._log_unavailable(str(e))
            raise MCPUnavailable(f"MCP service '{self.alias}' failed: {e}") from e

    def _log_unavailable(self, error_message: str) -> None:
        """Log MCP unavailability to notification_log"""
        try:
            import sqlite3
            from pathlib import Path
            
            db_path = Path("khursheed.db")
            conn = sqlite3.connect(db_path, timeout=30.0)
            
            log_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            
            conn.execute("""
                INSERT INTO notification_log (
                    log_id, notification_type, recipient, subject, content,
                    status, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id, "mcp_unavailable", self.alias, f"MCP {self.alias} unavailable",
                f"Service at {self.base_url} is unreachable",
                "failed", error_message, created_at
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as log_error:
            logger.error(f"Failed to log MCP unavailability: {log_error}")


class MCPRegistry:
    """
    Registry for MCP services with configuration loading and handle management.
    """
    
    def __init__(self):
        self._handles: Dict[str, MCPHandle] = {}
    
    @classmethod
    def load(cls, config_path: str = "config/mcp_servers.json") -> 'MCPRegistry':
        """
        Load MCP registry from configuration file.
        
        Args:
            config_path: Path to MCP servers configuration
            
        Returns:
            Configured MCPRegistry instance
        """
        registry = cls()
        
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.warning(f"MCP config file not found: {config_path}")
                return registry
            
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            servers = config.get("servers", {})
            for alias, server_config in servers.items():
                try:
                    handle = MCPHandle(alias, server_config)
                    registry._handles[alias] = handle
                    logger.info(f"Registered MCP service: {alias} -> {server_config['base_url']}")
                except Exception as e:
                    logger.error(f"Failed to create MCP handle for '{alias}': {e}")
                    continue
            
            logger.info(f"MCP registry loaded with {len(registry._handles)} services")
            
        except Exception as e:
            logger.error(f"Failed to load MCP configuration: {e}")
        
        return registry
    
    def get_handle(self, alias: str) -> MCPHandle:
        """
        Get MCP handle by alias.
        
        Args:
            alias: Service alias
            
        Returns:
            MCPHandle for the service
            
        Raises:
            KeyError: If alias not found
        """
        if alias not in self._handles:
            raise KeyError(f"MCP service '{alias}' not found in registry")
        
        return self._handles[alias]
    
    def list_aliases(self) -> list[str]:
        """Get list of registered MCP service aliases"""
        return list(self._handles.keys())
    
    def health_summary(self) -> Dict[str, bool]:
        """Get health status of all registered services"""
        return {alias: handle.available() for alias, handle in self._handles.items()}