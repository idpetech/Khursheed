"""
Enaam Configuration

DEPRECATED: This module is kept for backward compatibility.
Use enaam.core.config_loader for new code.

Configuration settings for the Enaam system.
"""

import warnings
from typing import Any, Dict

from .core.config_loader import get_config, EnaamConfig as NewEnaamConfig


class EnaamConfig:
    """
    Legacy configuration management for Enaam.
    
    DEPRECATED: Use enaam.core.config_loader.get_config() instead.
    This class is maintained for backward compatibility only.
    """
    
    def __init__(self):
        warnings.warn(
            "EnaamConfig is deprecated. Use enaam.core.config_loader.get_config() instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # Load new configuration and convert to legacy format
        self._new_config = get_config()
        self.base_dir = None  # Will be set by accessing methods
        self.khursheed_dir = None  # Will be set by accessing methods
        self._config_cache = None
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get configuration in legacy dictionary format"""
        if self._config_cache is None:
            self._config_cache = self._convert_to_legacy_format(self._new_config)
        return self._config_cache
    
    def _convert_to_legacy_format(self, new_config: NewEnaamConfig) -> Dict[str, Any]:
        """Convert new configuration format to legacy dictionary format"""
        return {
            "agent": {
                "name": new_config.agent.name,
                "version": new_config.agent.version,
                "mode": new_config.agent.mode
            },
            "khursheed": {
                "enabled": new_config.khursheed.enabled,
                "preserve_cron": new_config.khursheed.preserve_cron,
                "database_path": new_config.khursheed.database_path,
                "tasks_path": new_config.khursheed.tasks_path
            },
            "mcp": {
                "enabled": new_config.mcp.enabled,
                "server_port": new_config.mcp.server_port,
                "tools_enabled": new_config.mcp.tools_enabled
            },
            "logging": {
                "level": new_config.logging.level.value,
                "file": new_config.logging.file or ""
            },
            "api": {
                "openai_key": new_config.api.openai_key,
                "tavily_key": new_config.api.tavily_key
            },
            "server": {
                "host": new_config.server.host,
                "port": new_config.server.port
            }
        }
    
    def load_config(self):
        """
        Load configuration from environment.
        
        DEPRECATED: Configuration is now loaded automatically.
        This method is kept for backward compatibility.
        """
        warnings.warn(
            "load_config() is deprecated. Configuration is loaded automatically.",
            DeprecationWarning,
            stacklevel=2
        )
        # Reload configuration
        self._new_config = get_config(force_reload=True)
        self._config_cache = None
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value by dot notation path"""
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
                
        return value
    
    def set(self, key_path: str, value: Any) -> None:
        """
        Set configuration value by dot notation path.
        
        DEPRECATED: Configuration is now immutable.
        This method is kept for backward compatibility but does nothing.
        """
        warnings.warn(
            "set() is deprecated. Configuration is now immutable for security.",
            DeprecationWarning,
            stacklevel=2
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self.config.copy()


# Legacy global configuration instance
# DEPRECATED: Use get_config() instead
config = EnaamConfig()