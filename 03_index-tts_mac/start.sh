#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
INDEX_TTS_REPO_URL="${INDEX_TTS_REPO_URL:-https://github.com/index-tts/index-tts.git}"
INDEX_TTS_VENDOR_DIR="${INDEX_TTS_VENDOR_DIR:-$ROOT_DIR/vendor/index-tts}"
INDEX_TTS_NODE_PORT="${PORT:-3008}"
PYTHON_SERVICE_PORT="${PYTHON_SERVICE_PORT:-5012}"
INDEX_TTS_SKIP_LFS_SMUDGE="${INDEX_TTS_SKIP_LFS_SMUDGE:-1}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] Missing required command: $1"
    exit 1
  fi
}

require_cmd ffmpeg
require_cmd git
require_cmd git-lfs
require_cmd uv
require_cmd npm
require_cmd "$PYTHON_BIN"

git lfs install >/dev/null 2>&1 || true

if [[ ! -d node_modules ]]; then
  echo "[setup] Installing Node dependencies..."
  npm install
fi

if [[ ! -d .venv ]]; then
  echo "[setup] Creating bridge Python virtual environment with $PYTHON_BIN ..."
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate

if [[ ! -f .venv/.deps_installed ]]; then
  echo "[setup] Installing bridge Python dependencies..."
  python -m pip install --upgrade pip
  python -m pip install -r python_service/requirements.txt
  touch .venv/.deps_installed
fi

if [[ -d "$INDEX_TTS_VENDOR_DIR/.git" && ! -f "$INDEX_TTS_VENDOR_DIR/README.md" ]]; then
  echo "[warn] Broken vendor checkout detected. Removing and re-cloning..."
  rm -rf "$INDEX_TTS_VENDOR_DIR"
fi

if [[ ! -d "$INDEX_TTS_VENDOR_DIR/.git" ]]; then
  echo "[setup] Cloning IndexTTS repository..."
  if [[ "$INDEX_TTS_SKIP_LFS_SMUDGE" == "1" ]]; then
    GIT_LFS_SKIP_SMUDGE=1 git clone "$INDEX_TTS_REPO_URL" "$INDEX_TTS_VENDOR_DIR"
  else
    git clone "$INDEX_TTS_REPO_URL" "$INDEX_TTS_VENDOR_DIR"
  fi
fi

if [[ ! -f "$INDEX_TTS_VENDOR_DIR/.venv/pyvenv.cfg" ]]; then
  echo "[setup] Syncing IndexTTS vendor environment with uv..."
  (cd "$INDEX_TTS_VENDOR_DIR" && uv sync)
fi

MODEL_DIR="${INDEX_TTS_MODEL_DIR:-$INDEX_TTS_VENDOR_DIR/checkpoints}"
REQUIRED_FILES=(bpe.model gpt.pth config.yaml s2mel.pth wav2vec2bert_stats.pt)
MISSING_MODELS=0
for file in "${REQUIRED_FILES[@]}"; do
  if [[ ! -f "$MODEL_DIR/$file" ]]; then
    MISSING_MODELS=1
  fi
done

if [[ "$MISSING_MODELS" -eq 1 ]]; then
  echo "[warn] IndexTTS2 model files are not complete in $MODEL_DIR"
  echo "[warn] Run ./scripts/download_model.sh before first real synthesis."
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

echo "[start] Launching Python bridge service on $PYTHON_SERVICE_PORT ..."
PYTHON_SERVICE_PORT="$PYTHON_SERVICE_PORT" INDEX_TTS_VENDOR_DIR="$INDEX_TTS_VENDOR_DIR" python python_service/app.py &
PY_PID=$!

echo "[start] Launching Node web service on $INDEX_TTS_NODE_PORT ..."
PORT="$INDEX_TTS_NODE_PORT" PYTHON_SERVICE_URL="http://127.0.0.1:$PYTHON_SERVICE_PORT" node server.js &
NODE_PID=$!

echo "[ready] UI: http://127.0.0.1:$INDEX_TTS_NODE_PORT"
echo "[ready] Health: http://127.0.0.1:$INDEX_TTS_NODE_PORT/health"
echo "[ready] Press Ctrl+C to stop both services."

while kill -0 "$PY_PID" 2>/dev/null && kill -0 "$NODE_PID" 2>/dev/null; do
  sleep 1
done

wait "$PY_PID" 2>/dev/null || true
wait "$NODE_PID" 2>/dev/null || true
