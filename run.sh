#!/usr/bin/env bash
# Run Ofy. Builds first when the UI/dependencies are missing or out of date.
#
#   ./run.sh              desktop app (native window)
#   ./run.sh web          web server only: UI at http://localhost:8080
#   ./run.sh dev          development: backend (auto-reload) + Vite dev server (hot reload) at
#                         http://localhost:5173; Ctrl-C stops both
#
# Extra arguments are passed through, e.g. `./run.sh desktop --debug` or `./run.sh web --port 9000`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-desktop}"
[[ $# -gt 0 ]] && shift

case "$MODE" in
  desktop|web|dev) ;;
  -h|--help|help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
  *) echo "unknown mode: $MODE (use desktop, web or dev)" >&2; exit 2 ;;
esac

# Rebuild when the venv/node_modules are missing or the UI sources are newer than the build.
needs_build() {
  [[ -d "$ROOT/backend/.venv" && -d "$ROOT/frontend/node_modules" ]] || return 0
  [[ "$ROOT/backend/uv.lock" -nt "$ROOT/backend/.venv" ]] && return 0
  [[ "$ROOT/frontend/package-lock.json" -nt "$ROOT/frontend/node_modules/.package-lock.json" ]] && return 0
  [[ $MODE == dev ]] && return 1  # dev serves the sources directly, no dist needed
  local index="$ROOT/frontend/dist/index.html"
  [[ -f "$index" ]] || return 0
  [[ -n "$(find "$ROOT/frontend/src" "$ROOT/frontend/public" "$ROOT/frontend/index.html" \
           "$ROOT/frontend/package.json" "$ROOT/frontend"/*.config.* -newer "$index" -print -quit)" ]]
}

if needs_build; then
  "$ROOT/build.sh"
fi

cd "$ROOT/backend"
case "$MODE" in
  desktop)
    exec uv run ofy-desktop "$@"
    ;;
  web)
    PORT=8080
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --port) PORT="$2"; shift 2 ;;
        *) echo "unknown option for web: $1" >&2; exit 2 ;;
      esac
    done
    echo "Ofy web UI: http://localhost:$PORT"
    OFY_PORT="$PORT" exec uv run python -m ofy
    ;;
  dev)
    # Job control puts each server in its own process group, so cleanup can stop the whole tree
    # (uv -> python -> uvicorn reloader -> worker, and Vite's node process) with one signal.
    set -m
    pids=()
    cleanup() {
      trap - INT TERM EXIT
      for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
      wait 2>/dev/null || true
    }
    trap cleanup INT TERM EXIT
    uv run uvicorn ofy.main:app --host 127.0.0.1 --port 8080 --reload --reload-dir src &
    pids+=($!)
    # Run Vite directly (not via `npm run`), npm doesn't reliably forward signals to it.
    (cd "$ROOT/frontend" && exec ./node_modules/.bin/vite --host 127.0.0.1) &
    pids+=($!)
    echo "Dev UI: http://localhost:5173  (API on :8080, both reload on change; Ctrl-C to stop)"
    # Stop everything as soon as either process exits
    wait -n "${pids[@]}"
    ;;
esac
