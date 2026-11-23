"""
MCP Registry - Manages MCP server connections and health monitoring

Provides handles to MCP services with health checking, TTL caching,
and graceful degradation when services are unavailable.
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from desk_settings import get_setting
from desk_settings import set_setting
from enaam_mcp_client import EnaamMCPClient
from runtime import PROJECT_ROOT
from runtime import resolve_db_path

logger = logging.getLogger(__name__)

MCP_SERVERS_KEY = "mcp_servers"
CHECK_TIMEOUT_SECONDS = 5
_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def config_file(config_path: str | Path | None = None) -> Path:
    if config_path is None:
        return PROJECT_ROOT / "config" / "mcp_servers.json"
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _normalize_server(row: dict) -> dict | None:
    alias = str(row.get("alias") or "").strip()
    base_url = str(row.get("base_url") or "").strip().rstrip("/")
    if not alias or not base_url:
        return None
    health_path = str(row.get("health_path") or "/health").strip() or "/health"
    try:
        timeout = int(row.get("timeout_seconds") or 30)
    except (TypeError, ValueError):
        timeout = 30
    timeout = max(1, min(timeout, 120))
    display_name = str(row.get("display_name") or alias).strip() or alias
    return {
        "alias": alias,
        "display_name": display_name,
        "base_url": base_url,
        "auth_env": str(row.get("auth_env") or "").strip(),
        "health_path": health_path,
        "timeout_seconds": timeout,
    }


def servers_from_file(config_path: str | Path | None = None) -> list[dict]:
    path = config_file(config_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("MCP config file could not be read")
        return []
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return []
    rows = []
    seen = set()
    for alias, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        row = _normalize_server({**raw, "alias": alias})
        if row is None or row["alias"] in seen:
            continue
        seen.add(row["alias"])
        rows.append(row)
    return rows


def save_mcp_servers(db_path: str | Path, rows: list[dict]) -> None:
    clean = []
    seen = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = _normalize_server(raw)
        if row is None or row["alias"] in seen:
            continue
        seen.add(row["alias"])
        clean.append(row)
    set_setting(db_path, MCP_SERVERS_KEY, json.dumps(clean))


def mcp_servers(db_path: str | Path, config_path: str | Path | None = None) -> list[dict]:
    """Saved connections. An empty setting is filled once from the JSON file."""
    path = config_file(config_path)
    raw = get_setting(db_path, MCP_SERVERS_KEY, "")
    if raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Saved MCP connections are not valid JSON. Using the config file.")
            return servers_from_file(path)
        if isinstance(parsed, list):
            rows = []
            seen = set()
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                row = _normalize_server(item)
                if row is None or row["alias"] in seen:
                    continue
                seen.add(row["alias"])
                rows.append(row)
            return rows
        logger.warning("Saved MCP connections are not a list. Using the config file.")
        return servers_from_file(path)
    seeded = servers_from_file(path)
    if seeded or path.exists():
        save_mcp_servers(db_path, seeded)
    return seeded


def add_mcp_server(db_path: str | Path, name: str, base_url: str, auth_env: str) -> dict:
    alias = (name or "").strip()
    if not alias:
        return {"status": "error", "message": "Enter a connection name."}
    if not _ALIAS.fullmatch(alias):
        return {
            "status": "error",
            "message": "Use a name like insight_vault. Letters, numbers, and underscores.",
        }
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return {"status": "error", "message": "Enter a base URL."}
    if len(url) > 300 or any(char.isspace() for char in url):
        return {"status": "error", "message": "That base URL is not usable."}
    if not url.startswith(("http://", "https://")):
        return {"status": "error", "message": "Base URL must start with http:// or https://."}
    parsed = urlparse(url)
    if parsed.username or parsed.password:
        return {"status": "error", "message": "Put the key in an env var, not in the URL."}
    env_name = (auth_env or "").strip()
    if env_name and not _ENV_NAME.fullmatch(env_name):
        return {
            "status": "error",
            "message": "The env var must be a name, such as INSIGHT_VAULT_API_KEY.",
        }
    rows = mcp_servers(db_path)
    updated = False
    for row in rows:
        if row["alias"] == alias:
            row["base_url"] = url
            row["auth_env"] = env_name
            row["display_name"] = alias
            updated = True
            break
    if not updated:
        rows.append(
            {
                "alias": alias,
                "display_name": alias,
                "base_url": url,
                "auth_env": env_name,
                "health_path": "/health",
                "timeout_seconds": 30,
            }
        )
    save_mcp_servers(db_path, rows)
    verb = "Updated" if updated else "Added"
    return {"status": "ok", "message": f"{verb} {alias}."}


def remove_mcp_server(db_path: str | Path, alias: str) -> dict:
    name = (alias or "").strip()
    rows = mcp_servers(db_path)
    kept = [row for row in rows if row["alias"] != name]
    if len(kept) == len(rows):
        return {"status": "error", "message": f"{name} is not a saved connection."}
    save_mcp_servers(db_path, kept)
    return {"status": "ok", "message": f"Removed {name}."}


def _shown_url(url: str) -> str:
    if "@" in url:
        return "that address"
    return url


def health_message(server: dict) -> str:
    """Plain words for one health check. The API key is not included."""
    name = str(server.get("display_name") or server.get("alias") or "connection")
    url = str(server.get("base_url") or "").strip()
    if not url:
        return f"{name} has no address."
    client = EnaamMCPClient(
        base_url=url,
        timeout=CHECK_TIMEOUT_SECONDS,
        auth_env=str(server.get("auth_env") or ""),
        health_path=str(server.get("health_path") or "/health"),
    )
    try:
        result = client.health()
    except requests.exceptions.SSLError:
        return f"{name} could not be reached because the certificate was not trusted."
    except requests.exceptions.Timeout:
        return f"{name} did not answer in time."
    except requests.exceptions.ConnectionError:
        return f"{name} could not be reached at {_shown_url(url)}."
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "error"
        return f"{name} returned HTTP {code}."
    except (requests.exceptions.JSONDecodeError, ValueError):
        return f"{name} answered, but the reply was not a health message."
    except requests.exceptions.RequestException:
        return f"{name} health check failed."
    if isinstance(result, dict) and result.get("status") == "healthy":
        return f"{name} is healthy."
    status = result.get("status") if isinstance(result, dict) else None
    if isinstance(status, str) and status and len(status) <= 40 and "\n" not in status:
        return f"{name} answered with status {status}."
    return f"{name} answered, but the status was not healthy."


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
        self.health_path = config.get("health_path", "/health") or "/health"
        self.auth_env = str(config.get("auth_env") or "")

        # Create MCP client. The env var is a name; the client reads the value per call.
        self._client = EnaamMCPClient(
            base_url=self.base_url,
            timeout=self.timeout,
            auth_env=self.auth_env,
            health_path=self.health_path,
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
                logger.warning("MCP service '%s' reports unhealthy", self.alias)
            
            return is_healthy
            
        except Exception as exc:
            logger.warning(
                "MCP service '%s' health check failed: %s",
                self.alias,
                type(exc).__name__,
            )
            
            # Cache negative result
            self._health_cache = False
            self._health_cache_time = current_time
            
            # Log to notification_log. Keep the message free of header values.
            self._log_unavailable(type(exc).__name__)
            
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
        except Exception as exc:
            logger.error(
                "Failed to get capabilities from '%s': %s",
                self.alias,
                type(exc).__name__,
            )
            self._log_unavailable(type(exc).__name__)
            raise MCPUnavailable(f"MCP service '{self.alias}' failed") from exc

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
        except Exception as exc:
            logger.error("MCP request to '%s' failed: %s", self.alias, type(exc).__name__)
            self._log_unavailable(type(exc).__name__)
            raise MCPUnavailable(f"MCP service '{self.alias}' failed") from exc

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
    def load(
        cls,
        config_path: str = "config/mcp_servers.json",
        db_path: str | Path | None = None,
    ) -> "MCPRegistry":
        """
        Load MCP connections from desk settings, or the JSON file when unset.

        Args:
            config_path: Path to MCP servers configuration
            db_path: Desk database. The default database is used when omitted.

        Returns:
            Configured MCPRegistry instance
        """
        registry = cls()
        resolved = resolve_db_path(db_path or "khursheed.db")
        try:
            rows = mcp_servers(resolved, config_path)
        except Exception as exc:
            logger.error("Failed to load MCP configuration: %s", exc)
            rows = servers_from_file(config_path)
        for row in rows:
            alias = row.get("alias")
            try:
                handle = MCPHandle(alias, row)
                registry._handles[alias] = handle
                logger.info("Registered MCP service: %s -> %s", alias, row.get("base_url"))
            except Exception as exc:
                logger.error("Failed to create MCP handle for '%s': %s", alias, exc)
                continue
        logger.info("MCP registry loaded with %s services", len(registry._handles))
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