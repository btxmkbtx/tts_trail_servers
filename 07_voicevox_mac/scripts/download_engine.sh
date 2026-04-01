#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_DIR="$ROOT_DIR/engine"
WORK_DIR="$ROOT_DIR/.engine_download"

# VOICEVOX Engine release (macOS ARM64 CPU)
VERSION="${VOICEVOX_ENGINE_VERSION:-0.25.1}"
ARCHIVE_NAME="voicevox_engine-macos-arm64-${VERSION}.7z.001"
DOWNLOAD_URL="https://github.com/VOICEVOX/voicevox_engine/releases/download/${VERSION}/${ARCHIVE_NAME}"

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

if [[ -f "$ENGINE_DIR/run" ]]; then
  echo "[skip] VOICEVOX engine already exists at $ENGINE_DIR/run"
  echo "[hint] Delete $ENGINE_DIR to force re-download."
  exit 0
fi

if ! command -v 7z >/dev/null 2>&1 && ! command -v 7za >/dev/null 2>&1; then
  echo "[error] p7zip is required to extract the engine archive."
  echo "[hint]  brew install p7zip"
  exit 1
fi

EXTRACT_CMD="7z"
command -v 7z >/dev/null 2>&1 || EXTRACT_CMD="7za"

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

mkdir -p "$WORK_DIR"
ARCHIVE_PATH="$WORK_DIR/$ARCHIVE_NAME"

if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "[setup] Downloading VOICEVOX Engine v${VERSION} for macOS ARM64..."
  echo "        URL: $DOWNLOAD_URL"
  curl -L --progress-bar -o "$ARCHIVE_PATH" "$DOWNLOAD_URL"
  echo "[done] Download complete."
else
  echo "[skip] Archive already downloaded: $ARCHIVE_PATH"
fi

# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

echo "[setup] Extracting engine to $ENGINE_DIR ..."
"$EXTRACT_CMD" x "$ARCHIVE_PATH" -o"$WORK_DIR/extracted" -y

# Find the extracted run binary (may be nested in a subdirectory)
RUN_BIN=$(find "$WORK_DIR/extracted" -name "run" -type f | head -1)
if [[ -z "$RUN_BIN" ]]; then
  echo "[error] Could not find 'run' binary after extraction."
  echo "        Contents:"
  find "$WORK_DIR/extracted" -maxdepth 3 | head -20
  exit 1
fi

ENGINE_EXTRACTED_DIR="$(dirname "$RUN_BIN")"
mv "$ENGINE_EXTRACTED_DIR" "$ENGINE_DIR"
chmod +x "$ENGINE_DIR/run"

# Cleanup download files
rm -rf "$WORK_DIR"

echo ""
echo "[done] VOICEVOX Engine installed at: $ENGINE_DIR"
echo "[hint] Run 'bash ./start.sh' to launch the service."
echo ""
