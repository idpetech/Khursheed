#!/bin/bash

# Enaam Services Stop Script
# Gracefully stops all Enaam services

set -e

PROJECT_DIR="/Users/haseebtoor/Projects/Khursheed"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🛑 Stopping Enaam services...${NC}"

# Function to stop service by PID file
stop_service() {
    local name=$1
    local pidfile="pids/${name}.pid"
    
    if [ -f "$pidfile" ]; then
        local pid=$(cat "$pidfile")
        if kill -0 $pid 2>/dev/null; then
            echo -e "${YELLOW}Stopping $name (PID: $pid)...${NC}"
            kill -TERM $pid 2>/dev/null || true
            
            # Wait up to 10 seconds for graceful shutdown
            local count=0
            while kill -0 $pid 2>/dev/null && [ $count -lt 10 ]; do
                sleep 1
                ((count++))
            done
            
            # Force kill if still running
            if kill -0 $pid 2>/dev/null; then
                echo -e "${YELLOW}Force stopping $name...${NC}"
                kill -KILL $pid 2>/dev/null || true
            fi
            
            echo -e "${GREEN}✅ $name stopped${NC}"
        else
            echo -e "${YELLOW}⚠️  $name was not running${NC}"
        fi
        rm -f "$pidfile"
    else
        echo -e "${YELLOW}⚠️  No PID file found for $name${NC}"
    fi
}

# Function to kill by port (fallback)
kill_port() {
    local port=$1
    local service_name=$2
    
    if lsof -i :$port >/dev/null 2>&1; then
        echo -e "${YELLOW}Killing $service_name on port $port...${NC}"
        lsof -ti:$port | xargs kill -TERM 2>/dev/null || true
        sleep 2
        lsof -ti:$port | xargs kill -KILL 2>/dev/null || true
        echo -e "${GREEN}✅ Port $port cleared${NC}"
    fi
}

# Stop services by PID files first
stop_service "admin_ui"
stop_service "main_ui" 
stop_service "skill_api"
stop_service "mcp_server"

# Fallback: kill by ports
echo -e "${BLUE}🔍 Checking for remaining processes...${NC}"
kill_port 8502 "admin_ui"
kill_port 8501 "main_ui"
kill_port 5001 "skill_api"
kill_port 8080 "mcp_server"
kill_port 8510 "legacy_app"

# Clean up
rm -rf pids/

echo -e "${GREEN}🎉 All Enaam services stopped!${NC}"

# Show any remaining python/streamlit processes
echo -e "${BLUE}📊 Remaining Python processes:${NC}"
ps aux | grep -E "(streamlit|enaam|python.*enaam)" | grep -v grep || echo "None found"