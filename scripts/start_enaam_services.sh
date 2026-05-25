#!/bin/bash

# Enaam Services Startup Script
# Starts all Enaam services with proper port allocation

set -e

PROJECT_DIR="/Users/haseebtoor/Projects/Khursheed"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to kill process on port
kill_port() {
    local port=$1
    echo -e "${YELLOW}Killing processes on port $port...${NC}"
    lsof -ti:$port | xargs kill -9 2>/dev/null || true
}

# Check for conflicts and offer to resolve
echo -e "${BLUE}🔍 Checking for port conflicts...${NC}"

PORTS=(8501 8502 5001 8080 8510)
CONFLICTS=()

for port in "${PORTS[@]}"; do
    if check_port $port; then
        CONFLICTS+=($port)
        echo -e "${RED}❌ Port $port is in use${NC}"
    else
        echo -e "${GREEN}✅ Port $port is available${NC}"
    fi
done

if [ ${#CONFLICTS[@]} -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Found conflicts on ports: ${CONFLICTS[*]}${NC}"
    read -p "Kill conflicting processes? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for port in "${CONFLICTS[@]}"; do
            kill_port $port
        done
        sleep 2
    else
        echo -e "${RED}Cannot start services with port conflicts. Exiting.${NC}"
        exit 1
    fi
fi

# Activate virtual environment
echo -e "${BLUE}🔄 Activating virtual environment...${NC}"
source .venv/bin/activate

# Function to start service in background
start_service() {
    local name=$1
    local command=$2
    local port=$3
    local logfile=$4
    
    echo -e "${BLUE}🚀 Starting $name on port $port...${NC}"
    
    # Start service in background and capture PID
    nohup $command > "$logfile" 2>&1 &
    local pid=$!
    
    # Give service time to start
    sleep 3
    
    # Check if service is still running
    if kill -0 $pid 2>/dev/null; then
        echo -e "${GREEN}✅ $name started successfully (PID: $pid)${NC}"
        echo "$pid" > "pids/${name}.pid"
        return 0
    else
        echo -e "${RED}❌ $name failed to start${NC}"
        echo "Check log: $logfile"
        return 1
    fi
}

# Create directories for logs and PIDs
mkdir -p logs pids

# Start services in order
echo -e "${BLUE}📋 Starting Enaam services...${NC}"

# 1. MCP Server (foundation service)
start_service "mcp_server" \
              "python -m enaam.mcp_server" \
              8080 \
              "logs/mcp_server.log"

# 2. Skill Management API
start_service "skill_api" \
              "python enaam_skill_api.py" \
              5001 \
              "logs/skill_api.log"

# 3. Main Command Center
start_service "main_ui" \
              "streamlit run enaam_ui.py --server.port 8501" \
              8501 \
              "logs/main_ui.log"

# 4. Admin Interface
start_service "admin_ui" \
              "streamlit run enaam_admin.py --server.port 8502" \
              8502 \
              "logs/admin_ui.log"

echo -e "${GREEN}🎉 All services started successfully!${NC}"
echo
echo -e "${BLUE}📱 Access URLs:${NC}"
echo -e "  Main Enaam UI:     ${GREEN}http://localhost:8501${NC}"
echo -e "  Skill Admin:       ${GREEN}http://localhost:8502${NC}"
echo -e "  API Health:        ${GREEN}http://localhost:5001/api/health${NC}"
echo -e "  MCP Server:        ${GREEN}http://localhost:8080${NC}"
echo
echo -e "${BLUE}📊 Service Management:${NC}"
echo -e "  View logs:         ${YELLOW}tail -f logs/*.log${NC}"
echo -e "  Stop services:     ${YELLOW}./scripts/stop_enaam_services.sh${NC}"
echo -e "  Check status:      ${YELLOW}./scripts/status_enaam_services.sh${NC}"