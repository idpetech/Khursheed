"""
MCP Server Deployment Manager

Production-ready server management with health monitoring, graceful shutdown,
and environment-specific configuration.
"""

import argparse
import atexit
import json
import os
import signal
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from ..core.constants import DefaultValues, MagicStringConstants
from ..core.error_handler import get_error_logger
from ..core.exceptions import create_safe_error_response, log_error_safely
from ..mcp.server import MCPServer


class ServerConfiguration:
    """Server configuration management for different environments."""
    
    def __init__(self, config_path: Optional[str] = None, environment: str = "development"):
        self.environment = environment
        self.config_path = config_path
        self.config = self._load_configuration()
        self._validate_configuration()
    
    def _load_configuration(self) -> Dict[str, Any]:
        """Load configuration from file or environment variables."""
        # Default configuration
        config = {
            "server": {
                "host": os.getenv("ENAAM_HOST", "localhost"),
                "port": int(os.getenv("ENAAM_PORT", "8080")),
                "workers": int(os.getenv("ENAAM_WORKERS", "1")),
                "max_connections": int(os.getenv("ENAAM_MAX_CONNECTIONS", "100")),
                "request_timeout": int(os.getenv("ENAAM_REQUEST_TIMEOUT", "30")),
                "keep_alive_timeout": int(os.getenv("ENAAM_KEEP_ALIVE", "5"))
            },
            "logging": {
                "level": os.getenv("ENAAM_LOG_LEVEL", "INFO"),
                "file": os.getenv("ENAAM_LOG_FILE", ""),
                "max_size": os.getenv("ENAAM_LOG_MAX_SIZE", "10MB"),
                "backup_count": int(os.getenv("ENAAM_LOG_BACKUP_COUNT", "5"))
            },
            "security": {
                "rate_limit": int(os.getenv("ENAAM_RATE_LIMIT", "60")),
                "rate_limit_window": int(os.getenv("ENAAM_RATE_WINDOW", "60")),
                "max_request_size": os.getenv("ENAAM_MAX_REQUEST_SIZE", "1MB"),
                "cors_origins": os.getenv("ENAAM_CORS_ORIGINS", "*").split(",")
            },
            "health": {
                "check_interval": int(os.getenv("ENAAM_HEALTH_INTERVAL", "30")),
                "restart_threshold": int(os.getenv("ENAAM_RESTART_THRESHOLD", "3")),
                "memory_threshold": os.getenv("ENAAM_MEMORY_THRESHOLD", "512MB"),
                "cpu_threshold": float(os.getenv("ENAAM_CPU_THRESHOLD", "80.0"))
            },
            "database": {
                "path": os.getenv("ENAAM_DB_PATH", "data/enaam_runs.db"),
                "backup_interval": int(os.getenv("ENAAM_DB_BACKUP_INTERVAL", "3600")),
                "max_backups": int(os.getenv("ENAAM_DB_MAX_BACKUPS", "24"))
            }
        }
        
        # Load from config file if specified
        if self.config_path and Path(self.config_path).exists():
            try:
                with open(self.config_path, 'r') as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except Exception as e:
                error_logger = get_error_logger('server_config')
                error_logger.error(f"Failed to load config file {self.config_path}: {e}")
        
        # Environment-specific overrides
        env_config_path = Path(f"config/{self.environment}.json")
        if env_config_path.exists():
            try:
                with open(env_config_path, 'r') as f:
                    env_config = json.load(f)
                    config.update(env_config)
            except Exception as e:
                error_logger = get_error_logger('server_config')
                error_logger.error(f"Failed to load environment config: {e}")
        
        return config
    
    def _validate_configuration(self) -> None:
        """Validate configuration values."""
        server_config = self.config["server"]
        
        # Validate port
        port = server_config["port"]
        if not (1 <= port <= 65535):
            raise ValueError(f"Invalid port number: {port}")
        
        # Validate host
        host = server_config["host"]
        if not host:
            raise ValueError("Host cannot be empty")
        
        # Create necessary directories
        if self.config["logging"]["file"]:
            log_dir = Path(self.config["logging"]["file"]).parent
            log_dir.mkdir(parents=True, exist_ok=True)
        
        db_path = Path(self.config["database"]["path"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """Get configuration value using dot notation."""
        keys = key_path.split('.')
        value = self.config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value


class HealthMonitor:
    """Health monitoring and automatic restart capability."""
    
    def __init__(self, config: ServerConfiguration, server_manager: 'ServerManager'):
        self.config = config
        self.server_manager = server_manager
        self.health_thread = None
        self.monitoring = False
        self.failure_count = 0
        self.last_health_check = None
        self.logger = get_error_logger('health_monitor')
    
    def start_monitoring(self) -> None:
        """Start health monitoring in background thread."""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.health_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="HealthMonitor"
        )
        self.health_thread.start()
        self.logger.info("Health monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop health monitoring."""
        self.monitoring = False
        if self.health_thread:
            self.health_thread.join(timeout=5)
        self.logger.info("Health monitoring stopped")
    
    def _monitor_loop(self) -> None:
        """Main health monitoring loop."""
        check_interval = self.config.get("health.check_interval", 30)
        
        while self.monitoring:
            try:
                health_status = self._perform_health_check()
                self.last_health_check = datetime.now(timezone.utc)
                
                if health_status["healthy"]:
                    self.failure_count = 0
                else:
                    self.failure_count += 1
                    self.logger.warning(f"Health check failed: {health_status['issues']}")
                    
                    restart_threshold = self.config.get("health.restart_threshold", 3)
                    if self.failure_count >= restart_threshold:
                        self.logger.error(f"Health check failed {self.failure_count} times, initiating restart")
                        self._initiate_restart()
                
                time.sleep(check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in health monitoring: {e}")
                time.sleep(check_interval)
    
    def _perform_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        issues = []
        
        try:
            # Check if server is responding
            if not self.server_manager.is_server_running():
                issues.append("Server is not running")
            
            # Check memory usage
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 / 1024  # MB
            memory_threshold = self._parse_size_string(self.config.get("health.memory_threshold", "512MB"))
            
            if memory_usage > memory_threshold:
                issues.append(f"High memory usage: {memory_usage:.1f}MB > {memory_threshold}MB")
            
            # Check CPU usage
            cpu_percent = process.cpu_percent(interval=1)
            cpu_threshold = self.config.get("health.cpu_threshold", 80.0)
            
            if cpu_percent > cpu_threshold:
                issues.append(f"High CPU usage: {cpu_percent:.1f}% > {cpu_threshold}%")
            
            # Check disk space
            disk_usage = psutil.disk_usage('/')
            if disk_usage.percent > 90:
                issues.append(f"Low disk space: {disk_usage.percent:.1f}% used")
            
            return {
                "healthy": len(issues) == 0,
                "issues": issues,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics": {
                    "memory_mb": memory_usage,
                    "cpu_percent": cpu_percent,
                    "disk_percent": disk_usage.percent
                }
            }
            
        except Exception as e:
            return {
                "healthy": False,
                "issues": [f"Health check error: {str(e)}"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    def _parse_size_string(self, size_str: str) -> float:
        """Parse size string like '512MB' to float in MB."""
        if isinstance(size_str, (int, float)):
            return float(size_str)
        
        size_str = str(size_str).upper()
        if size_str.endswith('MB'):
            return float(size_str[:-2])
        elif size_str.endswith('GB'):
            return float(size_str[:-2]) * 1024
        elif size_str.endswith('KB'):
            return float(size_str[:-2]) / 1024
        else:
            return float(size_str)
    
    def _initiate_restart(self) -> None:
        """Initiate server restart."""
        try:
            self.logger.info("Initiating server restart due to health check failures")
            self.server_manager.restart_server()
            self.failure_count = 0
        except Exception as e:
            self.logger.error(f"Failed to restart server: {e}")
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status."""
        return self._perform_health_check()


class ServerManager:
    """Production-ready MCP server manager with deployment capabilities."""
    
    def __init__(self, config: ServerConfiguration):
        self.config = config
        self.server: Optional[MCPServer] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.logger = get_error_logger('server_manager')
        self.shutdown_event = threading.Event()
        self.pid_file = None
        
        # Register signal handlers
        self._register_signal_handlers()
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
    
    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            self.logger.info(f"Received {signal_name}, initiating graceful shutdown")
            self.shutdown_server()
        
        # Register handlers for common termination signals
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGHUP'):
            signal.signal(signal.SIGHUP, signal_handler)
    
    def start_server(self, daemon: bool = False) -> Dict[str, Any]:
        """Start the MCP server with full deployment infrastructure."""
        try:
            self.logger.info(f"Starting Enaam MCP server in {self.config.environment} environment")
            
            # Create and configure MCP server
            host = self.config.get("server.host")
            port = self.config.get("server.port")
            
            self.server = MCPServer(host=host, port=port)
            
            # Start the server
            start_result = self.server.start()
            
            if start_result.get("status") != MagicStringConstants.SUCCESS_LITERAL:
                return start_result
            
            # Write PID file for process management
            self._write_pid_file()
            
            # Start health monitoring
            self.health_monitor = HealthMonitor(self.config, self)
            self.health_monitor.start_monitoring()
            
            self.logger.info(f"Server started successfully on {host}:{port}")
            
            if daemon:
                return {
                    "status": MagicStringConstants.SUCCESS_LITERAL,
                    "message": f"Server started in daemon mode on {host}:{port}",
                    "pid": os.getpid(),
                    "environment": self.config.environment
                }
            else:
                # Keep server running until shutdown signal
                self._run_server_loop()
                return {
                    "status": MagicStringConstants.SUCCESS_LITERAL,
                    "message": "Server shutdown completed"
                }
                
        except Exception as e:
            correlation_id = log_error_safely(
                e, self.logger, 
                context={'operation': 'server_start', 'environment': self.config.environment}
            )
            
            _, safe_response = create_safe_error_response(e, context={'operation': 'server_start'})
            
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": safe_response.get('error', {}).get('message', 'Failed to start server'),
                "correlation_id": correlation_id
            }
    
    def shutdown_server(self) -> Dict[str, Any]:
        """Gracefully shutdown the server."""
        try:
            self.logger.info("Initiating graceful server shutdown")
            self.shutdown_event.set()
            
            # Stop health monitoring
            if self.health_monitor:
                self.health_monitor.stop_monitoring()
            
            # Stop MCP server
            if self.server:
                stop_result = self.server.stop()
                self.server = None
            else:
                stop_result = {"status": MagicStringConstants.SUCCESS_LITERAL, "message": "Server was not running"}
            
            # Cleanup PID file
            self._cleanup_pid_file()
            
            self.logger.info("Server shutdown completed")
            return stop_result
            
        except Exception as e:
            self.logger.error(f"Error during server shutdown: {e}")
            return {
                "status": MagicStringConstants.ERROR_LITERAL,
                "message": f"Error during shutdown: {str(e)}"
            }
    
    def restart_server(self) -> Dict[str, Any]:
        """Restart the server."""
        self.logger.info("Restarting server")
        
        # Shutdown current server
        shutdown_result = self.shutdown_server()
        if shutdown_result.get("status") != MagicStringConstants.SUCCESS_LITERAL:
            return shutdown_result
        
        # Wait a moment for cleanup
        time.sleep(2)
        
        # Start new server
        return self.start_server()
    
    def is_server_running(self) -> bool:
        """Check if server is currently running."""
        return self.server is not None and self.server.is_active()
    
    def get_server_status(self) -> Dict[str, Any]:
        """Get comprehensive server status."""
        status = {
            "running": self.is_server_running(),
            "environment": self.config.environment,
            "pid": os.getpid(),
            "uptime": None,
            "health": None
        }
        
        if self.server:
            server_status = self.server.get_status()
            status.update(server_status)
        
        if self.health_monitor:
            status["health"] = self.health_monitor.get_health_status()
        
        return status
    
    def _write_pid_file(self) -> None:
        """Write process ID to file for process management."""
        try:
            pid_dir = Path("run")
            pid_dir.mkdir(exist_ok=True)
            self.pid_file = pid_dir / "enaam_mcp.pid"
            
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            
            self.logger.debug(f"PID file written: {self.pid_file}")
            
        except Exception as e:
            self.logger.warning(f"Failed to write PID file: {e}")
    
    def _cleanup_pid_file(self) -> None:
        """Remove PID file."""
        if self.pid_file and self.pid_file.exists():
            try:
                self.pid_file.unlink()
                self.logger.debug("PID file removed")
            except Exception as e:
                self.logger.warning(f"Failed to remove PID file: {e}")
    
    def _run_server_loop(self) -> None:
        """Main server loop that waits for shutdown signal."""
        try:
            while not self.shutdown_event.is_set() and self.is_server_running():
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt, shutting down")
    
    def cleanup(self) -> None:
        """Cleanup resources on exit."""
        if not self.shutdown_event.is_set():
            self.shutdown_server()


def create_argument_parser() -> argparse.ArgumentParser:
    """Create command line argument parser."""
    parser = argparse.ArgumentParser(
        description="Enaam MCP Server Deployment Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  ENAAM_HOST              Server host (default: localhost)
  ENAAM_PORT              Server port (default: 8080)
  ENAAM_LOG_LEVEL         Logging level (default: INFO)
  ENAAM_LOG_FILE          Log file path (default: stderr)
  ENAAM_RATE_LIMIT        Rate limit per minute (default: 60)
  ENAAM_MEMORY_THRESHOLD  Memory threshold for restart (default: 512MB)
  ENAAM_CPU_THRESHOLD     CPU threshold for restart (default: 80.0)

Examples:
  enaam-server start --host 0.0.0.0 --port 8080 --env production
  enaam-server start --daemon --config config/production.json
  enaam-server stop
  enaam-server restart
  enaam-server status
  enaam-server health
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start the MCP server')
    start_parser.add_argument('--host', default=None, help='Server host')
    start_parser.add_argument('--port', type=int, default=None, help='Server port')
    start_parser.add_argument('--config', help='Configuration file path')
    start_parser.add_argument('--env', '--environment', default='development', 
                             choices=['development', 'staging', 'production'],
                             help='Environment (default: development)')
    start_parser.add_argument('--daemon', action='store_true', 
                             help='Run as daemon (background process)')
    
    # Stop command
    stop_parser = subparsers.add_parser('stop', help='Stop the MCP server')
    stop_parser.add_argument('--force', action='store_true', 
                            help='Force stop even if graceful shutdown fails')
    
    # Restart command
    restart_parser = subparsers.add_parser('restart', help='Restart the MCP server')
    restart_parser.add_argument('--config', help='Configuration file path')
    restart_parser.add_argument('--env', '--environment', default='development',
                               choices=['development', 'staging', 'production'])
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show server status')
    status_parser.add_argument('--json', action='store_true', 
                              help='Output status in JSON format')
    
    # Health command  
    health_parser = subparsers.add_parser('health', help='Show server health')
    health_parser.add_argument('--json', action='store_true',
                              help='Output health in JSON format')
    
    # Config command
    config_parser = subparsers.add_parser('config', help='Show current configuration')
    config_parser.add_argument('--env', '--environment', default='development',
                               choices=['development', 'staging', 'production'])
    config_parser.add_argument('key', nargs='?', help='Specific config key to show')
    
    return parser


def main() -> int:
    """Main entry point for server deployment manager."""
    parser = create_argument_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        if args.command == 'start':
            # Load configuration
            config = ServerConfiguration(
                config_path=getattr(args, 'config', None),
                environment=getattr(args, 'env', 'development')
            )
            
            # Override with command line arguments
            if args.host:
                config.config["server"]["host"] = args.host
            if args.port:
                config.config["server"]["port"] = args.port
            
            # Start server
            manager = ServerManager(config)
            result = manager.start_server(daemon=getattr(args, 'daemon', False))
            
            if result.get("status") == MagicStringConstants.SUCCESS_LITERAL:
                print(f"✅ {result['message']}")
                return 0
            else:
                print(f"❌ {result['message']}")
                return 1
        
        elif args.command in ['stop', 'restart', 'status', 'health']:
            print(f"🚧 Command '{args.command}' not yet implemented")
            print("💡 Use the basic MCP server for now: python -m enaam.mcp_server start")
            return 1
        
        elif args.command == 'config':
            config = ServerConfiguration(
                environment=getattr(args, 'env', 'development')
            )
            
            if hasattr(args, 'key') and args.key:
                value = config.get(args.key)
                print(f"{args.key}: {value}")
            else:
                print(json.dumps(config.config, indent=2))
            return 0
        
        else:
            print(f"❌ Unknown command: {args.command}")
            return 1
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())