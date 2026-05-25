#!/bin/bash

# Enaam Services Status Script
# Shows status of all Enaam services

PROJECT_DIR="/Users/haseebtoor/Projects/Khursheed"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}📊 Enaam Services Status${NC}"
echo "================================"

# Function to check service status
check_service() {
    local name=$1
    local port=$2
    local pidfile="pids/${name}.pid"
    local url=$3
    
    printf "%-15s " "$name:"
    
    # Check by PID file
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        if kill -0 $pid 2>/dev/null; then
            printf "${GREEN}RUNNING${NC} (PID: $pid) "
        else
            printf "${RED}DEAD${NC} (stale PID) "
            rm -f "$pidfile"
        fi
    else
        # Check by port
        if lsof -i :$port >/dev/null 2>&1; then
            local port_pid=$(lsof -ti :$port)
            printf "${YELLOW}RUNNING${NC} (PID: $port_pid) "
        else
            printf "${RED}STOPPED${NC} "
        fi
    fi
    
    # Check HTTP endpoint if provided
    if [ ! -z "$url" ]; then
        if curl -s "$url" >/dev/null 2>&1; then
            printf "${GREEN}[HTTP OK]${NC}"
        else
            printf "${RED}[HTTP FAIL]${NC}"
        fi
    fi
    
    echo " - Port $port"
}

# Check each service
check_service "MCP Server" 8080 "http://localhost:8080"
check_service "Skill API" 5001 "http://localhost:5001/api/health"
check_service "Main UI" 8501 "http://localhost:8501"
check_service "Admin UI" 8502 "http://localhost:8502"
check_service "Legacy App" 8510 "http://localhost:8510"

echo
echo -e "${BLUE}📱 Service URLs:${NC}"
echo "  Main Enaam UI:     http://localhost:8501"
echo "  Skill Admin:       http://localhost:8502"
echo "  API Health:        http://localhost:5001/api/health"
echo "  MCP Server:        http://localhost:8080"
echo "  Legacy App:        http://localhost:8510"

echo
echo -e "${BLUE}📁 Logs:${NC}"
if [ -d "logs" ]; then
    ls -la logs/ 2>/dev/null || echo "No logs directory"
else
    echo "No logs directory"
fi

echo
echo -e "${BLUE}🔧 Management Commands:${NC}"
echo "  Start:    ./scripts/start_enaam_services.sh"
echo "  Stop:     ./scripts/stop_enaam_services.sh"
echo "  Logs:     tail -f logs/*.log"