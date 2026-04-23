#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT_DIR   = Split-Path -Parent $SCRIPT_DIR
$ENGINE_DIR = Join-Path $ROOT_DIR "engine"
$WORK_DIR   = Join-Path $ROOT_DIR ".engine_download"

# ---------- 配置 ----------
$VERSION = if ($env:VOICEVOX_ENGINE_VERSION) { $env:VOICEVOX_ENGINE_VERSION } else { "0.25.1" }
$ENGINE_TYPE = if ($env:VOICEVOX_ENGINE_TYPE) { $env:VOICEVOX_ENGINE_TYPE } else { "nvidia" }
$MAX_PARTS = if ($env:VOICEVOX_MAX_PARTS) { [int]$env:VOICEVOX_MAX_PARTS } else { 20 }

$ARCHIVE_BASE  = "voicevox_engine-windows-$ENGINE_TYPE-$VERSION.7z"
$DOWNLOAD_BASE = "https://github.com/VOICEVOX/voicevox_engine/releases/download/$VERSION"

# ---------- 前置检查 ----------
if (Test-Path (Join-Path $ENGINE_DIR "run.exe")) {
    Write-Host "[skip] VOICEVOX engine already exists at $ENGINE_DIR\run.exe"
    Write-Host "[hint] Delete $ENGINE_DIR to force re-download."
    exit 0
}

# 查找 7z.exe（优先顺序：环境变量 → PATH → 常见安装路径）
$SEVENZIP = $null
if ($env:SEVENZIP_PATH -and (Test-Path $env:SEVENZIP_PATH)) {
    $SEVENZIP = $env:SEVENZIP_PATH
} else {
    $cmd = Get-Command "7z" -ErrorAction SilentlyContinue
    if ($cmd) {
        $SEVENZIP = $cmd.Source
    } else {
        $candidates = @(
            "D:\Install\7zip\7z.exe",
            "C:\Program Files\7-Zip\7z.exe",
            "C:\Program Files (x86)\7-Zip\7z.exe",
            "$env:USERPROFILE\scoop\apps\7zip\current\7z.exe"
        )
        foreach ($p in $candidates) {
            if (Test-Path $p) { $SEVENZIP = $p; break }
        }
    }
}

if (-not $SEVENZIP) {
    Write-Host "[error] 7-Zip is required to extract the engine archive." -ForegroundColor Red
    Write-Host "[hint]  Install via one of:"
    Write-Host "          winget install 7zip.7zip"
    Write-Host "          scoop install 7zip"
    exit 1
}
Write-Host "[info] Using 7-Zip: $SEVENZIP"

# ---------- 下载所有分卷 ----------
New-Item -ItemType Directory -Force -Path $WORK_DIR | Out-Null

Write-Host "[setup] Downloading VOICEVOX Engine v$VERSION ($ENGINE_TYPE) for Windows x64..."

$downloadedParts = @()
for ($i = 1; $i -le $MAX_PARTS; $i++) {
    $partSuffix = "{0:D3}" -f $i
    $partName   = "$ARCHIVE_BASE.$partSuffix"
    $partUrl    = "$DOWNLOAD_BASE/$partName"
    $partPath   = Join-Path $WORK_DIR $partName

    if (Test-Path $partPath) {
        Write-Host "[skip] Part $partSuffix already downloaded."
        $downloadedParts += $partPath
        continue
    }

    # 先用 HEAD 探测分卷是否存在（GitHub/CDN 对不存在的 .N 有时返回 404、有时直接断开连接，HEAD 更稳定）
    $exists = $true
    try {
        Invoke-WebRequest -Uri $partUrl -Method Head -UseBasicParsing -ErrorAction Stop | Out-Null
    } catch {
        $exists = $false
    }
    if (-not $exists) {
        if ($downloadedParts.Count -gt 0) {
            Write-Host "[done] No more parts (stopped at $partSuffix)."
            break
        } else {
            Write-Host "[error] First part does not exist. Verify URL:" -ForegroundColor Red
            Write-Host "        $partUrl"
            exit 1
        }
    }

    try {
        Write-Host "[download] $partUrl"
        Invoke-WebRequest -Uri $partUrl -OutFile $partPath -UseBasicParsing
        $downloadedParts += $partPath
    } catch {
        Write-Host "[error] Failed to download $partName : $($_.Exception.Message)" -ForegroundColor Red
        if (Test-Path $partPath) {
            Write-Host "[hint] Partial file removed. Re-run to retry." -ForegroundColor Yellow
            Remove-Item $partPath -Force -ErrorAction SilentlyContinue
        }
        exit 1
    }
}

if ($downloadedParts.Count -eq 0) {
    Write-Host "[error] No parts downloaded. Verify URL pattern:" -ForegroundColor Red
    Write-Host "        $DOWNLOAD_BASE/$ARCHIVE_BASE.001"
    exit 1
}

Write-Host "[done] Downloaded $($downloadedParts.Count) part(s)."

# ---------- 解压 ----------
$EXTRACT_DIR = Join-Path $WORK_DIR "extracted"
New-Item -ItemType Directory -Force -Path $EXTRACT_DIR | Out-Null

$firstPart = Join-Path $WORK_DIR "$ARCHIVE_BASE.001"
Write-Host "[setup] Extracting engine to $ENGINE_DIR ..."
& $SEVENZIP x $firstPart "-o$EXTRACT_DIR" -y
if ($LASTEXITCODE -ne 0) {
    Write-Host "[error] 7-Zip extraction failed." -ForegroundColor Red
    exit 1
}

# 找到 run.exe
$runBin = Get-ChildItem -Path $EXTRACT_DIR -Filter "run.exe" -Recurse -File | Select-Object -First 1
if (-not $runBin) {
    Write-Host "[error] Could not find 'run.exe' after extraction." -ForegroundColor Red
    Get-ChildItem -Path $EXTRACT_DIR -Recurse -Depth 3 | Select-Object -First 20 | Format-Table -AutoSize
    exit 1
}

$extractedDir = $runBin.Directory.FullName
Write-Host "[info] Found run.exe at: $($runBin.FullName)"

Move-Item -Path $extractedDir -Destination $ENGINE_DIR -Force

Remove-Item -Recurse -Force $WORK_DIR

Write-Host ""
Write-Host "[done] VOICEVOX Engine installed at: $ENGINE_DIR"
Write-Host "[hint] Run '.\start.ps1' to launch the service."
Write-Host ""
