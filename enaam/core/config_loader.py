"""
Configuration Loader - Centralized and secure configuration management

This module provides comprehensive configuration loading with validation,
environment-specific support, and secure handling of sensitive data.
"""

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from .enums import EnvironmentKeys
from .exceptions import ConfigurationError


class Environment(str, Enum):
    """Supported environment types"""
    DEVELOPMENT = "dev"
    TESTING = "test"
    STAGING = "staging"
    PRODUCTION = "prod"


class LogLevel(str, Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class ServerConfig:
    """Server configuration with validation"""
    host: str = "localhost"
    port: int = 8080
    
    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("Server host must be a non-empty string")
        
        if not isinstance(self.port, int) or not 1024 <= self.port <= 65535:
            raise ValueError(f"Server port must be between 1024-65535, got: {self.port}")


@dataclass
class DatabaseConfig:
    """Database configuration with validation"""
    path: str
    
    def __post_init__(self):
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("Database path must be a non-empty string")
        
        # Create directory if it doesn't exist
        db_path = Path(self.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class LoggingConfig:
    """Logging configuration with validation"""
    level: LogLevel = LogLevel.INFO
    file: Optional[str] = None
    console: bool = True
    
    def __post_init__(self):
        if isinstance(self.level, str):
            try:
                self.level = LogLevel(self.level.upper())
            except ValueError:
                raise ValueError(f"Invalid log level: {self.level}. Must be one of: {[l.value for l in LogLevel]}")
        
        if self.file:
            log_path = Path(self.file)
            log_path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class EmailConfig:
    """Email configuration with validation"""
    sender: Optional[str] = None
    password: Optional[str] = None
    recipient: Optional[str] = None
    enabled: bool = False
    
    def __post_init__(self):
        if self.enabled:
            if not self.sender or not self.password or not self.recipient:
                raise ValueError("Email sender, password, and recipient are required when email is enabled")
            
            # Basic email validation
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, self.sender):
                raise ValueError(f"Invalid sender email format: {self.sender}")
            if not re.match(email_pattern, self.recipient):
                raise ValueError(f"Invalid recipient email format: {self.recipient}")


@dataclass
class APIConfig:
    """API configuration with validation"""
    openai_key: Optional[str] = None
    tavily_key: Optional[str] = None
    
    def __post_init__(self):
        # OpenAI key validation (basic format check)
        if self.openai_key and not (self.openai_key.startswith('sk-') and len(self.openai_key) > 20):
            raise ValueError("Invalid OpenAI API key format")
        
        # Tavily key validation (basic check)
        if self.tavily_key and len(self.tavily_key) < 10:
            raise ValueError("Invalid Tavily API key format")


@dataclass
class AgentConfig:
    """Agent configuration with validation"""
    name: str = "Enaam"
    version: str = "1.0.0"
    mode: str = "chief_of_staff"
    
    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Agent name must be a non-empty string")
        
        if not isinstance(self.version, str) or not re.match(r'^\d+\.\d+\.\d+$', self.version):
            raise ValueError("Agent version must be in format x.y.z")
        
        if self.mode not in ["chief_of_staff", "assistant", "standalone"]:
            raise ValueError(f"Invalid agent mode: {self.mode}")


@dataclass
class KhursheedConfig:
    """Khursheed integration configuration with validation"""
    enabled: bool = True
    preserve_cron: bool = True
    database_path: str = "khursheed.db"
    tasks_path: str = "tasks.json"
    
    def __post_init__(self):
        if not isinstance(self.database_path, str) or not self.database_path.strip():
            raise ValueError("Database path must be a non-empty string")
        
        if not isinstance(self.tasks_path, str) or not self.tasks_path.strip():
            raise ValueError("Tasks path must be a non-empty string")


@dataclass
class MCPConfig:
    """MCP configuration with validation"""
    enabled: bool = False
    server_port: int = 8080
    tools_enabled: list = field(default_factory=list)
    
    def __post_init__(self):
        if not isinstance(self.server_port, int) or not 1024 <= self.server_port <= 65535:
            raise ValueError(f"MCP server port must be between 1024-65535, got: {self.server_port}")
        
        if not isinstance(self.tools_enabled, list):
            raise ValueError("MCP tools_enabled must be a list")


@dataclass(frozen=True)
class EnaamConfig:
    """
    Immutable configuration container for Enaam system.
    
    This is the main configuration class that contains all subsystem configurations.
    Once created, it cannot be modified to prevent configuration drift.
    """
    environment: Environment
    agent: AgentConfig
    server: ServerConfig
    database: DatabaseConfig
    logging: LoggingConfig
    email: EmailConfig
    api: APIConfig
    khursheed: KhursheedConfig
    mcp: MCPConfig
    
    def __post_init__(self):
        """Validate configuration consistency"""
        # Ensure server and MCP don't use the same port
        if self.mcp.enabled and self.server.port == self.mcp.server_port:
            raise ValueError("Server and MCP cannot use the same port")
        
        # Validate environment-specific constraints
        if self.environment == Environment.PRODUCTION:
            if not self.api.openai_key:
                raise ValueError("OpenAI API key is required in production")
            if self.logging.level == LogLevel.DEBUG:
                raise ValueError("Debug logging not allowed in production")


class ConfigurationSecrets:
    """
    Secure handling of sensitive configuration data.
    
    This class provides methods to handle sensitive data like API keys and passwords
    with proper security considerations.
    """
    
    @staticmethod
    def get_secret(env_key: str, required: bool = False) -> Optional[str]:
        """Get a secret from environment with proper validation"""
        value = os.getenv(env_key)
        
        if required and not value:
            raise ConfigurationError(f"Required secret '{env_key}' not found in environment")
        
        # Basic security check - warn about potential issues
        if value:
            if len(value.strip()) < 5:
                raise ConfigurationError(f"Secret '{env_key}' appears to be too short")
            
            # Check for common mistakes
            if value.strip().lower() in ['password', 'secret', 'key', 'changeme', 'default']:
                raise ConfigurationError(f"Secret '{env_key}' appears to be a placeholder value")
        
        return value
    
    @staticmethod
    def mask_secret(secret: str, show_chars: int = 4) -> str:
        """Mask a secret for logging purposes"""
        if not secret or len(secret) <= show_chars:
            return "***"
        
        return secret[:show_chars] + "*" * (len(secret) - show_chars)


class ConfigLoader:
    """
    Configuration loader with environment support and validation.
    
    Loads configuration from multiple sources with proper validation and
    environment-specific handling.
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent.parent.parent
        self.config_dir = self.base_dir / "config"
        
    def load(self, environment: Optional[str] = None) -> EnaamConfig:
        """
        Load and validate configuration for the specified environment.
        
        Args:
            environment: Target environment (dev, test, staging, prod)
            
        Returns:
            Validated and immutable configuration object
            
        Raises:
            ConfigurationError: If configuration is invalid or missing
        """
        # Determine environment
        env_str = environment or os.getenv("ENAAM_ENVIRONMENT", Environment.DEVELOPMENT.value)
        try:
            env = Environment(env_str.lower())
        except ValueError:
            raise ConfigurationError(f"Invalid environment: {env_str}")
        
        # Load base configuration
        config_data = self._load_base_config()
        
        # Load environment-specific overrides
        env_config = self._load_environment_config(env)
        if env_config:
            config_data = self._merge_configs(config_data, env_config)
        
        # Load environment variables
        env_overrides = self._load_environment_variables()
        if env_overrides:
            config_data = self._merge_configs(config_data, env_overrides)
        
        # Create and validate configuration objects
        return self._create_config(env, config_data)
    
    def _load_base_config(self) -> Dict[str, Any]:
        """Load base configuration with sensible defaults"""
        return {
            "agent": {
                "name": "Enaam",
                "version": "1.0.0",
                "mode": "chief_of_staff"
            },
            "server": {
                "host": "localhost",
                "port": 8080
            },
            "database": {
                "path": str(self.base_dir / "khursheed.db")
            },
            "logging": {
                "level": "INFO",
                "file": str(self.base_dir / "logs" / "enaam.log"),
                "console": True
            },
            "email": {
                "enabled": False
            },
            "api": {},
            "khursheed": {
                "enabled": True,
                "preserve_cron": True,
                "database_path": str(self.base_dir / "khursheed.db"),
                "tasks_path": str(self.base_dir / "tasks.json")
            },
            "mcp": {
                "enabled": False,
                "server_port": 8080,
                "tools_enabled": []
            }
        }
    
    def _load_environment_config(self, env: Environment) -> Optional[Dict[str, Any]]:
        """Load environment-specific configuration file"""
        config_file = self.config_dir / f"{env.value}.json"
        
        if not config_file.exists():
            return None
        
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ConfigurationError(f"Failed to load environment config {config_file}: {e}")
    
    def _load_environment_variables(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        config = {}
        
        # Server configuration
        if os.getenv("ENAAM_SERVER_HOST"):
            config.setdefault("server", {})["host"] = os.getenv("ENAAM_SERVER_HOST")
        
        if os.getenv("ENAAM_SERVER_PORT"):
            try:
                config.setdefault("server", {})["port"] = int(os.getenv("ENAAM_SERVER_PORT"))
            except ValueError:
                raise ConfigurationError("ENAAM_SERVER_PORT must be an integer")
        
        # Database configuration
        if os.getenv("ENAAM_DATABASE_PATH"):
            config.setdefault("database", {})["path"] = os.getenv("ENAAM_DATABASE_PATH")
        
        # Logging configuration
        if os.getenv(EnvironmentKeys.ENAAM_LOG_LEVEL.value):
            config.setdefault("logging", {})["level"] = os.getenv(EnvironmentKeys.ENAAM_LOG_LEVEL.value)
        
        # Email configuration
        email_config = {}
        try:
            if ConfigurationSecrets.get_secret(EnvironmentKeys.GMAIL_EMAIL.value):
                email_config["sender"] = ConfigurationSecrets.get_secret(EnvironmentKeys.GMAIL_EMAIL.value)
        except ConfigurationError:
            # Skip invalid email configuration
            pass
            
        try:
            if ConfigurationSecrets.get_secret(EnvironmentKeys.GMAIL_PASSWORD.value):
                email_config["password"] = ConfigurationSecrets.get_secret(EnvironmentKeys.GMAIL_PASSWORD.value)
        except ConfigurationError:
            # Skip invalid password configuration
            pass
            
        try:
            if ConfigurationSecrets.get_secret(EnvironmentKeys.SUMMARY_TO.value):
                email_config["recipient"] = ConfigurationSecrets.get_secret(EnvironmentKeys.SUMMARY_TO.value)
        except ConfigurationError:
            # Skip invalid recipient configuration
            pass
        
        if email_config:
            email_config["enabled"] = bool(email_config.get("sender") and 
                                         email_config.get("password") and 
                                         email_config.get("recipient"))
            config["email"] = email_config
        
        # API configuration
        api_config = {}
        try:
            if ConfigurationSecrets.get_secret(EnvironmentKeys.OPENAI_API_KEY.value):
                api_config["openai_key"] = ConfigurationSecrets.get_secret(EnvironmentKeys.OPENAI_API_KEY.value)
        except ConfigurationError:
            # Skip invalid OpenAI key
            pass
            
        try:
            if ConfigurationSecrets.get_secret(EnvironmentKeys.TAVILY_API_KEY.value):
                api_config["tavily_key"] = ConfigurationSecrets.get_secret(EnvironmentKeys.TAVILY_API_KEY.value)
        except ConfigurationError:
            # Skip invalid Tavily key
            pass
        
        if api_config:
            config["api"] = api_config
        
        return config
    
    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge configuration dictionaries"""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _create_config(self, env: Environment, config_data: Dict[str, Any]) -> EnaamConfig:
        """Create validated configuration object"""
        try:
            # Create sub-configuration objects
            agent = AgentConfig(**config_data.get("agent", {}))
            server = ServerConfig(**config_data.get("server", {}))
            database = DatabaseConfig(**config_data.get("database", {}))
            logging = LoggingConfig(**config_data.get("logging", {}))
            email = EmailConfig(**config_data.get("email", {}))
            api = APIConfig(**config_data.get("api", {}))
            khursheed = KhursheedConfig(**config_data.get("khursheed", {}))
            mcp = MCPConfig(**config_data.get("mcp", {}))
            
            # Create main configuration object
            config = EnaamConfig(
                environment=env,
                agent=agent,
                server=server,
                database=database,
                logging=logging,
                email=email,
                api=api,
                khursheed=khursheed,
                mcp=mcp
            )
            
            return config
            
        except (TypeError, ValueError) as e:
            raise ConfigurationError(f"Configuration validation failed: {e}")


# Global configuration loader instance
_config_loader = ConfigLoader()
_cached_config: Optional[EnaamConfig] = None


def get_config(environment: Optional[str] = None, force_reload: bool = False) -> EnaamConfig:
    """
    Get the global configuration instance.
    
    Args:
        environment: Environment to load (uses ENAAM_ENVIRONMENT if not specified)
        force_reload: Force reloading configuration from sources
        
    Returns:
        Validated configuration instance
    """
    global _cached_config
    
    if _cached_config is None or force_reload:
        _cached_config = _config_loader.load(environment)
    
    return _cached_config


def reset_config():
    """Reset cached configuration (useful for testing)"""
    global _cached_config
    _cached_config = None