"""
Enaam Configuration

Configuration settings for the Enaam system.
"""

import os
from pathlib import Path
from typing import Dict, Any


class EnaamConfig:
    """Configuration management for Enaam"""
    
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        self.khursheed_dir = self.base_dir
        self.load_config()
    
    def load_config(self):
        """Load configuration from environment"""
        self.config = {
            # Enaam specific settings
            "agent": {
                "name": "Enaam",
                "version": "1.0.0",
                "mode": "chief_of_staff"
            },
            
            # Khursheed integration settings
            "khursheed": {
                "enabled": True,
                "preserve_cron": True,
                "database_path": str(self.khursheed_dir / "khursheed.db"),
                "tasks_path": str(self.khursheed_dir / "tasks.json")
            },
            
            # MCP settings (placeholder)
            "mcp": {
                "enabled": False,
                "server_port": 8080,
                "tools_enabled": []
            },
            
            # Logging settings
            "logging": {
                "level": os.getenv("ENAAM_LOG_LEVEL", "INFO"),
                "file": str(self.base_dir / "logs" / "enaam.log")
            },
            
            # API settings
            "api": {
                "openai_key": os.getenv("OPENAI_API_KEY"),
                "tavily_key": os.getenv("TAVILY_API_KEY")
            }
        }
    
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
        """Set configuration value by dot notation path"""
        keys = key_path.split('.')
        config_ref = self.config
        
        for key in keys[:-1]:
            if key not in config_ref:
                config_ref[key] = {}
            config_ref = config_ref[key]
            
        config_ref[keys[-1]] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary"""
        return self.config.copy()


# Global configuration instance
config = EnaamConfig()