#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

NODE_PORT="${PORT:-3010}"
VOICEVOX_PORT="${VOICEVOX_PORT:-50021}"
ENGINE_DIR="$ROOT_DIR/engine"
ENGINE_BIN="$ENGINE_DIR/run"

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
require_cmd node

# ---------------------------------------------------------------------------
# Node dependencies
# ---------------------------------------------------------------------------

if [[ ! -d node_modules ]]; then
  echo "[setup] Installing Node dependencies..."
  npm install
fi

# ---------------------------------------------------------------------------
# VOICEVOX Engine check
# ---------------------------------------------------------------------------

if [[ ! -f "$ENGINE_BIN" ]]; then
  echo ""
  echo "[warn] VOICEVOX engine not found at: $ENGINE_BIN"
  echo "[hint] Run the following command to download the engine:"
  echo "       bash ./scripts/download_engine.sh"
  echo ""
  exit 1
fi

chmod +x "$ENGINE_BIN"

# ---------------------------------------------------------------------------
# Launch services
# ---------------------------------------------------------------------------

cleanup() {
  echo
  echo "[shutdown] Stopping services..."
  [[ -n "${VV_PID:-}" ]]   && kill "$VV_PID"   2>/dev/null || true
  [[ -n "${NODE_PID:-}" ]] && kill "$NODE_PID"  2>/dev/null || true
}

trap cleanup EXIT INT TERM

echo "[start] Launching VOICEVOX engine on port $VOICEVOX_PORT ..."
"$ENGINE_BIN" --host 127.0.0.1 --port "$VOICEVOX_PORT" &
VV_PID=$!

# Wait until engine is ready (max 60s)
echo "[start] Waiting for VOICEVOX engine to be ready..."
for i in $(seq 1 60); do
  if curl -s "http://127.0.0.1:$VOICEVOX_PORT/version" >/dev/null 2>&1; then
    VV_VERSION=$(curl -s "http://127.0.0.1:$VOICEVOX_PORT/version" | tr -d '"')
    echo "[ready] VOICEVOX engine v${VV_VERSION} is ready"
    break
  fi
  sleep 1
  if [[ $i -eq 60 ]]; then
    echo "[error] VOICEVOX engine did not start within 60 seconds"
    exit 1
  fi
done

echo "[start] Launching Node service on port $NODE_PORT ..."
PORT="$NODE_PORT" VOICEVOX_URL="http://127.0.0.1:$VOICEVOX_PORT" node server.js &
NODE_PID=$!

echo ""
echo "[ready] UI:     http://127.0.0.1:$NODE_PORT"
echo "[ready] Health: http://127.0.0.1:$NODE_PORT/health"
echo "[ready] Press Ctrl+C to stop."
echo ""

while kill -0 "$VV_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do
  sleep 1
done

wait "$VV_PID"   2>/dev/null || true
wait "$NODE_PID" 2>/dev/null || true
