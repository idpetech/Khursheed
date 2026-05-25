#!/bin/bash
# Enaam MCP Server Deployment Script
# Production-ready deployment with health monitoring and management

set -e

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values
ENVIRONMENT="development"
ACTION="start"
DAEMON=false
CONFIG_FILE=""
HOST=""
PORT=""

# Color output functions
red() { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
blue() { echo -e "\033[34m$*\033[0m"; }

# Usage information
usage() {
    cat << EOF
🚀 Enaam MCP Server Deployment Script

Usage: $0 [OPTIONS] ACTION

ACTIONS:
    start       Start the MCP server
    stop        Stop the MCP server  
    restart     Restart the MCP server
    status      Show server status
    health      Show server health
    logs        Show server logs
    config      Show configuration

OPTIONS:
    -e, --env ENV          Environment: development|staging|production (default: development)
    -c, --config FILE      Custom configuration file path
    -h, --host HOST        Server host override
    -p, --port PORT        Server port override
    -d, --daemon           Run as daemon (background)
    --help                 Show this help

ENVIRONMENT VARIABLES:
    ENAAM_HOST             Server host (default: localhost)
    ENAAM_PORT             Server port (default: 8080)
    ENAAM_LOG_LEVEL        Logging level (default: INFO)
    ENAAM_ENV              Environment (default: development)

EXAMPLES:
    # Development server (foreground)
    $0 start

    # Production server (daemon)
    $0 --env production --daemon start

    # Custom configuration
    $0 --config custom.json --host 0.0.0.0 --port 9000 start

    # Check server status
    $0 --env production status

    # View server health
    $0 health

    # Restart staging server
    $0 --env staging restart

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -e|--env|--environment)
            ENVIRONMENT="$2"
            shift 2
            ;;
        -c|--config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        -h|--host)
            HOST="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -d|--daemon)
            DAEMON=true
            shift
            ;;
        --help)
            usage
            exit 0
            ;;
        start|stop|restart|status|health|logs|config)
            ACTION="$1"
            shift
            ;;
        *)
            red "❌ Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate environment
case $ENVIRONMENT in
    development|staging|production)
        ;;
    *)
        red "❌ Invalid environment: $ENVIRONMENT"
        echo "Valid environments: development, staging, production"
        exit 1
        ;;
esac

# Setup functions
setup_environment() {
    blue "🔧 Setting up environment: $ENVIRONMENT"
    
    # Activate virtual environment
    if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
        source "$PROJECT_ROOT/.venv/bin/activate"
        green "✅ Virtual environment activated"
    else
        red "❌ Virtual environment not found at $PROJECT_ROOT/.venv"
        echo "💡 Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
        exit 1
    fi
    
    # Change to project directory
    cd "$PROJECT_ROOT"
    
    # Create necessary directories
    mkdir -p data logs run config
    
    # Set environment variables
    export ENAAM_ENV="$ENVIRONMENT"
    
    # Override with command line arguments
    if [[ -n "$HOST" ]]; then
        export ENAAM_HOST="$HOST"
    fi
    if [[ -n "$PORT" ]]; then
        export ENAAM_PORT="$PORT"
    fi
}

# Check if server is running
is_server_running() {
    local pid_file="run/enaam_mcp.pid"
    if [[ -f "$pid_file" ]]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        else
            rm -f "$pid_file"
            return 1
        fi
    fi
    return 1
}

# Start server
start_server() {
    blue "🚀 Starting Enaam MCP server..."
    
    if is_server_running; then
        yellow "⚠️  Server is already running"
        show_status
        return 0
    fi
    
    # Build command arguments
    local cmd_args=("start" "--env" "$ENVIRONMENT")
    
    if [[ -n "$CONFIG_FILE" ]]; then
        cmd_args+=("--config" "$CONFIG_FILE")
    fi
    
    if [[ -n "$HOST" ]]; then
        cmd_args+=("--host" "$HOST")
    fi
    
    if [[ -n "$PORT" ]]; then
        cmd_args+=("--port" "$PORT")
    fi
    
    if [[ "$DAEMON" == "true" ]]; then
        cmd_args+=("--daemon")
    fi
    
    # Start the server using the new deployment manager
    if python -m enaam.deployment.server_manager "${cmd_args[@]}"; then
        green "✅ Server started successfully"
        
        if [[ "$DAEMON" != "true" ]]; then
            blue "💡 Server running in foreground. Press Ctrl+C to stop."
        fi
    else
        red "❌ Failed to start server"
        exit 1
    fi
}

# Stop server
stop_server() {
    blue "🛑 Stopping Enaam MCP server..."
    
    if ! is_server_running; then
        yellow "⚠️  Server is not running"
        return 0
    fi
    
    local pid_file="run/enaam_mcp.pid"
    local pid=$(cat "$pid_file")
    
    # Send graceful shutdown signal
    if kill -TERM "$pid" 2>/dev/null; then
        echo "📡 Graceful shutdown signal sent to process $pid"
        
        # Wait for graceful shutdown
        local count=0
        while kill -0 "$pid" 2>/dev/null && [[ $count -lt 30 ]]; do
            sleep 1
            ((count++))
        done
        
        if kill -0 "$pid" 2>/dev/null; then
            yellow "⚠️  Graceful shutdown timed out, forcing stop"
            kill -KILL "$pid" 2>/dev/null || true
        fi
        
        rm -f "$pid_file"
        green "✅ Server stopped"
    else
        red "❌ Failed to stop server (process not found)"
        rm -f "$pid_file"
    fi
}

# Restart server
restart_server() {
    blue "🔄 Restarting Enaam MCP server..."
    stop_server
    sleep 2
    start_server
}

# Show server status
show_status() {
    blue "📊 Enaam MCP Server Status"
    echo "Environment: $ENVIRONMENT"
    
    if is_server_running; then
        local pid_file="run/enaam_mcp.pid"
        local pid=$(cat "$pid_file")
        green "✅ Status: Running (PID: $pid)"
        
        # Show additional process information
        if command -v ps >/dev/null 2>&1; then
            echo
            echo "Process Information:"
            ps -p "$pid" -o pid,ppid,user,etime,pcpu,pmem,command 2>/dev/null || echo "Process details unavailable"
        fi
        
        # Try to get server status via API
        echo
        echo "API Status:"
        local config_file="config/$ENVIRONMENT.json"
        local host="localhost"
        local port="8080"
        
        if [[ -f "$config_file" ]]; then
            host=$(python -c "import json; print(json.load(open('$config_file'))['server']['host'])" 2>/dev/null || echo "localhost")
            port=$(python -c "import json; print(json.load(open('$config_file'))['server']['port'])" 2>/dev/null || echo "8080")
        fi
        
        if command -v curl >/dev/null 2>&1; then
            if curl -s "http://$host:$port/health" >/dev/null 2>&1; then
                green "✅ API: Responding"
            else
                red "❌ API: Not responding"
            fi
        fi
    else
        red "❌ Status: Not running"
    fi
}

# Show server health
show_health() {
    blue "🩺 Enaam MCP Server Health"
    
    if ! is_server_running; then
        red "❌ Server is not running"
        return 1
    fi
    
    # Get host and port from config
    local config_file="config/$ENVIRONMENT.json"
    local host="localhost"
    local port="8080"
    
    if [[ -f "$config_file" ]]; then
        host=$(python -c "import json; print(json.load(open('$config_file'))['server']['host'])" 2>/dev/null || echo "localhost")
        port=$(python -c "import json; print(json.load(open('$config_file'))['server']['port'])" 2>/dev/null || echo "8080")
    fi
    
    # Query health endpoint
    if command -v curl >/dev/null 2>&1; then
        echo "Querying health endpoint: http://$host:$port/health"
        echo
        
        if curl -s "http://$host:$port/health" | python -m json.tool 2>/dev/null; then
            green "✅ Health check successful"
        else
            red "❌ Health check failed or server not responding"
            return 1
        fi
    else
        yellow "⚠️  curl not available, cannot check API health"
    fi
}

# Show server logs
show_logs() {
    blue "📋 Enaam MCP Server Logs"
    
    local config_file="config/$ENVIRONMENT.json"
    local log_file=""
    
    if [[ -f "$config_file" ]]; then
        log_file=$(python -c "import json; print(json.load(open('$config_file'))['logging']['file'])" 2>/dev/null || echo "")
    fi
    
    if [[ -n "$log_file" && -f "$log_file" ]]; then
        echo "Log file: $log_file"
        echo
        tail -f "$log_file"
    else
        yellow "⚠️  No log file configured or file doesn't exist"
        echo "Logs are being written to stderr/stdout"
    fi
}

# Show configuration
show_config() {
    blue "⚙️  Enaam MCP Server Configuration"
    echo "Environment: $ENVIRONMENT"
    echo
    
    if python -m enaam.deployment.server_manager config --env "$ENVIRONMENT"; then
        green "✅ Configuration loaded successfully"
    else
        red "❌ Failed to load configuration"
        exit 1
    fi
}

# Main execution
main() {
    echo "🤖 Enaam MCP Server Deployment Manager"
    echo "========================================"
    
    setup_environment
    
    case $ACTION in
        start)
            start_server
            ;;
        stop)
            stop_server
            ;;
        restart)
            restart_server
            ;;
        status)
            show_status
            ;;
        health)
            show_health
            ;;
        logs)
            show_logs
            ;;
        config)
            show_config
            ;;
        *)
            red "❌ Unknown action: $ACTION"
            usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"