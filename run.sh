#!/usr/bin/env bash
# ============================================================
#  agents-trading — Bash Runner (Linux / macOS / WSL / Git Bash)
#  Usage: ./run.sh [command]
#
#  Commands:
#    all       Start infra + backend + frontend (default)
#    infra     Start postgres + redis only
#    backend   Start backend only
#    frontend  Start frontend only
#    stop      Stop all docker containers
#    logs      Tail backend logs
#    status    Show running services
# ============================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
COMMAND="${1:-all}"

# ── Colors ────────────────────────────────────────────────────────────────────
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
RESET='\033[0m'

header() {
  echo ""
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo -e "${CYAN}  $1${RESET}"
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
  echo ""
}

ok()   { echo -e "${GREEN}[OK]${RESET} $1"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $1"; }
err()  { echo -e "${RED}[ERROR]${RESET} $1"; exit 1; }

# ── Helpers ───────────────────────────────────────────────────────────────────

start_infra() {
  header "Starting Infrastructure (Postgres + Redis)"
  cd "$ROOT_DIR"
  docker compose up postgres redis -d || err "Docker failed. Is Docker running?"
  ok "Infra containers started"

  echo "Waiting for Postgres to be healthy..."
  for i in $(seq 1 15); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' \
      "$(docker compose ps -q postgres)" 2>/dev/null || echo "unknown")
    [ "$STATUS" = "healthy" ] && { ok "Postgres healthy"; return; }
    sleep 2
  done
  warn "Postgres may not be ready yet, proceeding anyway..."
}

start_backend() {
  header "Starting Backend (FastAPI :8000)"

  # Detect venv python
  if [ -f "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
  elif [ -f "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON="$BACKEND_DIR/.venv/Scripts/python.exe"
  else
    err "Python venv not found.\n  Run: cd backend && python -m venv .venv && pip install -r requirements.txt"
  fi

  cd "$BACKEND_DIR"
  nohup "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 --reload \
    > uvicorn_stdout.log 2> uvicorn_stderr.log &
  echo $! > /tmp/agents-backend.pid
  ok "Backend started (PID $!)"
  echo -e "     Logs:     ${GRAY}backend/uvicorn_stdout.log${RESET}"
  echo -e "     API Docs: ${CYAN}http://localhost:8000/docs${RESET}"
  sleep 3
}

start_frontend() {
  header "Starting Frontend (Next.js :3000)"
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    warn "node_modules not found, running npm install..."
    cd "$FRONTEND_DIR" && npm install
  fi
  cd "$FRONTEND_DIR"
  nohup npm run dev > /tmp/agents-frontend.log 2>&1 &
  echo $! > /tmp/agents-frontend.pid
  ok "Frontend started (PID $!)"
  echo -e "     App: ${CYAN}http://localhost:3000${RESET}"
}

stop_all() {
  header "Stopping all services"
  cd "$ROOT_DIR"
  docker compose down
  [ -f /tmp/agents-backend.pid ]  && kill "$(cat /tmp/agents-backend.pid)"  2>/dev/null && rm /tmp/agents-backend.pid  || true
  [ -f /tmp/agents-frontend.pid ] && kill "$(cat /tmp/agents-frontend.pid)" 2>/dev/null && rm /tmp/agents-frontend.pid || true
  ok "All services stopped"
}

show_status() {
  header "Service Status"
  echo "Docker containers:"
  cd "$ROOT_DIR" && docker compose ps
  echo ""
  echo -e "${CYAN}Backend (port 8000):${RESET}"
  nc -z localhost 8000 2>/dev/null && echo -e "  ${GREEN}[RUNNING]${RESET}" || echo -e "  ${RED}[STOPPED]${RESET}"
  echo -e "${CYAN}Frontend (port 3000):${RESET}"
  nc -z localhost 3000 2>/dev/null && echo -e "  ${GREEN}[RUNNING]${RESET}" || echo -e "  ${RED}[STOPPED]${RESET}"
}

show_logs() {
  header "Backend Logs (Ctrl+C to stop)"
  tail -f "$BACKEND_DIR/uvicorn_stdout.log"
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo ""
echo -e "${CYAN}  agents-trading runner${RESET}"
echo -e "${GRAY}  command: $COMMAND${RESET}"
echo ""

case "$COMMAND" in
  all)
    start_infra
    start_backend
    start_frontend
    header "All services started!"
    echo -e "  Frontend  → ${GREEN}http://localhost:3000${RESET}"
    echo -e "  Backend   → ${GREEN}http://localhost:8000${RESET}"
    echo -e "  API Docs  → ${GREEN}http://localhost:8000/docs${RESET}"
    echo -e "  Postgres  → ${GREEN}localhost:5432${RESET}"
    echo -e "  Redis     → ${GREEN}localhost:6379${RESET}"
    echo ""
    echo -e "  Logs: ${GRAY}backend/uvicorn_stdout.log${RESET}"
    echo -e "  Stop: ${GRAY}./run.sh stop${RESET}"
    echo ""
    ;;
  infra)    start_infra ;;
  backend)  start_infra; start_backend ;;
  frontend) start_frontend ;;
  stop)     stop_all ;;
  logs)     show_logs ;;
  status)   show_status ;;
  *)
    echo -e "${RED}Unknown command: $COMMAND${RESET}"
    echo "Usage: ./run.sh [all|infra|backend|frontend|stop|logs|status]"
    exit 1
    ;;
esac
