#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[error] ffmpeg is required. Install it first, for example: brew install ffmpeg"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[error] Python executable not found: $PYTHON_BIN"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[error] npm is required"
  exit 1
fi

if [[ ! -d node_modules ]]; then
  echo "[setup] Installing Node dependencies..."
  npm install
fi

if [[ ! -d .venv ]]; then
  echo "[setup] Creating Python virtual environment with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

if [[ ! -f .venv/.deps_installed ]]; then
  echo "[setup] Installing Python dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -r python_service/requirements.txt
  touch .venv/.deps_installed
fi

cleanup() {
  echo
  echo "[shutdown] Stopping services..."
  if [[ -n "${PY_PID:-}" ]]; then
    kill "$PY_PID" 2>/dev/null || true
  fi
  if [[ -n "${NODE_PID:-}" ]]; then
    kill "$NODE_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

echo "[start] Launching Python XTTS service..."
python python_service/app.py &
PY_PID=$!

echo "[start] Launching Node web service..."
node server.js &
NODE_PID=$!

echo "[ready] Python interpreter: $PYTHON_BIN"
echo "[ready] UI: http://127.0.0.1:3007"
echo "[ready] Press Ctrl+C to stop both services."

wait -n "$PY_PID" "$NODE_PID"
