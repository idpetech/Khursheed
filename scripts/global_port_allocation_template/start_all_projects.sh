#!/bin/bash

# Master Project Startup Script
# Starts all projects with port allocation in correct order

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project paths
PROJECTS_ROOT="/Users/haseebtoor/Projects"
ENAAM_DIR="$PROJECTS_ROOT/Khursheed"
BA_DIR="$PROJECTS_ROOT/bus_ai_audit_v2"
CTO_DIR="$PROJECTS_ROOT/ctodashboard"
VAULT_DIR="$PROJECTS_ROOT/InsightVault"

# Function to start project services
start_project() {
    local project_name=$1
    local project_dir=$2
    
    echo -e "${BLUE}🚀 Starting $project_name...${NC}"
    
    if [[ ! -d "$project_dir" ]]; then
        echo -e "${RED}❌ Directory not found: $project_dir${NC}"
        return 1
    fi
    
    if [[ ! -f "$project_dir/PORT_CONFIG.json" ]]; then
        echo -e "${YELLOW}⚠️  Port allocation not deployed for $project_name${NC}"
        echo -e "${BLUE}💡 Run: cd $project_dir && /path/to/deploy_port_allocation.sh${NC}"
        return 1
    fi
    
    cd "$project_dir"
    
    if [[ -x "./scripts/start_services.sh" ]]; then
        ./scripts/start_services.sh
        echo -e "${GREEN}✅ $project_name services started${NC}"
    else
        echo -e "${YELLOW}⚠️  No start script found for $project_name${NC}"
    fi
    
    echo
}

# Function to check project status
check_project() {
    local project_name=$1
    local project_dir=$2
    
    if [[ ! -d "$project_dir" ]] || [[ ! -f "$project_dir/PORT_CONFIG.json" ]]; then
        return 1
    fi
    
    cd "$project_dir"
    python3 scripts/port_manager.py status 2>/dev/null | grep -q "RUNNING" && return 0 || return 1
}

# Function to deploy port allocation if needed
deploy_if_needed() {
    local project_name=$1
    local project_dir=$2
    
    if [[ ! -f "$project_dir/PORT_CONFIG.json" ]]; then
        echo -e "${YELLOW}📦 Deploying port allocation to $project_name...${NC}"
        cd "$project_dir"
        echo "y" | "/Users/haseebtoor/Projects/Khursheed/scripts/global_port_allocation_template/deploy_port_allocation.sh"
    fi
}

# Function to show global status
show_global_status() {
    echo -e "${BLUE}🌍 Global Project Status${NC}"
    echo "════════════════════════════════════════════"
    
    local projects=(
        "Enaam:$ENAAM_DIR"
        "Business Assistant:$BA_DIR"  
        "CTO Dashboard:$CTO_DIR"
        "InsightVault:$VAULT_DIR"
    )
    
    for project_info in "${projects[@]}"; do
        IFS=: read -r name dir <<< "$project_info"
        printf "%-20s " "$name"
        
        if check_project "$name" "$dir"; then
            echo -e "${GREEN}🟢 RUNNING${NC}"
        else
            echo -e "${RED}🔴 STOPPED${NC}"
        fi
    done
    
    echo
}

# Function to show service URLs
show_service_urls() {
    echo -e "${BLUE}📱 Service URLs${NC}"
    echo "════════════════════════════════════════════"
    echo -e "${GREEN}Local Access:${NC}"
    echo "  Enaam Main UI:      http://localhost:8501"
    echo "  Enaam Admin:        http://localhost:8502"  
    echo "  Enaam API:          http://localhost:8505"
    echo "  Business Assistant: http://localhost:8510"
    echo "  BA Production:      http://localhost:8511"
    echo "  CTO Dashboard:      http://localhost:8520"
    echo "  InsightVault:       http://localhost:8530"
    echo
    echo -e "${BLUE}Public Access (after Cloudflare tunnel):${NC}"
    echo "  Enaam Main UI:      https://enaam.techvizpro.workers.dev"
    echo "  Enaam Admin:        https://enaam-admin.techvizpro.workers.dev"
    echo "  Business Assistant: https://ba.techvizpro.workers.dev"
    echo "  CTO Dashboard:      https://cto.techvizpro.workers.dev"
    echo "  InsightVault:       https://vault.techvizpro.workers.dev"
    echo
}

# Main function
main() {
    case "${1:-start}" in
        "start")
            echo -e "${BLUE}🚀 Starting All Projects${NC}"
            echo "════════════════════════════════════════════"
            echo "$(date)"
            echo
            
            # Deploy port allocation if needed
            echo -e "${BLUE}📋 Checking port allocation deployment...${NC}"
            deploy_if_needed "Enaam" "$ENAAM_DIR"
            deploy_if_needed "Business Assistant" "$BA_DIR"
            deploy_if_needed "CTO Dashboard" "$CTO_DIR"
            deploy_if_needed "InsightVault" "$VAULT_DIR"
            echo
            
            # Start projects in dependency order
            start_project "Enaam" "$ENAAM_DIR"
            start_project "Business Assistant" "$BA_DIR"
            start_project "CTO Dashboard" "$CTO_DIR" 
            start_project "InsightVault" "$VAULT_DIR"
            
            # Show status
            show_global_status
            show_service_urls
            
            echo -e "${BLUE}💡 Next Steps:${NC}"
            echo "  1. Start Cloudflare tunnel: cloudflared tunnel run techvizpro-services"
            echo "  2. Check status: $0 status"
            echo "  3. Stop all: $0 stop"
            ;;
        
        "status")
            show_global_status
            show_service_urls
            ;;
        
        "stop")
            echo -e "${BLUE}🛑 Stopping All Projects${NC}"
            echo "════════════════════════════════════════════"
            
            local projects=("$VAULT_DIR" "$CTO_DIR" "$BA_DIR" "$ENAAM_DIR")
            
            for project_dir in "${projects[@]}"; do
                if [[ -f "$project_dir/scripts/stop_services.sh" ]]; then
                    echo -e "${YELLOW}Stopping $(basename "$project_dir")...${NC}"
                    cd "$project_dir"
                    ./scripts/stop_services.sh
                fi
            done
            
            echo -e "${GREEN}✅ All projects stopped${NC}"
            ;;
        
        "deploy")
            echo -e "${BLUE}📦 Deploying Port Allocation to All Projects${NC}"
            echo "════════════════════════════════════════════"
            
            # Force deploy to all projects
            local projects=(
                "Enaam:$ENAAM_DIR"
                "Business Assistant:$BA_DIR"
                "CTO Dashboard:$CTO_DIR"  
                "InsightVault:$VAULT_DIR"
            )
            
            for project_info in "${projects[@]}"; do
                IFS=: read -r name dir <<< "$project_info"
                echo -e "${BLUE}📦 Deploying to $name...${NC}"
                cd "$dir"
                echo "y" | "/Users/haseebtoor/Projects/Khursheed/scripts/global_port_allocation_template/deploy_port_allocation.sh"
                echo
            done
            
            echo -e "${GREEN}✅ Port allocation deployed to all projects${NC}"
            ;;
        
        "tunnel")
            echo -e "${BLUE}🌐 Cloudflare Tunnel Management${NC}"
            echo "════════════════════════════════════════════"
            
            case "${2:-start}" in
                "start")
                    if command -v cloudflared >/dev/null 2>&1; then
                        echo -e "${BLUE}🚀 Starting Cloudflare tunnel...${NC}"
                        nohup cloudflared tunnel --config ~/.cloudflared/config.yml run techvizpro-services > tunnel.log 2>&1 &
                        echo $! > tunnel.pid
                        echo -e "${GREEN}✅ Tunnel started (PID: $(cat tunnel.pid))${NC}"
                        echo "  Log: tail -f tunnel.log"
                    else
                        echo -e "${RED}❌ cloudflared not installed${NC}"
                        echo "  Install: brew install cloudflare/cloudflare/cloudflared"
                    fi
                    ;;
                "stop")
                    if [[ -f tunnel.pid ]]; then
                        kill "$(cat tunnel.pid)" 2>/dev/null || true
                        rm -f tunnel.pid
                        echo -e "${GREEN}✅ Tunnel stopped${NC}"
                    else
                        echo -e "${YELLOW}⚠️  No tunnel PID found${NC}"
                    fi
                    ;;
                "status")
                    if [[ -f tunnel.pid ]] && kill -0 "$(cat tunnel.pid)" 2>/dev/null; then
                        echo -e "${GREEN}🟢 Tunnel running (PID: $(cat tunnel.pid))${NC}"
                    else
                        echo -e "${RED}🔴 Tunnel stopped${NC}"
                    fi
                    ;;
                *)
                    echo "Usage: $0 tunnel {start|stop|status}"
                    ;;
            esac
            ;;
        
        "help"|"--help"|"-h")
            echo "Universal Project Management Script"
            echo "════════════════════════════════════════════"
            echo "Usage: $0 <command>"
            echo
            echo "Commands:"
            echo "  start    - Start all projects with port allocation"
            echo "  stop     - Stop all projects gracefully"
            echo "  status   - Show status of all projects"
            echo "  deploy   - Deploy port allocation to all projects"
            echo "  tunnel   - Manage Cloudflare tunnel (start|stop|status)"
            echo "  help     - Show this help message"
            echo
            echo "Examples:"
            echo "  $0 start                    # Start everything"
            echo "  $0 status                   # Check what's running"
            echo "  $0 tunnel start             # Start Cloudflare tunnel"
            echo "  $0 stop                     # Stop everything"
            ;;
        
        *)
            echo "Unknown command: $1"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Change to script directory
cd "$(dirname "$0")"

# Run main function
main "$@"