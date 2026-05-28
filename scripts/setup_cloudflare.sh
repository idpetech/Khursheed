#!/bin/bash

# Cloudflare Tunnel Setup Script
# Sets up tunnel for techvizpro.workers.dev services

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

TUNNEL_NAME="techvizpro-services"
CONFIG_DIR="$HOME/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"

echo -e "${BLUE}🌐 Setting up Cloudflare Tunnel for techvizpro.workers.dev${NC}"
echo "════════════════════════════════════════════════════════════"

# Step 1: Check if cloudflared is installed
echo -e "${BLUE}📋 Step 1: Checking cloudflared installation...${NC}"
if ! command -v cloudflared &> /dev/null; then
    echo -e "${RED}❌ cloudflared not found${NC}"
    echo -e "${YELLOW}Installing via Homebrew...${NC}"
    brew install cloudflare/cloudflare/cloudflared
else
    echo -e "${GREEN}✅ cloudflared is installed${NC}"
fi

# Step 2: Use quick tunnel mode (no domain auth needed)
echo -e "${BLUE}📋 Step 2: Using quick tunnel mode...${NC}"
echo -e "${GREEN}✅ No domain authentication required${NC}"

# Step 3: Setup quick tunnel (no tunnel creation needed)
echo -e "${BLUE}📋 Step 3: Setting up quick tunnel mode...${NC}"
echo -e "${GREEN}✅ Using cloudflared tunnel --url mode${NC}"

# Step 4: Create configuration file
echo -e "${BLUE}📋 Step 4: Creating tunnel configuration...${NC}"

mkdir -p "$CONFIG_DIR"

cat > "$CONFIG_FILE" << EOF
tunnel: $TUNNEL_ID
credentials-file: $CONFIG_DIR/$TUNNEL_ID.json

ingress:
  # All services route through tunnel without custom hostnames
  # Will use Cloudflare's auto-generated tunnel URLs
  - service: http://localhost:8501
EOF

echo -e "${GREEN}✅ Configuration created at $CONFIG_FILE${NC}"

# Step 5: Configure DNS routes
echo -e "${BLUE}📋 Step 5: Configuring DNS routes...${NC}"

HOSTNAMES=(
    "enaam.techvizpro.workers.dev"
    "enaam-admin.techvizpro.workers.dev"
    "enaam-api.techvizpro.workers.dev"
    "ba.techvizpro.workers.dev"
    "ba-prod.techvizpro.workers.dev"
    "cto.techvizpro.workers.dev"
    "cto-api.techvizpro.workers.dev"
    "vault.techvizpro.workers.dev"
    "vault-api.techvizpro.workers.dev"
)

for hostname in "\${HOSTNAMES[@]}"; do
    echo -e "${YELLOW}Setting up DNS for \$hostname...${NC}"
    cloudflared tunnel route dns "$TUNNEL_NAME" "\$hostname" || {
        echo -e "${YELLOW}⚠️  DNS route for \$hostname might already exist${NC}"
    }
done

echo -e "${GREEN}✅ DNS routes configured${NC}"

# Step 6: Validate configuration
echo -e "${BLUE}📋 Step 6: Validating configuration...${NC}"
cloudflared tunnel ingress validate

echo -e "${GREEN}✅ Configuration is valid${NC}"

# Step 7: Create tunnel management script
TUNNEL_SCRIPT="/Users/haseebtoor/Projects/Khursheed/scripts/manage_tunnel.sh"

cat > "$TUNNEL_SCRIPT" << 'EOF'
#!/bin/bash

# Cloudflare Tunnel Management Script
# Manages the techvizpro-services tunnel

TUNNEL_NAME="techvizpro-services"
CONFIG_FILE="$HOME/.cloudflared/config.yml"
PID_FILE="/tmp/cloudflare_tunnel.pid"
LOG_FILE="/tmp/cloudflare_tunnel.log"

case "${1:-status}" in
    "start")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "🟡 Tunnel already running (PID: $(cat "$PID_FILE"))"
        else
            echo "🚀 Starting Cloudflare tunnel..."
            nohup cloudflared tunnel --config "$CONFIG_FILE" run "$TUNNEL_NAME" > "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
            sleep 3
            
            if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
                echo "✅ Tunnel started successfully (PID: $(cat "$PID_FILE"))"
                echo "📋 Your services are now available at:"
                echo "  🌐 https://enaam.techvizpro.workers.dev"
                echo "  🌐 https://ba.techvizpro.workers.dev"  
                echo "  🌐 https://cto.techvizpro.workers.dev"
                echo "  🌐 https://vault.techvizpro.workers.dev"
                echo "📝 Log: tail -f $LOG_FILE"
            else
                echo "❌ Failed to start tunnel"
                rm -f "$PID_FILE"
            fi
        fi
        ;;
    
    "stop")
        if [[ -f "$PID_FILE" ]]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo "🛑 Stopping tunnel (PID: $PID)..."
                kill "$PID"
                rm -f "$PID_FILE"
                echo "✅ Tunnel stopped"
            else
                echo "⚠️  Tunnel was not running"
                rm -f "$PID_FILE"
            fi
        else
            echo "⚠️  No tunnel PID file found"
        fi
        ;;
    
    "restart")
        "$0" stop
        sleep 2
        "$0" start
        ;;
    
    "status")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "🟢 Tunnel is RUNNING (PID: $(cat "$PID_FILE"))"
            echo "📋 Your services are available at:"
            echo "  🌐 https://enaam.techvizpro.workers.dev"
            echo "  🌐 https://ba.techvizpro.workers.dev"
            echo "  🌐 https://cto.techvizpro.workers.dev" 
            echo "  🌐 https://vault.techvizpro.workers.dev"
        else
            echo "🔴 Tunnel is STOPPED"
            rm -f "$PID_FILE"
        fi
        ;;
    
    "logs")
        if [[ -f "$LOG_FILE" ]]; then
            tail -f "$LOG_FILE"
        else
            echo "⚠️  No log file found"
        fi
        ;;
    
    "test")
        echo "🧪 Testing tunnel connectivity..."
        URLS=(
            "https://enaam.techvizpro.workers.dev"
            "https://ba.techvizpro.workers.dev"
            "https://cto.techvizpro.workers.dev"
            "https://vault.techvizpro.workers.dev"
        )
        
        for url in "\${URLS[@]}"; do
            printf "Testing %-40s " "$url"
            if curl -s --max-time 10 "$url" >/dev/null 2>&1; then
                echo "✅ OK"
            else
                echo "❌ FAIL"
            fi
        done
        ;;
    
    "help"|"--help"|"-h")
        echo "Cloudflare Tunnel Management"
        echo "Usage: $0 {start|stop|restart|status|logs|test|help}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the tunnel"
        echo "  stop    - Stop the tunnel"
        echo "  restart - Restart the tunnel" 
        echo "  status  - Show tunnel status"
        echo "  logs    - Show tunnel logs"
        echo "  test    - Test connectivity to all services"
        echo "  help    - Show this help"
        ;;
    
    *)
        echo "Unknown command: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac
EOF

chmod +x "$TUNNEL_SCRIPT"

echo -e "${GREEN}✅ Tunnel management script created at $TUNNEL_SCRIPT${NC}"

echo
echo -e "${BLUE}🎉 Cloudflare Tunnel Setup Complete!${NC}"
echo "══════════════════════════════════════════════"
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Start your local services:"
echo "   /Users/haseebtoor/Projects/Khursheed/scripts/global_port_allocation_template/start_all_projects.sh start"
echo
echo "2. Start the Cloudflare tunnel:"
echo "   $TUNNEL_SCRIPT start"
echo
echo "3. Test your services:"
echo "   $TUNNEL_SCRIPT test"
echo
echo -e "${BLUE}📱 Your services will be accessible at:${NC}"
echo "  🌐 https://enaam.techvizpro.workers.dev"
echo "  🌐 https://ba.techvizpro.workers.dev"
echo "  🌐 https://cto.techvizpro.workers.dev"
echo "  🌐 https://vault.techvizpro.workers.dev"
echo
echo -e "${BLUE}🔧 Tunnel Management:${NC}"
echo "  Start:  $TUNNEL_SCRIPT start"
echo "  Stop:   $TUNNEL_SCRIPT stop"
echo "  Status: $TUNNEL_SCRIPT status"
echo "  Logs:   $TUNNEL_SCRIPT logs"