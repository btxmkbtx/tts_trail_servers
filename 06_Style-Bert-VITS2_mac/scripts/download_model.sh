#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="$ROOT_DIR/models"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"

# 下载目标 HuggingFace repo（可通过环境变量覆盖）
HF_REPO="${SBV2_HF_REPO:-litagin/style_bert_vits2_jvnv}"
# 下载到 models/ 下的子目录名（默认取 repo 名的最后一段）
MODEL_NAME="${SBV2_MODEL_NAME:-${HF_REPO##*/}}"
LOCAL_DIR="$MODELS_DIR/$MODEL_NAME"

# HF 镜像加速（国内可用 https://hf-mirror.com）
if [[ -n "${HF_ENDPOINT:-}" ]]; then
  echo "[info] Using HF_ENDPOINT=$HF_ENDPOINT"
  export HF_ENDPOINT
fi

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------

if [[ ! -f "$VENV_PYTHON" ]]; then
  echo "[error] Virtual environment not found at $ROOT_DIR/.venv"
  echo "[hint]  Run 'bash ./start.sh' once first to create the venv."
  exit 1
fi

# ---------------------------------------------------------------------------
# BERT base models (required for text analysis)
# ---------------------------------------------------------------------------

BERT_DIR="$ROOT_DIR/.venv/lib/python3.11/site-packages/bert"

mkdir -p "$BERT_DIR"

_download_bert() {
  local dir_name="$1"
  local repo="$2"
  local local_path="$BERT_DIR/$dir_name"
  if [[ -d "$local_path" ]] && [[ -n "$(ls -A "$local_path" 2>/dev/null)" ]]; then
    echo "[skip] BERT model already exists: $dir_name"
  else
    echo "[setup] Downloading BERT model '$repo' → $local_path ..."
    "$VENV_PYTHON" -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='$repo', local_dir='$local_path')
print('[done] $dir_name')
"
  fi
}

_download_bert "deberta-v2-large-japanese-char-wwm" "ku-nlp/deberta-v2-large-japanese-char-wwm"
_download_bert "deberta-v3-large"                   "microsoft/deberta-v3-large"
_download_bert "chinese-roberta-wwm-ext-large"      "hfl/chinese-roberta-wwm-ext-large"

# ---------------------------------------------------------------------------
# Voice model
# ---------------------------------------------------------------------------

echo "[setup] Downloading '$HF_REPO' → $LOCAL_DIR ..."
"$VENV_PYTHON" - <<PYEOF
from huggingface_hub import snapshot_download
import sys

repo_id = "$HF_REPO"
local_dir = "$LOCAL_DIR"

try:
    path = snapshot_download(repo_id=repo_id, local_dir=local_dir)
    print(f"[done] Downloaded to: {path}")
except Exception as e:
    print(f"[error] Download failed: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
