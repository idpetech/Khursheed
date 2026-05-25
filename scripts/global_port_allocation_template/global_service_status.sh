#!/bin/bash

# Global Service Status Check
# Check status of all projects with port allocation

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Project directories (adjust paths as needed)
PROJECTS_ROOT="/Users/haseebtoor/Projects"

get_project_dir() {
    local project_name=$1
    case "$project_name" in
        "Enaam") echo "$PROJECTS_ROOT/Khursheed" ;;
        "Business Assistant") echo "$PROJECTS_ROOT/bus_ai_audit_v2" ;;
        "CTO Dashboard") echo "$PROJECTS_ROOT/ctodashboard" ;;
        "InsightVault") echo "$PROJECTS_ROOT/InsightVault" ;;
        *) echo "" ;;
    esac
}

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i :$port >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to check service health
check_service_health() {
    local port=$1
    local url="http://localhost:$port"
    
    if curl -s --max-time 5 "$url" >/dev/null 2>&1; then
        echo "HEALTHY"
    else
        echo "UNHEALTHY"
    fi
}

# Function to get project status
get_project_status() {
    local project_name=$1
    local project_dir=$2
    
    echo -e "${BLUE}📋 $project_name${NC}"
    echo "────────────────────────────────────────"
    
    if [[ ! -d "$project_dir" ]]; then
        echo -e "  ${RED}❌ Project directory not found: $project_dir${NC}"
        return
    fi
    
    # Check if port allocation is deployed
    if [[ ! -f "$project_dir/PORT_CONFIG.json" ]]; then
        echo -e "  ${YELLOW}⚠️  Port allocation not deployed${NC}"
        echo -e "  ${BLUE}💡 Run: cd $project_dir && ./deploy_port_allocation.sh${NC}"
        return
    fi
    
    # Parse PORT_CONFIG.json
    local services=$(python3 -c "
import json, sys
try:
    with open('$project_dir/PORT_CONFIG.json') as f:
        config = json.load(f)
    
    for name, service in config['services'].items():
        print(f\"{name}:{service['port']}:{service.get('description', 'Service')}\")
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
")
    
    if [[ $? -ne 0 ]]; then
        echo -e "  ${RED}❌ Failed to read PORT_CONFIG.json${NC}"
        return
    fi
    
    # Check each service
    local running_services=0
    local total_services=0
    
    while IFS=: read -r service_name port description; do
        if [[ -z "$service_name" ]]; then continue; fi
        
        total_services=$((total_services + 1))
        
        printf "  %-15s " "$service_name"
        
        if check_port $port; then
            printf "${GREEN}RUNNING${NC} "
            health=$(check_service_health $port)
            if [[ "$health" == "HEALTHY" ]]; then
                printf "${GREEN}[HEALTHY]${NC}"
            else
                printf "${YELLOW}[UNHEALTHY]${NC}"
            fi
            running_services=$((running_services + 1))
        else
            printf "${RED}STOPPED${NC} "
        fi
        
        printf " - Port $port - $description\n"
    done <<< "$services"
    
    # Summary
    if [[ $running_services -eq $total_services ]] && [[ $total_services -gt 0 ]]; then
        echo -e "  ${GREEN}✅ All services running ($running_services/$total_services)${NC}"
    elif [[ $running_services -gt 0 ]]; then
        echo -e "  ${YELLOW}⚠️  Partial services running ($running_services/$total_services)${NC}"
    else
        echo -e "  ${RED}❌ No services running ($running_services/$total_services)${NC}"
    fi
    
    echo
}

# Function to show global port allocation map
show_port_map() {
    echo -e "${BLUE}🗺️  Global Port Allocation Map${NC}"
    echo "═══════════════════════════════════════════════"
    echo "Port Range  | Project           | Status"
    echo "───────────────────────────────────────────────"
    
    local ranges=(
        "8500-8509:Enaam:$(get_project_dir "Enaam")"
        "8510-8519:Business Assistant:$(get_project_dir "Business Assistant")"
        "8520-8529:CTO Dashboard:$(get_project_dir "CTO Dashboard")"
        "8530-8539:InsightVault:$(get_project_dir "InsightVault")"
        "8540-8549:Future Project 1:N/A"
        "8550-8559:Future Project 2:N/A"
    )
    
    for range_info in "${ranges[@]}"; do
        IFS=: read -r port_range project_name project_dir <<< "$range_info"
        
        printf "%-12s| %-18s| " "$port_range" "$project_name"
        
        if [[ "$project_dir" == "N/A" ]]; then
            echo -e "${BLUE}RESERVED${NC}"
        elif [[ ! -d "$project_dir" ]]; then
            echo -e "${RED}NOT FOUND${NC}"
        elif [[ ! -f "$project_dir/PORT_CONFIG.json" ]]; then
            echo -e "${YELLOW}NOT DEPLOYED${NC}"
        else
            # Check if any services are running in this range
            local start_port=$(echo "$port_range" | cut -d'-' -f1)
            local end_port=$(echo "$port_range" | cut -d'-' -f2)
            local running=false
            
            for ((port=$start_port; port<=end_port; port++)); do
                if check_port $port; then
                    running=true
                    break
                fi
            done
            
            if $running; then
                echo -e "${GREEN}ACTIVE${NC}"
            else
                echo -e "${RED}INACTIVE${NC}"
            fi
        fi
    done
    echo
}

# Function to show quick access URLs
show_service_urls() {
    echo -e "${BLUE}📱 Quick Access URLs${NC}"
    echo "═══════════════════════════════════════════════"
    
    # Standard service URLs based on port allocation
    local urls=(
        "Enaam Main UI:8501:http://localhost:8501"
        "Enaam Admin:8502:http://localhost:8502"
        "Enaam API:8505:http://localhost:8505/api/health"
        "BA Main App:8510:http://localhost:8510"
        "BA Production:8511:http://localhost:8511"  
        "CTO Dashboard:8520:http://localhost:8520"
        "InsightVault:8530:http://localhost:8530"
    )
    
    for url_info in "${urls[@]}"; do
        IFS=: read -r service_name port url <<< "$url_info"
        
        printf "%-20s " "$service_name"
        
        if check_port $port; then
            echo -e "${GREEN}🟢${NC} $url"
        else
            echo -e "${RED}🔴${NC} $url (not running)"
        fi
    done
    echo
}

# Function to show management commands
show_management_commands() {
    echo -e "${BLUE}🔧 Management Commands${NC}"
    echo "═══════════════════════════════════════════════"
    
    local projects=("Enaam" "Business Assistant" "CTO Dashboard" "InsightVault")
    for project_name in "${projects[@]}"; do
        local project_dir=$(get_project_dir "$project_name")
        if [[ -n "$project_dir" ]]; then
            echo -e "${YELLOW}$project_name:${NC}"
            echo -e "  Start:  cd $project_dir && ./scripts/start_services.sh"
            echo -e "  Status: cd $project_dir && ./scripts/status_services.sh"
            echo -e "  Stop:   cd $project_dir && ./scripts/stop_services.sh"
            echo
        fi
    done
}

# Main function
main() {
    echo -e "${BLUE}🌍 Global Service Status Dashboard${NC}"
    echo "═══════════════════════════════════════════════"
    echo "$(date)"
    echo
    
    # Show port allocation map
    show_port_map
    
    # Show each project status
    local projects=("Enaam" "Business Assistant" "CTO Dashboard" "InsightVault")
    for project_name in "${projects[@]}"; do
        local project_dir=$(get_project_dir "$project_name")
        if [[ -n "$project_dir" ]]; then
            get_project_status "$project_name" "$project_dir"
        fi
    done
    
    # Show service URLs
    show_service_urls
    
    # Show management commands if requested
    if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
        show_management_commands
    fi
    
    echo -e "${BLUE}💡 Use --help to see management commands${NC}"
}

# Run main function
main "$@"