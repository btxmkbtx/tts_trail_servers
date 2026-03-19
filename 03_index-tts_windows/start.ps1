#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$ROOT_DIR   = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT_DIR

# ---------- 配置（支持环境变量覆盖） ----------
$PYTHON_BIN  = if ($env:PYTHON_BIN)                { $env:PYTHON_BIN }                else { "python" }
$REPO_URL    = if ($env:INDEX_TTS_REPO_URL)         { $env:INDEX_TTS_REPO_URL }         else { "https://github.com/index-tts/index-tts.git" }
$VENDOR_DIR  = if ($env:INDEX_TTS_VENDOR_DIR)       { $env:INDEX_TTS_VENDOR_DIR }       else { Join-Path $ROOT_DIR "vendor\index-tts" }
$NODE_PORT   = if ($env:PORT)                       { $env:PORT }                       else { "3008" }
$PY_PORT     = if ($env:PYTHON_SERVICE_PORT)        { $env:PYTHON_SERVICE_PORT }        else { "5012" }
$SKIP_LFS    = if ($env:INDEX_TTS_SKIP_LFS_SMUDGE) { $env:INDEX_TTS_SKIP_LFS_SMUDGE } else { "1" }

$VENV_PYTHON = Join-Path $ROOT_DIR ".venv\Scripts\python.exe"

# ---------- 前置命令检查 ----------
function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "[error] Missing required command: $name"
        exit 1
    }
}

Require-Cmd ffmpeg
Require-Cmd git
Require-Cmd git-lfs
Require-Cmd uv
Require-Cmd npm
Require-Cmd $PYTHON_BIN

git lfs install 2>$null

# ---------- Node 依赖 ----------
if (-not (Test-Path "node_modules")) {
    Write-Host "[setup] Installing Node dependencies..."
    npm install
}

# ---------- bridge venv ----------
if (-not (Test-Path ".venv")) {
    Write-Host "[setup] Creating bridge Python venv with $PYTHON_BIN ..."
    & $PYTHON_BIN -m venv .venv
}

if (-not (Test-Path ".venv\.deps_installed")) {
    Write-Host "[setup] Installing bridge Python dependencies..."
    & $VENV_PYTHON -m pip install --upgrade pip --quiet
    & $VENV_PYTHON -m pip install -r python_service\requirements.txt
    New-Item ".venv\.deps_installed" -ItemType File -Force | Out-Null
}

# ---------- vendor 仓库 ----------
if ((Test-Path "$VENDOR_DIR\.git") -and (-not (Test-Path "$VENDOR_DIR\README.md"))) {
    Write-Warning "[warn] Broken vendor checkout detected. Removing and re-cloning..."
    Remove-Item -Recurse -Force $VENDOR_DIR
}

if (-not (Test-Path "$VENDOR_DIR\.git")) {
    Write-Host "[setup] Cloning IndexTTS repository..."
    if ($SKIP_LFS -eq "1") {
        $env:GIT_LFS_SKIP_SMUDGE = "1"
        git clone $REPO_URL $VENDOR_DIR
        Remove-Item Env:GIT_LFS_SKIP_SMUDGE -ErrorAction SilentlyContinue
    } else {
        git clone $REPO_URL $VENDOR_DIR
    }
}

# ---------- vendor uv 环境 ----------
if (-not (Test-Path "$VENDOR_DIR\.venv\pyvenv.cfg")) {
    Write-Host "[setup] Running uv sync for vendor environment..."
    Push-Location $VENDOR_DIR
    uv sync
    Pop-Location
}

# ---------- 模型文件检查 ----------
$MODEL_DIR = if ($env:INDEX_TTS_MODEL_DIR) { $env:INDEX_TTS_MODEL_DIR } else { Join-Path $VENDOR_DIR "checkpoints" }
$REQUIRED  = @("bpe.model", "gpt.pth", "config.yaml", "s2mel.pth", "wav2vec2bert_stats.pt")
$missing   = $REQUIRED | Where-Object { -not (Test-Path (Join-Path $MODEL_DIR $_)) }
if ($missing) {
    Write-Warning "[warn] Missing model files: $($missing -join ', ')"
    Write-Warning "[warn] Run .\scripts\download_model.ps1 before first synthesis."
}

# ---------- 启动两个服务 ----------
$env:PYTHON_SERVICE_PORT = $PY_PORT
$env:INDEX_TTS_VENDOR_DIR = $VENDOR_DIR
$env:PORT = $NODE_PORT
$env:PYTHON_SERVICE_URL = "http://127.0.0.1:$PY_PORT"
if (-not $env:INDEX_TTS_DEVICE)   { $env:INDEX_TTS_DEVICE   = "cuda:0" }
if (-not $env:INDEX_TTS_USE_FP16) { $env:INDEX_TTS_USE_FP16 = "true" }

Write-Host "[start] Launching Python bridge service on port $PY_PORT ..."
$PyProc = Start-Process -FilePath $VENV_PYTHON `
    -ArgumentList "python_service\app.py" `
    -PassThru -NoNewWindow

Write-Host "[start] Launching Node web server on port $NODE_PORT ..."
$NodeProc = Start-Process -FilePath "node" `
    -ArgumentList "server.js" `
    -PassThru -NoNewWindow

Write-Host "[ready] UI:     http://127.0.0.1:$NODE_PORT"
Write-Host "[ready] Health: http://127.0.0.1:$NODE_PORT/health"
Write-Host "[ready] Press Ctrl+C to stop both services."

try {
    while (-not $PyProc.HasExited -and -not $NodeProc.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`n[shutdown] Stopping services..."
    if (-not $PyProc.HasExited)   { $PyProc.Kill() }
    if (-not $NodeProc.HasExited) { $NodeProc.Kill() }
}
