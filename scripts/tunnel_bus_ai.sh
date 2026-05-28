#!/bin/bash

# Bus AI Audit Cloudflare Tunnel Script
# Exposes Bus AI service (assuming port 8540 based on allocation)

PID_FILE="/tmp/tunnel_bus_ai.pid"
LOG_FILE="/tmp/tunnel_bus_ai.log"
URL_FILE="/tmp/tunnel_bus_ai_url.txt"

case "${1:-status}" in
    "start")
        if [[ -f "$PID_FILE" ]] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "🟡 Bus AI tunnel already running (PID: $(cat "$PID_FILE"))"
            if [[ -f "$URL_FILE" ]]; then
                echo "🌐 URL: $(cat "$URL_FILE")"
            fi
        else
            echo "🚀 Starting Bus AI tunnel on port 8540..."
            nohup cloudflared tunnel --url http://localhost:8540 > "$LOG_FILE" 2>&1 &
            echo $! > "$PID_FILE"
            
            echo "⏳ Waiting for tunnel to establish..."
            sleep 5
            
            if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
                TUNNEL_URL=$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | head -1)
                if [[ -n "$TUNNEL_URL" ]]; then
                    echo "$TUNNEL_URL" > "$URL_FILE"
                    echo "✅ Bus AI tunnel started!"
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
                echo "🛑 Stopping Bus AI tunnel..."
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
            echo "🟢 Bus AI tunnel RUNNING (PID: $(cat "$PID_FILE"))"
            if [[ -f "$URL_FILE" ]]; then
                echo "🌐 URL: $(cat "$URL_FILE")"
            fi
        else
            echo "🔴 Bus AI tunnel STOPPED"
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