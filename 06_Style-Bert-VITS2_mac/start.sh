#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
SBV2_NODE_PORT="${PORT:-3009}"
PYTHON_SERVICE_PORT="${PYTHON_SERVICE_PORT:-5013}"

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] Missing required command: $1"
    echo "[error] Install with: brew install $1"
    exit 1
  fi
}

require_cmd npm
require_cmd "$PYTHON_BIN"
require_cmd cmake

# ---------------------------------------------------------------------------
# Node dependencies
# ---------------------------------------------------------------------------

if [[ ! -d node_modules ]]; then
  echo "[setup] Installing Node dependencies..."
  npm install
fi

# ---------------------------------------------------------------------------
# Python virtual environment
# ---------------------------------------------------------------------------

if [[ ! -d .venv ]]; then
  echo "[setup] Creating Python virtual environment with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

if [[ ! -f .venv/.deps_installed ]]; then
  echo "[setup] Installing Python dependencies..."
  python -m pip install --upgrade pip

  # Install torch for the current platform
  if [[ "$(uname -m)" == "arm64" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
    echo "[setup] Apple Silicon detected — installing torch with MPS support..."
    python -m pip install torch torchaudio
  else
    echo "[setup] Installing torch (CPU)..."
    python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
  fi

  python -m pip install -r python_service/requirements.txt
  touch .venv/.deps_installed
fi

# ---------------------------------------------------------------------------
# Model check
# ---------------------------------------------------------------------------

MODEL_COUNT=$(find "$ROOT_DIR/models" -mindepth 2 -name "*.safetensors" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$MODEL_COUNT" -eq 0 ]]; then
  echo ""
  echo "[warn] No models found in $ROOT_DIR/models/"
  echo "[warn] Place a model directory there with:"
  echo "[warn]   models/<model_name>/*.safetensors"
  echo "[warn]   models/<model_name>/config.json"
  echo "[warn]   models/<model_name>/style_vectors.npy"
  echo ""
fi

# ---------------------------------------------------------------------------
# Launch services
# ---------------------------------------------------------------------------

cleanup() {
  echo
  echo "[shutdown] Stopping services..."
  [[ -n "${PY_PID:-}" ]] && kill "$PY_PID" 2>/dev/null || true
  [[ -n "${NODE_PID:-}" ]] && kill "$NODE_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "[start] Launching Python service on port $PYTHON_SERVICE_PORT ..."
PYTHON_SERVICE_PORT="$PYTHON_SERVICE_PORT" python python_service/app.py &
PY_PID=$!

echo "[start] Launching Node service on port $SBV2_NODE_PORT ..."
PORT="$SBV2_NODE_PORT" PYTHON_SERVICE_URL="http://127.0.0.1:$PYTHON_SERVICE_PORT" node server.js &
NODE_PID=$!

echo ""
echo "[ready] UI:     http://127.0.0.1:$SBV2_NODE_PORT"
echo "[ready] Health: http://127.0.0.1:$SBV2_NODE_PORT/health"
echo "[ready] Press Ctrl+C to stop."
echo ""

while kill -0 "$PY_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do
  sleep 1
done

wait "$PY_PID" 2>/dev/null || true
wait "$NODE_PID" 2>/dev/null || true
