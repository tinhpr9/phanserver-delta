#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="/tmp/phanserver_delta_agent.pid"
LOG_FILE="/tmp/phanserver_delta_agent.log"

start() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Agent is already running (PID: $(cat "$PID_FILE"))"
        exit 0
    fi
    echo "Starting phanserver-delta device agent..."
    nohup python3 "$SCRIPT_DIR/agent/agent.py" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Agent started with PID $!"
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID="$(cat "$PID_FILE")"
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping agent (PID: $PID)..."
            kill "$PID"
            rm -f "$PID_FILE"
            echo "Agent stopped."
            exit 0
        fi
        rm -f "$PID_FILE"
    fi
    echo "Agent is not running."
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "Agent is running (PID: $(cat "$PID_FILE"))"
    else
        echo "Agent is stopped."
    fi
}

case "${1:-status}" in
    start) start ;;
    stop) stop ;;
    restart) stop; sleep 1; start ;;
    status) status ;;
    *) echo "Usage: $0 {start|stop|restart|status}" ;;
esac
