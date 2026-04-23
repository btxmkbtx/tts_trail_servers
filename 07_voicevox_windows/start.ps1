#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT_DIR

# ---------- 配置（支持环境变量覆盖） ----------
$NODE_PORT     = if ($env:PORT)          { $env:PORT }          else { "3010" }
$VOICEVOX_PORT = if ($env:VOICEVOX_PORT) { $env:VOICEVOX_PORT } else { "50021" }
$ENGINE_DIR    = Join-Path $ROOT_DIR "engine"
$ENGINE_BIN    = Join-Path $ENGINE_DIR "run.exe"

# ---------- 前置命令检查 ----------
function Require-Cmd($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Error "[error] Missing required command: $name"
        exit 1
    }
}

Require-Cmd npm
Require-Cmd node

# ---------- Node 依赖 ----------
if (-not (Test-Path "node_modules")) {
    Write-Host "[setup] Installing Node dependencies..."
    npm install
}

# ---------- VOICEVOX 引擎检查 ----------
if (-not (Test-Path $ENGINE_BIN)) {
    Write-Host ""
    Write-Warning "[warn] VOICEVOX engine not found at: $ENGINE_BIN"
    Write-Host "[hint] Run the following command to download the engine:"
    Write-Host "       .\scripts\download_engine.ps1"
    Write-Host ""
    exit 1
}

# ---------- 启动服务 ----------
# --use_gpu 启用 CUDA/DirectML 加速（需 NVIDIA 版引擎）。设置 $env:VOICEVOX_USE_GPU="false" 可禁用
$useGpu = if ($env:VOICEVOX_USE_GPU -eq "false") { $false } else { $true }
$engineArgs = @("--host", "127.0.0.1", "--port", $VOICEVOX_PORT)
if ($useGpu) { $engineArgs += "--use_gpu" }

Write-Host "[start] Launching VOICEVOX engine on port $VOICEVOX_PORT (use_gpu=$useGpu) ..."
$VvProc = Start-Process -FilePath $ENGINE_BIN `
    -ArgumentList $engineArgs `
    -WorkingDirectory $ENGINE_DIR `
    -PassThru -NoNewWindow

# 等待引擎就绪（最多 60 秒）
Write-Host "[start] Waiting for VOICEVOX engine to be ready..."
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$VOICEVOX_PORT/version" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $version = $resp.Content.Trim('"')
            Write-Host "[ready] VOICEVOX engine v$version is ready"
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $ready) {
    Write-Error "[error] VOICEVOX engine did not start within 60 seconds"
    if (-not $VvProc.HasExited) { $VvProc.Kill() }
    exit 1
}

# 启动 Node 服务
Write-Host "[start] Launching Node service on port $NODE_PORT ..."
$env:PORT = $NODE_PORT
$env:VOICEVOX_URL = "http://127.0.0.1:$VOICEVOX_PORT"
$NodeProc = Start-Process -FilePath "node" `
    -ArgumentList "server.js" `
    -PassThru -NoNewWindow

Write-Host ""
Write-Host "[ready] UI:     http://127.0.0.1:$NODE_PORT"
Write-Host "[ready] Health: http://127.0.0.1:$NODE_PORT/health"
Write-Host "[ready] Press Ctrl+C to stop."
Write-Host ""

try {
    while (-not $VvProc.HasExited -and -not $NodeProc.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`n[shutdown] Stopping services..."
    if (-not $VvProc.HasExited)   { $VvProc.Kill() }
    if (-not $NodeProc.HasExited) { $NodeProc.Kill() }
}
