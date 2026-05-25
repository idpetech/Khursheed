#!/bin/bash

# Universal Port Allocation Deployment Script
# Deploys standardized port management to any project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Global port allocation mapping
get_project_port() {
    local project_name=$1
    case "$project_name" in
        "Khursheed") echo "8500" ;;
        "bus_ai_audit_v2") echo "8510" ;;
        "ctodashboard") echo "8520" ;;
        "InsightVault") echo "8530" ;;
        "future_project_1") echo "8540" ;;
        "future_project_2") echo "8550" ;;
        *) echo "8560" ;;  # Default fallback
    esac
}

# Function to detect project type
detect_project_type() {
    local project_dir=$1
    
    if [[ -f "$project_dir/streamlit_app.py" ]] || [[ -f "$project_dir/app.py" ]] && grep -q "streamlit" "$project_dir"/*.py 2>/dev/null; then
        echo "streamlit"
    elif [[ -f "$project_dir/app.py" ]] && grep -q "Flask" "$project_dir"/*.py 2>/dev/null; then
        echo "flask"
    elif [[ -f "$project_dir/main.py" ]] && grep -q "FastAPI" "$project_dir"/*.py 2>/dev/null; then
        echo "fastapi"
    else
        echo "unknown"
    fi
}

# Function to detect project name from directory
detect_project_name() {
    basename "$(pwd)"
}

# Function to get base port for project
get_base_port() {
    local project_name=$1
    get_project_port "$project_name"
}

# Function to generate PORT_CONFIG.json
generate_port_config() {
    local project_name=$1
    local project_type=$2
    local base_port=$3
    
    local main_port=$base_port
    local api_port=$((base_port + 1))
    local admin_port=$((base_port + 2))
    local dev_port=$((base_port + 5))
    local test_port=$((base_port + 8))
    
    # Determine main app command based on project type
    local main_command=""
    local main_file="app.py"
    
    case $project_type in
        "streamlit")
            main_command="streamlit run {file} --server.port {port} --server.address 0.0.0.0"
            ;;
        "flask")
            main_command="python {file}"
            main_file="app.py"
            ;;
        "fastapi") 
            main_command="uvicorn {file}:app --host 0.0.0.0 --port {port}"
            main_file="main"
            ;;
        *)
            main_command="python {file}"
            ;;
    esac
    
    # Find actual main file
    if [[ -f "app_production.py" ]]; then
        main_file="app_production.py"
    elif [[ -f "integrated_dashboard.py" ]]; then
        main_file="integrated_dashboard.py"  
    elif [[ -f "streamlit_app.py" ]]; then
        main_file="streamlit_app.py"
    elif [[ -f "main.py" ]]; then
        main_file="main.py"
    elif [[ -f "app.py" ]]; then
        main_file="app.py"
    fi
    
    cat > PORT_CONFIG.json << EOF
{
  "project_name": "$project_name",
  "port_range": [$base_port, $((base_port + 9))],
  "base_port": $base_port,
  "services": {
    "main_app": {
      "port": $main_port,
      "type": "$project_type",
      "file": "$main_file",
      "command": "$main_command",
      "description": "Main application interface",
      "required": true
    },
    "api_server": {
      "port": $api_port,
      "type": "flask",
      "file": "api.py",
      "command": "python {file}",
      "description": "API server",
      "required": false
    },
    "admin_ui": {
      "port": $admin_port,
      "type": "$project_type",
      "file": "admin.py",
      "command": "$main_command",
      "description": "Administrative interface", 
      "required": false
    }
  },
  "development_ports": [$dev_port, $((dev_port + 1)), $((dev_port + 2))],
  "testing_ports": [$test_port, $((test_port + 1))],
  "environment_overrides": {
    "development": {
      "main_app": $dev_port
    },
    "testing": {
      "main_app": $test_port
    }
  },
  "health_check_urls": {
    "main_app": "http://localhost:{port}",
    "api_server": "http://localhost:{port}/health"
  },
  "dependencies": {
    "startup_order": ["api_server", "main_app", "admin_ui"],
    "required_services": ["main_app"]
  }
}
EOF
}

# Function to update existing app files with new ports
update_app_ports() {
    local project_name=$1
    local base_port=$2
    local project_type=$3
    
    echo -e "${BLUE}📝 Updating application files with new ports...${NC}"
    
    # Update Python files based on project type
    case $project_type in
        "streamlit")
            # Add port and host configuration to main files
            for file in app.py app_production.py streamlit_app.py; do
                if [[ -f "$file" ]]; then
                    echo -e "  Updating $file..."
                    
                    # Check if port configuration already exists
                    if ! grep -q "server.port" "$file"; then
                        # Add port and host configuration at the end
                        cat >> "$file" << EOF

# Port allocation for $project_name - accessible on both localhost and 0.0.0.0
if __name__ == "__main__":
    import sys
    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "$base_port"])
    if "--server.address" not in sys.argv and "--server-address" not in sys.argv:
        sys.argv.extend(["--server.address", "0.0.0.0"])
    # Original main call preserved below
EOF
                    fi
                fi
            done
            ;;
        
        "flask")
            # Update Flask apps to use assigned port and bind to 0.0.0.0
            for file in app.py integrated_dashboard.py main.py; do
                if [[ -f "$file" ]]; then
                    echo -e "  Updating $file..."
                    
                    # Replace hardcoded ports and ensure 0.0.0.0 binding
                    sed -i.bak "s/port.*=.*[0-9][0-9][0-9][0-9]/port=$base_port/g" "$file"
                    sed -i.bak "s/app\.run.*host.*port.*[0-9][0-9][0-9][0-9]/app.run(host=\"0.0.0.0\", port=$base_port, debug=True)/g" "$file"
                    sed -i.bak "s/app\.run.*port.*[0-9][0-9][0-9][0-9]/app.run(host=\"0.0.0.0\", port=$base_port, debug=True)/g" "$file"
                    
                    # Ensure any app.run() without host gets 0.0.0.0
                    sed -i.bak "s/app\.run()/app.run(host=\"0.0.0.0\", port=$base_port, debug=True)/g" "$file"
                    sed -i.bak "s/app\.run(debug=True)/app.run(host=\"0.0.0.0\", port=$base_port, debug=True)/g" "$file"
                    
                    # Clean up backup files
                    rm -f "${file}.bak"
                fi
            done
            ;;
    esac
}

# Function to install management scripts
install_scripts() {
    echo -e "${BLUE}📦 Installing port management scripts...${NC}"
    
    # Create scripts directory
    mkdir -p scripts
    
    # Copy port manager
    cp /Users/haseebtoor/Projects/Khursheed/scripts/global_port_allocation_template/port_manager.py scripts/
    chmod +x scripts/port_manager.py
    
    # Generate project-specific start script
    cat > scripts/start_services.sh << 'EOF'
#!/bin/bash

# Project Service Startup Script
# Auto-generated by port allocation system

cd "$(dirname "$0")/.."
python scripts/port_manager.py start
EOF
    
    # Generate project-specific stop script
    cat > scripts/stop_services.sh << 'EOF'
#!/bin/bash

# Project Service Stop Script  
# Auto-generated by port allocation system

cd "$(dirname "$0")/.."
python scripts/port_manager.py stop
EOF
    
    # Generate project-specific status script
    cat > scripts/status_services.sh << 'EOF'
#!/bin/bash

# Project Service Status Script
# Auto-generated by port allocation system

cd "$(dirname "$0")/.."
python scripts/port_manager.py status
EOF
    
    chmod +x scripts/*.sh
}

# Function to create documentation
create_documentation() {
    local project_name=$1
    local base_port=$2
    
    cat > PORT_ALLOCATION.md << EOF
# Port Allocation for $project_name

This project uses standardized port allocation to prevent conflicts with other projects.

## 🎯 Assigned Ports

| Service | Port | Description |
|---------|------|-------------|
| Main App | $base_port | Primary application interface |
| API Server | $((base_port + 1)) | RESTful API endpoints |
| Admin Interface | $((base_port + 2)) | Administrative tools |
| Development | $((base_port + 5)) | Local development instance |
| Testing | $((base_port + 8)) | Automated testing |

## 🚀 Usage

### Quick Start
\`\`\`bash
# Start all services
./scripts/start_services.sh

# Check status
./scripts/status_services.sh

# Stop all services  
./scripts/stop_services.sh
\`\`\`

### Individual Service Management
\`\`\`bash
# Start specific service
python scripts/port_manager.py start main_app

# Stop specific service
python scripts/port_manager.py stop main_app

# Check for conflicts
python scripts/port_manager.py conflicts
\`\`\`

## 📱 Service URLs

- **Main Application**: http://localhost:$base_port
- **API Server**: http://localhost:$((base_port + 1))  
- **Admin Interface**: http://localhost:$((base_port + 2))

## 🔧 Configuration

Port configuration is defined in \`PORT_CONFIG.json\`. Modify this file to:
- Add new services
- Change port assignments
- Update startup order
- Configure health checks

## 🆘 Troubleshooting

### Port Conflicts
\`\`\`bash
# Check for conflicts
python scripts/port_manager.py conflicts

# Auto-resolve conflicts
python scripts/port_manager.py kill-conflicts
\`\`\`

### Service Issues
\`\`\`bash
# View service logs
tail -f logs/*.log

# Restart problematic service
python scripts/port_manager.py restart main_app
\`\`\`

Generated by Universal Port Allocation System 🚀
EOF
}

# Main deployment function
main() {
    echo -e "${BLUE}🚀 Deploying Port Allocation System${NC}"
    echo "================================"
    
    # Detect project info
    local project_name=$(detect_project_name)
    local project_type=$(detect_project_type ".")
    local base_port=$(get_base_port "$project_name")
    
    echo -e "${BLUE}📋 Project Information:${NC}"
    echo -e "  Name: $project_name"
    echo -e "  Type: $project_type"
    echo -e "  Base Port: $base_port"
    echo
    
    # Confirm deployment
    read -p "Deploy port allocation system? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Deployment cancelled${NC}"
        exit 0
    fi
    
    # Check for existing configuration
    if [[ -f "PORT_CONFIG.json" ]]; then
        echo -e "${YELLOW}⚠️  PORT_CONFIG.json already exists${NC}"
        read -p "Overwrite? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Keeping existing configuration${NC}"
        else
            generate_port_config "$project_name" "$project_type" "$base_port"
            echo -e "${GREEN}✅ PORT_CONFIG.json updated${NC}"
        fi
    else
        generate_port_config "$project_name" "$project_type" "$base_port"
        echo -e "${GREEN}✅ PORT_CONFIG.json created${NC}"
    fi
    
    # Update application files
    update_app_ports "$project_name" "$base_port" "$project_type"
    echo -e "${GREEN}✅ Application files updated${NC}"
    
    # Install management scripts
    install_scripts
    echo -e "${GREEN}✅ Management scripts installed${NC}"
    
    # Create documentation
    create_documentation "$project_name" "$base_port"
    echo -e "${GREEN}✅ Documentation created${NC}"
    
    # Create required directories
    mkdir -p logs pids
    echo -e "${GREEN}✅ Service directories created${NC}"
    
    echo
    echo -e "${GREEN}🎉 Port allocation system deployed successfully!${NC}"
    echo
    echo -e "${BLUE}📱 Your services will use these URLs:${NC}"
    echo -e "  Main App:  http://localhost:$base_port"
    echo -e "  API:       http://localhost:$((base_port + 1))"
    echo -e "  Admin:     http://localhost:$((base_port + 2))"
    echo
    echo -e "${BLUE}🔧 Management Commands:${NC}"
    echo -e "  Start:     ./scripts/start_services.sh"
    echo -e "  Stop:      ./scripts/stop_services.sh" 
    echo -e "  Status:    ./scripts/status_services.sh"
    echo -e "  Config:    vim PORT_CONFIG.json"
    echo
    echo -e "${BLUE}📖 Documentation:${NC}"
    echo -e "  Read:      cat PORT_ALLOCATION.md"
}

# Check if running from template directory
if [[ "$(basename "$PWD")" == "global_port_allocation_template" ]]; then
    echo -e "${RED}❌ Do not run from template directory${NC}"
    echo -e "Usage: cd /path/to/your/project && /path/to/deploy_port_allocation.sh"
    exit 1
fi

# Run main deployment
main "$@"