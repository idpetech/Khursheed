#!/usr/bin/env python3
"""
Universal Port Management System
Standardized port allocation and service management across all projects
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

class PortManager:
    """Universal port manager for project services"""
    
    def __init__(self, config_file: str = "PORT_CONFIG.json"):
        self.config_file = Path(config_file)
        self.config = self._load_config()
        self.project_root = Path.cwd()
        self.logs_dir = self.project_root / "logs"
        self.pids_dir = self.project_root / "pids"
        
        # Create directories
        self.logs_dir.mkdir(exist_ok=True)
        self.pids_dir.mkdir(exist_ok=True)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load port configuration"""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Port config not found: {self.config_file}")
        
        with open(self.config_file) as f:
            config = json.load(f)
        
        # Validate configuration
        required_keys = ["project_name", "port_range", "services"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Missing required config key: {key}")
        
        return config
    
    def _colorize(self, text: str, color: str) -> str:
        """Add color to terminal output"""
        colors = {
            "red": "\033[0;31m",
            "green": "\033[0;32m", 
            "yellow": "\033[1;33m",
            "blue": "\033[0;34m",
            "nc": "\033[0m"  # No color
        }
        return f"{colors.get(color, '')}{text}{colors['nc']}"
    
    def check_port_available(self, port: int) -> bool:
        """Check if port is available"""
        try:
            result = subprocess.run(
                ["lsof", "-i", f":{port}"],
                capture_output=True,
                text=True
            )
            return result.returncode != 0  # Port is free if lsof finds nothing
        except Exception:
            return True
    
    def get_port_conflicts(self) -> List[Tuple[str, int]]:
        """Get list of services with port conflicts"""
        conflicts = []
        
        for service_name, service_config in self.config["services"].items():
            port = service_config["port"]
            if not self.check_port_available(port):
                conflicts.append((service_name, port))
        
        return conflicts
    
    def kill_port(self, port: int) -> bool:
        """Kill processes using specified port"""
        try:
            # Get PIDs using the port
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split("\n")
                
                # Try graceful shutdown first
                for pid in pids:
                    subprocess.run(["kill", "-TERM", pid], check=False)
                
                time.sleep(2)
                
                # Force kill if still running
                for pid in pids:
                    subprocess.run(["kill", "-KILL", pid], check=False)
                
                return True
        except Exception as e:
            print(f"Error killing port {port}: {e}")
        
        return False
    
    def resolve_conflicts(self, auto_kill: bool = False) -> bool:
        """Resolve port conflicts"""
        conflicts = self.get_port_conflicts()
        
        if not conflicts:
            return True
        
        print(f"{self._colorize('⚠️  Port conflicts detected:', 'yellow')}")
        for service_name, port in conflicts:
            print(f"  - {service_name}: port {port}")
        
        if auto_kill:
            print(f"{self._colorize('🔧 Auto-resolving conflicts...', 'yellow')}")
            for service_name, port in conflicts:
                if self.kill_port(port):
                    print(f"  ✅ Freed port {port} for {service_name}")
                else:
                    print(f"  ❌ Failed to free port {port} for {service_name}")
            return True
        else:
            response = input("Kill conflicting processes? (y/N): ")
            if response.lower() == 'y':
                for service_name, port in conflicts:
                    self.kill_port(port)
                return True
            else:
                print(f"{self._colorize('❌ Cannot start with port conflicts', 'red')}")
                return False
    
    def get_service_command(self, service_name: str) -> List[str]:
        """Get command to start a service"""
        service_config = self.config["services"][service_name]
        
        # Resolve command template
        command_template = service_config["command"]
        command = command_template.format(
            file=service_config["file"],
            port=service_config["port"]
        )
        
        return command.split()
    
    def start_service(self, service_name: str, background: bool = True) -> bool:
        """Start a service"""
        if service_name not in self.config["services"]:
            print(f"Unknown service: {service_name}")
            return False
        
        service_config = self.config["services"][service_name]
        port = service_config["port"]
        
        # Check if already running
        if not self.check_port_available(port):
            print(f"{self._colorize('⚠️', 'yellow')} {service_name} already running on port {port}")
            return True
        
        # Get command
        try:
            cmd = self.get_service_command(service_name)
        except Exception as e:
            print(f"Error building command for {service_name}: {e}")
            return False
        
        # Set up logging
        log_file = self.logs_dir / f"{service_name}.log"
        pid_file = self.pids_dir / f"{service_name}.pid"
        
        print(f"{self._colorize('🚀', 'blue')} Starting {service_name} on port {port}...")
        
        try:
            if background:
                # Start in background
                with open(log_file, 'w') as log:
                    process = subprocess.Popen(
                        cmd,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        preexec_fn=os.setsid  # Create new process group
                    )
                
                # Save PID
                with open(pid_file, 'w') as f:
                    f.write(str(process.pid))
                
                # Give service time to start
                time.sleep(3)
                
                # Check if still running
                if process.poll() is None and not self.check_port_available(port):
                    print(f"{self._colorize('✅', 'green')} {service_name} started (PID: {process.pid})")
                    return True
                else:
                    print(f"{self._colorize('❌', 'red')} {service_name} failed to start")
                    return False
            else:
                # Start in foreground
                subprocess.run(cmd, check=True)
                return True
                
        except Exception as e:
            print(f"Failed to start {service_name}: {e}")
            return False
    
    def stop_service(self, service_name: str) -> bool:
        """Stop a service"""
        pid_file = self.pids_dir / f"{service_name}.pid"
        
        if not pid_file.exists():
            # Try to kill by port
            service_config = self.config["services"].get(service_name)
            if service_config:
                port = service_config["port"]
                if not self.check_port_available(port):
                    print(f"{self._colorize('🛑', 'yellow')} Stopping {service_name} on port {port}...")
                    return self.kill_port(port)
                else:
                    print(f"{service_name} is not running")
                    return True
            return False
        
        # Read PID and stop process
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            
            print(f"{self._colorize('🛑', 'yellow')} Stopping {service_name} (PID: {pid})...")
            
            # Try graceful shutdown
            subprocess.run(["kill", "-TERM", str(pid)], check=False)
            
            # Wait for graceful shutdown
            for _ in range(10):
                try:
                    os.kill(pid, 0)  # Check if process exists
                    time.sleep(1)
                except OSError:
                    break  # Process is gone
            
            # Force kill if still running
            try:
                os.kill(pid, 0)
                subprocess.run(["kill", "-KILL", str(pid)], check=False)
            except OSError:
                pass  # Process already gone
            
            # Clean up PID file
            pid_file.unlink()
            
            print(f"{self._colorize('✅', 'green')} {service_name} stopped")
            return True
            
        except Exception as e:
            print(f"Error stopping {service_name}: {e}")
            pid_file.unlink(missing_ok=True)
            return False
    
    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get status of a service"""
        service_config = self.config["services"][service_name]
        port = service_config["port"]
        pid_file = self.pids_dir / f"{service_name}.pid"
        
        status = {
            "name": service_name,
            "port": port,
            "running": False,
            "pid": None,
            "health": "unknown"
        }
        
        # Check by PID file
        if pid_file.exists():
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
                
                # Check if process is actually running
                try:
                    os.kill(pid, 0)
                    status["running"] = True
                    status["pid"] = pid
                except OSError:
                    # Stale PID file
                    pid_file.unlink()
            except Exception:
                pass
        
        # Double-check by port
        if not status["running"] and not self.check_port_available(port):
            status["running"] = True
            status["health"] = "port_in_use"
        
        # Health check if configured
        if status["running"] and service_name in self.config.get("health_check_urls", {}):
            health_url = self.config["health_check_urls"][service_name].format(port=port)
            try:
                import urllib.request
                urllib.request.urlopen(health_url, timeout=5)
                status["health"] = "healthy"
            except Exception:
                status["health"] = "unhealthy"
        
        return status
    
    def status_all_services(self) -> None:
        """Show status of all services"""
        print(f"{self._colorize('📊 Service Status for', 'blue')} {self.config['project_name']}")
        print("=" * 50)
        
        for service_name in self.config["services"]:
            status = self.get_service_status(service_name)
            
            # Format status
            if status["running"]:
                status_text = self._colorize("RUNNING", "green")
                pid_text = f"(PID: {status['pid']})" if status['pid'] else ""
            else:
                status_text = self._colorize("STOPPED", "red")
                pid_text = ""
            
            health_text = ""
            if status["health"] == "healthy":
                health_text = self._colorize("[HEALTHY]", "green")
            elif status["health"] == "unhealthy":
                health_text = self._colorize("[UNHEALTHY]", "red")
            
            print(f"{service_name:15} {status_text} {pid_text} {health_text} - Port {status['port']}")
        
        # Show service URLs
        print(f"\n{self._colorize('📱 Service URLs:', 'blue')}")
        for service_name, service_config in self.config["services"].items():
            port = service_config["port"]
            print(f"  {service_name:15} http://localhost:{port}")
    
    def start_all_services(self, auto_resolve_conflicts: bool = False) -> bool:
        """Start all services in dependency order"""
        print(f"{self._colorize('🚀 Starting all services for', 'blue')} {self.config['project_name']}")
        
        # Resolve conflicts
        if not self.resolve_conflicts(auto_resolve_conflicts):
            return False
        
        # Get startup order
        startup_order = self.config.get("dependencies", {}).get("startup_order", 
                                                                 list(self.config["services"].keys()))
        
        # Start services in order
        success_count = 0
        for service_name in startup_order:
            if service_name in self.config["services"]:
                if self.start_service(service_name):
                    success_count += 1
        
        total_services = len([s for s in startup_order if s in self.config["services"]])
        
        if success_count == total_services:
            print(f"\n{self._colorize('🎉 All services started successfully!', 'green')}")
            self.status_all_services()
            return True
        else:
            print(f"\n{self._colorize(f'⚠️ {success_count}/{total_services} services started', 'yellow')}")
            return False
    
    def stop_all_services(self) -> None:
        """Stop all services"""
        print(f"{self._colorize('🛑 Stopping all services for', 'blue')} {self.config['project_name']}")
        
        # Stop in reverse order
        startup_order = self.config.get("dependencies", {}).get("startup_order", 
                                                                 list(self.config["services"].keys()))
        
        for service_name in reversed(startup_order):
            if service_name in self.config["services"]:
                self.stop_service(service_name)
        
        # Clean up directories
        try:
            if self.pids_dir.exists():
                for pid_file in self.pids_dir.glob("*.pid"):
                    pid_file.unlink()
        except Exception:
            pass
        
        print(f"{self._colorize('✅ All services stopped', 'green')}")


def main():
    """CLI interface for port manager"""
    if len(sys.argv) < 2:
        print("Usage: python port_manager.py <command> [options]")
        print("\nCommands:")
        print("  start [service_name]     - Start service(s)")
        print("  stop [service_name]      - Stop service(s)")  
        print("  restart [service_name]   - Restart service(s)")
        print("  status                   - Show service status")
        print("  conflicts                - Check for port conflicts")
        print("  kill-conflicts           - Kill conflicting processes")
        return
    
    command = sys.argv[1]
    
    try:
        manager = PortManager()
        
        if command == "start":
            if len(sys.argv) > 2:
                # Start specific service
                service_name = sys.argv[2]
                manager.start_service(service_name)
            else:
                # Start all services
                manager.start_all_services()
        
        elif command == "stop":
            if len(sys.argv) > 2:
                # Stop specific service
                service_name = sys.argv[2]
                manager.stop_service(service_name)
            else:
                # Stop all services
                manager.stop_all_services()
        
        elif command == "restart":
            if len(sys.argv) > 2:
                # Restart specific service
                service_name = sys.argv[2]
                manager.stop_service(service_name)
                time.sleep(2)
                manager.start_service(service_name)
            else:
                # Restart all services
                manager.stop_all_services()
                time.sleep(2)
                manager.start_all_services()
        
        elif command == "status":
            manager.status_all_services()
        
        elif command == "conflicts":
            conflicts = manager.get_port_conflicts()
            if conflicts:
                print("Port conflicts detected:")
                for service, port in conflicts:
                    print(f"  - {service}: port {port}")
            else:
                print("No port conflicts detected")
        
        elif command == "kill-conflicts":
            manager.resolve_conflicts(auto_kill=True)
        
        else:
            print(f"Unknown command: {command}")
    
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()