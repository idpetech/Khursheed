#!/bin/bash

# InsightVault Cloudflare Tunnel Script
# Exposes InsightVault service on port 8530

PID_FILE="/tmp/tunnel_insightvault.pid"
LOG_FILE="/tmp/tunnel_insightvault.log"
URL_FILE="/tmp/tunnel_insightvault_url.txt"

case "${1:-status}" in
    "start")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "🟡 InsightVault tunnel already running (PID: $(cat "$PID_FILE"))"
            if [[ -f "$URL_FILE" ]]; then
                echo "🌐 URL: $(cat "$URL_FILE")"
            fi
        else
            echo "🚀 Starting InsightVault tunnel on port 8530..."
            nohup cloudflared tunnel --url http://localhost:8530 > "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
            
            echo "⏳ Waiting for tunnel to establish..."
            sleep 5
            
            if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
                TUNNEL_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | head -1)
                if [[ -n "$TUNNEL_URL" ]]; then
                    echo "$TUNNEL_URL" > "$URL_FILE"
                    echo "✅ InsightVault tunnel started!"
                    echo "🌐 URL: $TUNNEL_URL"
                fi
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
                echo "🛑 Stopping InsightVault tunnel..."
                kill "$PID"
                rm -f "$PID_FILE" "$URL_FILE"
                echo "✅ Tunnel stopped"
            else
                rm -f "$PID_FILE" "$URL_FILE"
                echo "⚠️  Tunnel was not running"
            fi
        fi
        ;;
    "status")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "🟢 InsightVault tunnel RUNNING (PID: $(cat "$PID_FILE"))"
            if [[ -f "$URL_FILE" ]]; then
                echo "🌐 URL: $(cat "$URL_FILE")"
            fi
        else
            echo "🔴 InsightVault tunnel STOPPED"
            rm -f "$PID_FILE" "$URL_FILE"
        fi
        ;;
    "url")
        if [[ -f "$URL_FILE" ]]; then
            cat "$URL_FILE"
        else
            echo "⚠️  No tunnel URL available"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|status|url}"
        ;;
esac