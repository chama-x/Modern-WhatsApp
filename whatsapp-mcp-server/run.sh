#!/bin/bash
# Simple runner script for whatsapp-mcp-server
# Usage:
#   ./run.sh quick        -> install deps, seed demo, run API
#   ./run.sh dev          -> install deps, seed demo, run dev API (reload)
#   ./run.sh api          -> just run API (assumes deps/db ready)
#   ./run.sh mcp          -> run MCP stdio server
#   ./run.sh seed         -> seed demo data
#   ./run.sh reset        -> reset & seed demo data
#   ./run.sh health       -> check API health

set -e

PY=${PY:-python}
PIP=${PIP:-pip}
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}
DB_SCRIPT="../whatsapp-bridge/store/initialize_messages_db.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[run]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[warn]${NC} $1"
}

error() {
    echo -e "${RED}[error]${NC} $1"
    exit 1
}

install_deps() {
    log "Installing dependencies..."
    $PIP install -e .
}

seed_db() {
    log "Seeding database with demo data..."
    $PY "$DB_SCRIPT" --seed
}

reset_db() {
    log "Resetting database..."
    $PY "$DB_SCRIPT" --reset --seed
}

run_api() {
    log "Starting API server at http://$HOST:$PORT"
    $PY api_server.py
}

run_api_dev() {
    log "Starting dev API server (auto-reload) at http://$HOST:$PORT"
    $PY -m uvicorn api_server:app --reload --port $PORT --host $HOST
}

run_mcp() {
    log "Starting MCP stdio server..."
    $PY main.py
}

check_health() {
    log "Checking API health..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "http://localhost:$PORT/api/health" || warn "Health check failed"
    else
        warn "curl not found - cannot check health"
    fi
}

show_help() {
    echo "Usage: $0 <command>"
    echo
    echo "Commands:"
    echo "  quick     Install deps, seed demo data, run API"
    echo "  dev       Install deps, seed demo data, run dev API (auto-reload)"
    echo "  api       Run API server (assumes deps/db ready)"
    echo "  mcp       Run MCP stdio server"
    echo "  seed      Seed demo data"
    echo "  reset     Reset & seed demo data"
    echo "  health    Check API health"
    echo "  install   Install dependencies only"
    echo
    echo "Environment variables:"
    echo "  PY=python3.11  (override Python executable)"
    echo "  PORT=9000      (override API port)"
    echo "  HOST=127.0.0.1 (override bind address)"
}

# Main command dispatch
case "${1:-help}" in
    quick)
        install_deps
        seed_db
        run_api
        ;;
    dev)
        install_deps
        seed_db
        run_api_dev
        ;;
    api)
        run_api
        ;;
    mcp)
        run_mcp
        ;;
    seed)
        seed_db
        ;;
    reset)
        reset_db
        ;;
    health)
        check_health
        ;;
    install)
        install_deps
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        error "Unknown command: $1. Use '$0 help' for usage."
        ;;
esac
