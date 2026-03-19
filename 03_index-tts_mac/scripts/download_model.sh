#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INDEX_TTS_VENDOR_DIR="${INDEX_TTS_VENDOR_DIR:-$ROOT_DIR/vendor/index-tts}"
MODEL_DIR="${INDEX_TTS_MODEL_DIR:-$INDEX_TTS_VENDOR_DIR/checkpoints}"
HF_ENDPOINT_VALUE="${HF_ENDPOINT:-}"

if ! command -v uv >/dev/null 2>&1; then
  echo "[error] uv is required"
  exit 1
fi

if [[ ! -d "$INDEX_TTS_VENDOR_DIR" ]]; then
  echo "[error] Missing vendor repository at $INDEX_TTS_VENDOR_DIR"
  echo "[hint] Run bash ./start.sh once to clone the repo scaffold."
  exit 1
fi

cd "$INDEX_TTS_VENDOR_DIR"

if [[ -n "$HF_ENDPOINT_VALUE" ]]; then
  echo "[info] Using HF_ENDPOINT=$HF_ENDPOINT_VALUE"
fi

echo "[setup] Downloading IndexTTS-2 model files into $MODEL_DIR ..."
uvx --from "huggingface-hub[cli,hf_xet]" hf download IndexTeam/IndexTTS-2 --local-dir "$MODEL_DIR"

echo "[done] Model download completed."
