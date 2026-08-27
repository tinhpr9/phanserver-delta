#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="${PHANSERVER_DELTA_ROOT:-$HOME/.phanserver-delta/current}"
STATE_ROOT="${PHANSERVER_DELTA_STATE_ROOT:-$HOME/.phanserver-delta}"
PID_FILE="$STATE_ROOT/agent.pid"
LOG_FILE="$STATE_ROOT/agent.log"
PYTHON="${PYTHON:-$(command -v python3 || command -v python || true)}"
AGENT="$ROOT/agent/secure_agent.py"

mkdir -p "$STATE_ROOT"

is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null | grep -Fxq "$AGENT"
}

start() {
  [ -n "$PYTHON" ] || { echo "AGENT_SERVICE=FAIL missing_python"; exit 1; }
  [ -f "$AGENT" ] || { echo "AGENT_SERVICE=FAIL missing_agent"; exit 1; }
  if is_running; then
    echo "AGENT_SERVICE=RUNNING pid=$(cat "$PID_FILE")"
    return 0
  fi
  rm -f "$PID_FILE"
  nohup "$PYTHON" -u "$AGENT" >> "$LOG_FILE" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  sleep 1
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "AGENT_SERVICE=FAIL startup"
    return 1
  fi
  echo "AGENT_SERVICE=STARTED pid=$pid"
}

stop() {
  if ! is_running; then
    rm -f "$PID_FILE"
    echo "AGENT_SERVICE=STOPPED"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "AGENT_SERVICE=FAIL stop_timeout"
    return 1
  fi
  rm -f "$PID_FILE"
  echo "AGENT_SERVICE=STOPPED"
}

status() {
  if is_running; then
    echo "AGENT_SERVICE=RUNNING pid=$(cat "$PID_FILE")"
    return 0
  fi
  echo "AGENT_SERVICE=STOPPED"
  return 1
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop && start ;;
  status) status ;;
  *) echo "Usage: phanserver-agent {start|stop|restart|status}"; exit 2 ;;
esac
