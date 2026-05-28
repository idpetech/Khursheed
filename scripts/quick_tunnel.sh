#!/bin/bash

# Quick Cloudflare Tunnel Script
# Uses cloudflared's quick tunnel mode without domain requirements

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PID_FILE="/tmp/cloudflare_quick_tunnel.pid"
LOG_FILE="/tmp/cloudflare_quick_tunnel.log"
URL_FILE="/tmp/cloudflare_tunnel_url.txt"

case "${1:-status}" in
    "start")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo -e "${YELLOW}🟡 Tunnel already running (PID: $(cat "$PID_FILE"))${NC}"
            if [[ -f "$URL_FILE" ]]; then
                echo -e "${BLUE}🌐 Current URL: $(cat "$URL_FILE")${NC}"
            fi
        else
            echo -e "${BLUE}🚀 Starting Cloudflare quick tunnel...${NC}"
            
            # Start tunnel for main Enaam service on port 8501
            nohup cloudflared tunnel --url http://localhost:8501 > "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
            
            echo -e "${YELLOW}⏳ Waiting for tunnel to establish...${NC}"
            sleep 5
            
            if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
                # Extract the tunnel URL from logs
                TUNNEL_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | head -1)
                if [[ -n "$TUNNEL_URL" ]]; then
                    echo "$TUNNEL_URL" > "$URL_FILE"
                    echo -e "${GREEN}✅ Tunnel started successfully!${NC}"
                    echo -e "${BLUE}🌐 Your service is accessible at: $TUNNEL_URL${NC}"
                    echo -e "${BLUE}📝 Log: tail -f $LOG_FILE${NC}"
                else
                    echo -e "${YELLOW}⚠️  Tunnel started but URL not found yet. Check logs: tail -f $LOG_FILE${NC}"
                fi
            else
                echo -e "${RED}❌ Failed to start tunnel${NC}"
                rm -f "$PID_FILE"
                cat "$LOG_FILE"
            fi
        fi
        ;;
    
    "stop")
        if [[ -f "$PID_FILE" ]]; then
            PID=$(cat "$PID_FILE")
            if kill -0 "$PID" 2>/dev/null; then
                echo -e "${BLUE}🛑 Stopping tunnel (PID: $PID)...${NC}"
                kill "$PID"
                rm -f "$PID_FILE" "$URL_FILE"
                echo -e "${GREEN}✅ Tunnel stopped${NC}"
            else
                echo -e "${YELLOW}⚠️  Tunnel was not running${NC}"
                rm -f "$PID_FILE" "$URL_FILE"
            fi
        else
            echo -e "${YELLOW}⚠️  No tunnel PID file found${NC}"
        fi
        ;;
    
    "restart")
        "$0" stop
        sleep 2
        "$0" start
        ;;
    
    "status")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo -e "${GREEN}🟢 Tunnel is RUNNING (PID: $(cat "$PID_FILE"))${NC}"
            if [[ -f "$URL_FILE" ]]; then
                echo -e "${BLUE}🌐 Service URL: $(cat "$URL_FILE")${NC}"
            fi
        else
            echo -e "${RED}🔴 Tunnel is STOPPED${NC}"
            rm -f "$PID_FILE" "$URL_FILE"
        fi
        ;;
    
    "url")
        if [[ -f "$URL_FILE" ]]; then
            cat "$URL_FILE"
        else
            echo -e "${YELLOW}⚠️  No tunnel URL available. Is the tunnel running?${NC}"
        fi
        ;;
    
    "logs")
        if [[ -f "$LOG_FILE" ]]; then
            tail -f "$LOG_FILE"
        else
            echo -e "${YELLOW}⚠️  No log file found${NC}"
        fi
        ;;
    
    "test")
        if [[ -f "$URL_FILE" ]]; then
            URL=$(cat "$URL_FILE")
            echo -e "${BLUE}🧪 Testing tunnel connectivity to $URL...${NC}"
            if curl -s --max-time 10 "$URL" >/dev/null 2>&1; then
                echo -e "${GREEN}✅ Tunnel is working!${NC}"
            else
                echo -e "${RED}❌ Tunnel test failed${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  No tunnel URL available${NC}"
        fi
        ;;
    
    "help"|"--help"|"-h")
        echo -e "${BLUE}Cloudflare Quick Tunnel Management${NC}"
        echo "Usage: $0 {start|stop|restart|status|url|logs|test|help}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the quick tunnel"
        echo "  stop    - Stop the tunnel"
        echo "  restart - Restart the tunnel" 
        echo "  status  - Show tunnel status"
        echo "  url     - Show tunnel URL"
        echo "  logs    - Show tunnel logs"
        echo "  test    - Test tunnel connectivity"
        echo "  help    - Show this help"
        ;;
    
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac