#!/usr/bin/env bash
# Start the full Apollo stack locally: Chroma + dispatcher + worker + Telegram bot.
# Usage: scripts/run.sh [start|stop|status]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/data/run"
mkdir -p "$RUN_DIR"

APOLLO="${APOLLO:-uv run apollo}"
CHROMA_PATH="$ROOT/data/chroma"
CHROMA_PORT="${CHROMA_PORT:-8000}"

start_one() {
  local name="$1"; shift
  if [[ -f "$RUN_DIR/$name.pid" ]] && kill -0 "$(cat "$RUN_DIR/$name.pid")" 2>/dev/null; then
    echo "[apollo] $name already running (pid $(cat "$RUN_DIR/$name.pid"))"
    return 0
  fi
  echo "[apollo] starting $name"
  "$@" >"$RUN_DIR/$name.log" 2>&1 &
  echo $! >"$RUN_DIR/$name.pid"
}

start() {
  start_one chroma uv run chroma run --path "$CHROMA_PATH" --port "$CHROMA_PORT"
  # Give Chroma a moment to bind before dependent processes probe it.
  sleep 2
  start_one dispatcher $APOLLO dispatcher
  start_one worker $APOLLO worker
  start_one telegram $APOLLO telegram
  echo "[apollo] all processes started; logs in $RUN_DIR"
}

stop_one() {
  local name="$1"
  local pidfile="$RUN_DIR/$name.pid"
  if [[ -f "$pidfile" ]]; then
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "[apollo] stopping $name (pid $pid)"
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
}

stop() {
  for name in telegram worker dispatcher chroma; do stop_one "$name"; done
  echo "[apollo] stopped"
}

status() {
  for name in chroma dispatcher worker telegram; do
    local pidfile="$RUN_DIR/$name.pid"
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
      echo "  $name: running (pid $(cat "$pidfile"))"
    else
      echo "  $name: stopped"
    fi
  done
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  *) echo "usage: $0 [start|stop|restart|status]" >&2; exit 2 ;;
esac
