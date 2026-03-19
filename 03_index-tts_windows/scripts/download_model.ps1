#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$ROOT_DIR   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$VENDOR_DIR = if ($env:INDEX_TTS_VENDOR_DIR) { $env:INDEX_TTS_VENDOR_DIR } else { Join-Path $ROOT_DIR "vendor\index-tts" }
$MODEL_DIR  = if ($env:INDEX_TTS_MODEL_DIR)  { $env:INDEX_TTS_MODEL_DIR }  else { Join-Path $VENDOR_DIR "checkpoints" }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error "[error] uv is required"
    exit 1
}

if (-not (Test-Path $VENDOR_DIR)) {
    Write-Error "[error] Missing vendor repository at $VENDOR_DIR"
    Write-Host "[hint] Run .\start.ps1 once to clone the repo scaffold."
    exit 1
}

if ($env:HF_ENDPOINT) {
    Write-Host "[info] Using HF_ENDPOINT=$($env:HF_ENDPOINT)"
}

Write-Host "[setup] Downloading IndexTTS-2 model files into $MODEL_DIR ..."
Push-Location $VENDOR_DIR
uvx --from "huggingface-hub[cli,hf_xet]" hf download IndexTeam/IndexTTS-2 --local-dir $MODEL_DIR
Pop-Location

Write-Host "[done] Model download completed."
