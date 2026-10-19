#!/bin/bash
# Private Cloudflare quick tunnel to the chief-of-staff desk on 127.0.0.1:8510.
# The desk still requires KHURSHEED_UI_PASSWORD. The URL is unlisted, not public auth.

set -euo pipefail

PID_FILE="/tmp/khursheed_desk_tunnel.pid"
LOG_FILE="/tmp/khursheed_desk_tunnel.log"
URL_FILE="/tmp/khursheed_desk_tunnel.url"

case "${1:-status}" in
    start)
        if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "Tunnel already running."
            [[ -f "$URL_FILE" ]] && cat "$URL_FILE"
            exit 0
        fi
        nohup cloudflared tunnel --url http://127.0.0.1:8510 >"$LOG_FILE" 2>&1 &
        echo $! >"$PID_FILE"
        sleep 4
        URL="$(grep -o 'https://.*\.trycloudflare\.com' "$LOG_FILE" | head -1 || true)"
        if [[ -n "$URL" ]]; then
            echo "$URL" >"$URL_FILE"
            echo "$URL"
        else
            echo "Tunnel started. URL not in the log yet. See $LOG_FILE"
        fi
        ;;
    stop)
        if [[ -f "$PID_FILE" ]]; then
            kill "$(cat "$PID_FILE")" 2>/dev/null || true
            rm -f "$PID_FILE" "$URL_FILE"
        fi
        ;;
    url)
        [[ -f "$URL_FILE" ]] && cat "$URL_FILE" || echo "No tunnel URL."
        ;;
    *)
        echo "Usage: $0 {start|stop|url}"
        exit 1
        ;;
esac
