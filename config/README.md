# Enaam Configuration Files

This directory contains environment-specific configuration files for the Enaam system.

## Configuration Files

- `dev.json` - Development environment configuration
- `test.json` - Testing environment configuration  
- `staging.json` - Staging environment configuration
- `prod.json` - Production environment configuration

## Configuration Structure

Each configuration file follows the same structure:

```json
{
  "agent": {
    "name": "string",
    "version": "string",
    "mode": "string"
  },
  "server": {
    "host": "string",
    "port": "integer"
  },
  "database": {
    "path": "string"
  },
  "logging": {
    "level": "string",
    "console": "boolean",
    "file": "string"
  },
  "email": {
    "enabled": "boolean"
  },
  "api": {
    "openai_key": "string",
    "tavily_key": "string"
  },
  "khursheed": {
    "enabled": "boolean",
    "preserve_cron": "boolean",
    "database_path": "string",
    "tasks_path": "string"
  },
  "mcp": {
    "enabled": "boolean",
    "server_port": "integer",
    "tools_enabled": ["string"]
  }
}
```

## Environment Variables

Sensitive configuration values (API keys, passwords) should be provided via environment variables:

- `ENAAM_ENVIRONMENT` - Environment name (dev/test/staging/prod)
- `ENAAM_SERVER_HOST` - Override server host
- `ENAAM_SERVER_PORT` - Override server port
- `ENAAM_DATABASE_PATH` - Override database path
- `ENAAM_LOG_LEVEL` - Override logging level
- `GMAIL_EMAIL` - Gmail account for notifications
- `GMAIL_PASSWORD` - Gmail password/app password
- `SUMMARY_TO` - Email recipient for summaries
- `OPENAI_API_KEY` - OpenAI API key
- `TAVILY_API_KEY` - Tavily API key

## Configuration Loading Priority

Configuration is loaded in the following priority order (higher priority overrides lower):

1. Default configuration (hardcoded defaults)
2. Environment-specific configuration file (e.g., `dev.json`)
3. Environment variables

## Security

- Never commit sensitive data (API keys, passwords) to configuration files
- Use environment variables for all sensitive configuration
- Production configuration files should not contain default/example values
- API keys and passwords are validated for basic format and security

## Validation

All configuration values are validated at startup:

- Port numbers must be in valid range (1024-65535)
- Email addresses must be properly formatted
- API keys must meet minimum format requirements
- File paths are created if they don't exist
- Required values are checked for production environments

## Usage

```python
from enaam.core.config_loader import get_config

# Load configuration for current environment
config = get_config()

# Load specific environment
config = get_config("prod")

# Access configuration values
print(f"Server: {config.server.host}:{config.server.port}")
print(f"Database: {config.database.path}")
```