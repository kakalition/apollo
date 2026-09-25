#!/usr/bin/env bash
# Apollo — one-command local stack.
#
# Brings up everything Apollo needs: Chroma (memory server), then the dispatcher,
# worker and Telegram bot. Idempotent and self-healing: it reaps stale processes so
# you never end up with two bots fighting over getUpdates (409) or a double
# dispatcher.
#
# Usage:
#   scripts/run.sh              # start the whole stack (default)
#   scripts/run.sh start        # same
#   scripts/run.sh stop         # stop everything
#   scripts/run.sh restart      # stop, then start
#   scripts/run.sh status       # show process state
#   scripts/run.sh logs [name]  # tail a component log (chroma|dispatcher|worker|telegram)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/data/run"
mkdir -p "$RUN_DIR" "$ROOT/data/logs"

PY="$ROOT/.venv/bin/python"
CHROMA_BIN="$ROOT/.venv/bin/chroma"
CHROMA_PATH="$ROOT/data/chroma"
CHROMA_PORT="${CHROMA_PORT:-8000}"
CHROMA_HEALTH="http://localhost:${CHROMA_PORT}/api/v2/heartbeat"
COMPONENTS=(chroma dispatcher worker telegram)

info()  { printf '\033[1;36m[apollo]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[apollo]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[apollo]\033[0m %s\n' "$*" >&2; }

pattern_for() {
  case "$1" in
    chroma)     printf '%s run --path %s' "$CHROMA_BIN" "$CHROMA_PATH" ;;
    telegram|worker|dispatcher) printf '%s -m apollo.cli %s' "$PY" "$1" ;;
  esac
}

pid_of() { [[ -f "$RUN_DIR/$1.pid" ]] && cat "$RUN_DIR/$1.pid" 2>/dev/null || true; }
is_running() { local pid; pid="$(pid_of "$1")"; [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; }

# Any process matching a component's command line, regardless of pidfiles.
stray_pids() { pgrep -f "$(pattern_for "$1")" 2>/dev/null || true; }

reap_stale() {
  local name="$1" pids; pids="$(stray_pids "$name")"
  [[ -z "$pids" ]] && return 0
  if is_running "$name"; then return 0; fi
  warn "reaping stale $name process(es): $pids"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 1
  pids="$(stray_pids "$name")"
  # shellcheck disable=SC2086
  [[ -n "$pids" ]] && { kill -9 $pids 2>/dev/null || true; sleep 1; }
  return 0
}

# --- prerequisites ----------------------------------------------------------
ensure_venv() {
  if [[ ! -x "$PY" || ! -x "$CHROMA_BIN" ]]; then
    info "installing dependencies (uv sync --extra memory)"
    uv sync --extra memory
  fi
}

ensure_secrets() {
  if [[ ! -f "$ROOT/.env" ]]; then
    warn ".env not found — copying .env.example; fill in provider + Telegram keys"
    cp "$ROOT/.env.example" "$ROOT/.env"
    chmod 600 "$ROOT/.env" || true
  fi
  if ! grep -qE '^APOLLO_PROVIDER__API_KEY=.+' "$ROOT/.env" 2>/dev/null; then
    warn "APOLLO_PROVIDER__API_KEY is unset in .env — agents will not run"
  fi
  if ! grep -qE '^APOLLO_TELEGRAM__BOT_TOKEN=.+' "$ROOT/.env" 2>/dev/null; then
    warn "APOLLO_TELEGRAM__BOT_TOKEN is unset in .env — the Telegram component will exit"
  fi
}

ensure_db() {
  if [[ ! -f "$ROOT/data/apollo.db" ]]; then
    info "initialising database (migrations + seed)"
    "$PY" -m apollo.cli init-db
  fi
}

# --- process control --------------------------------------------------------
start_one() {
  local name="$1"; shift
  reap_stale "$name"
  if is_running "$name"; then
    info "$name already running (pid $(pid_of "$name"))"
    return 0
  fi
  rm -f "$RUN_DIR/$name.pid"
  : > "$RUN_DIR/$name.log"
  "$@" >>"$RUN_DIR/$name.log" 2>&1 &
  echo $! > "$RUN_DIR/$name.pid"
  sleep 1
  if ! is_running "$name"; then
    fail "$name failed to start; last log lines:"
    tail -n 15 "$RUN_DIR/$name.log" >&2 || true
    return 1
  fi
  info "$name started (pid $(pid_of "$name"))"
}

wait_for_http() {
  local url="$1" timeout="${2:-45}" elapsed=0
  while (( elapsed < timeout )); do
    if curl -sf -o /dev/null --max-time 3 "$url"; then return 0; fi
    sleep 1; elapsed=$((elapsed + 1))
  done
  return 1
}

start() {
  ensure_venv
  ensure_secrets
  ensure_db

  start_one chroma "$CHROMA_BIN" run --path "$CHROMA_PATH" --port "$CHROMA_PORT"
  if wait_for_http "$CHROMA_HEALTH" 45; then
    info "chroma healthy at $CHROMA_HEALTH"
  else
    warn "chroma health check did not pass; memory will degrade to in-memory"
  fi

  start_one dispatcher "$PY" -m apollo.cli dispatcher
  start_one worker     "$PY" -m apollo.cli worker
  if grep -qE '^APOLLO_TELEGRAM__BOT_TOKEN=.+' "$ROOT/.env" 2>/dev/null; then
    start_one telegram "$PY" -m apollo.cli telegram
  else
    warn "skipping telegram (no bot token)"
  fi

  echo
  status
  echo
  info "logs: $RUN_DIR/*.log   ·   stop with: scripts/run.sh stop"
}

stop_one() {
  local name="$1" pid; pid="$(pid_of "$name")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    info "stopping $name (pid $pid)"
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  # Belt and braces: catch a process that lost its pidfile.
  local pids; pids="$(stray_pids "$name")"
  # shellcheck disable=SC2086
  [[ -n "$pids" ]] && { info "reaping leftover $name (pids $pids)"; kill -9 $pids 2>/dev/null || true; }
  rm -f "$RUN_DIR/$name.pid"
}

stop() {
  for name in telegram worker dispatcher chroma; do stop_one "$name"; done
  info "stopped"
}

status() {
  for name in "${COMPONENTS[@]}"; do
    if is_running "$name"; then
      printf '  \033[1;32m●\033[0m %-11s running (pid %s)\n' "$name" "$(pid_of "$name")"
    else
      printf '  \033[1;31m○\033[0m %-11s stopped\n' "$name"
    fi
  done
}

logs() {
  local name="${1:-telegram}"
  local file="$RUN_DIR/$name.log"
  [[ -f "$file" ]] || { fail "no log for '$name' ($file)"; exit 1; }
  tail -n 50 -f "$file"
}

case "${1:-start}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
  logs)    logs "${2:-telegram}" ;;
  *) echo "usage: $0 [start|stop|restart|status|logs <component>]" >&2; exit 2 ;;
esac
