#!/usr/bin/env bash
# Build Ofy: install backend + frontend dependencies and build the UI.
#
#   ./build.sh            install deps (if needed) and build
#   ./build.sh --clean    wipe node_modules, dist and the backend venv first
#   ./build.sh --test     also run the backend unit tests
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLEAN=0
TEST=0
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --test) TEST=1 ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found. $2" >&2; exit 1; }; }

need uv "Install it: https://docs.astral.sh/uv/getting-started/installation/"
need npm "Install Node.js 18+ (https://nodejs.org)."
command -v ffmpeg >/dev/null 2>&1 || echo "warning: ffmpeg not found on PATH; downloads will fail until it is installed." >&2

if [[ $CLEAN == 1 ]]; then
  step "Cleaning"
  rm -rf "$ROOT/frontend/node_modules" "$ROOT/frontend/dist" "$ROOT/backend/.venv"
fi

step "Backend: uv sync"
(cd "$ROOT/backend" && uv sync && touch .venv)  # touch: lets run.sh detect staleness

step "Frontend: npm install"
cd "$ROOT/frontend"
if [[ -f package-lock.json ]]; then
  # npm ci is reproducible; skip it when node_modules is already in sync with the lockfile
  if [[ ! -d node_modules || package-lock.json -nt node_modules/.package-lock.json ]]; then
    npm ci
  else
    echo "node_modules up to date"
  fi
else
  npm install
fi

step "Frontend: build"
npm run build

if [[ $TEST == 1 ]]; then
  step "Backend: tests"
  (cd "$ROOT/backend" && uv run pytest -q)
fi

step "Done. Start with ./run.sh"
