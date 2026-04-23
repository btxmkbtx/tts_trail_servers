# 07_voicevox_windows

VOICEVOX 本地日语 TTS 服务器 —— Windows 11 版本。

基于 `07_voicevox_mac` 改造，适配 Windows 11 + NVIDIA GPU 环境。

---

## 目标硬件环境

| 配置项 | 规格 |
|--------|------|
| CPU | Intel Core i7-12700H（14核/20线程） |
| GPU | NVIDIA GeForce RTX 3070 Ti Laptop（8 GB VRAM） |
| RAM | 32 GB |
| OS | Windows 11 Pro |
| CUDA 驱动 | 581.95（支持 CUDA 12.x） |

---

## 与 Mac 版的核心差异

| 项目 | Mac 版 | Windows 版 |
|------|--------|-----------|
| 启动脚本 | `start.sh`（bash） | `start.ps1`（PowerShell） |
| 引擎下载脚本 | `scripts/download_engine.sh` | `scripts/download_engine.ps1` |
| 引擎二进制 | `engine/run`（ARM64） | `engine/run.exe`（x64） |
| 引擎变体 | macos-arm64 (CPU) | **windows-nvidia (CUDA 加速)** |
| 压缩分卷 | 单卷（.7z.001） | 多卷（.7z.001、.002...） |
| 解压工具 | `p7zip`（brew） | `7-Zip`（winget / scoop） |
| 下载工具 | `curl` | `Invoke-WebRequest` |
| 路径分隔符 | `/` | `\`（ffmpeg concat 列表内部仍用 `/`） |
| 进程管理 | `kill` / `trap` | `Start-Process` + `.Kill()` |

Node.js 代码（`server.js`）几乎无需修改，仅对 ffmpeg concat 列表的路径做了 Windows 反斜杠 → 正斜杠归一化。

---

## 前置依赖

### 需要安装的工具

```powershell
# 在普通用户 PowerShell 中执行（不要用管理员身份，否则 winget 可能报 Access denied）
winget install 7zip.7zip     # 用于解压引擎压缩包
winget install Gyan.FFmpeg   # 用于长文本分段音频合并

# 如需指定安装位置（示例：装到 D 盘）
winget install 7zip.7zip --location "D:\Install\7zip"
```

安装后**重启终端**使 PATH 生效，验证：

```powershell
7z          # 7-Zip（若用了自定义路径，会不在 PATH 中，但脚本会自动探测）
ffmpeg -version
node --version   # >= 18
npm --version
```

> 如果 7-Zip 装到非默认路径且不在 PATH 中，`download_engine.ps1` 会依次探测 `D:\Install\7zip\7z.exe` / `C:\Program Files\7-Zip\7z.exe` / Scoop 路径，或读取 `$env:SEVENZIP_PATH`。

### PowerShell 执行策略（首次需要确认）

```powershell
# 检查当前策略
Get-ExecutionPolicy -List
# 如果 LocalMachine 是 RemoteSigned，无需任何操作
# 否则执行：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 使用步骤

### 第一步：下载引擎（首次运行）

```powershell
cd 07_voicevox_windows

# 默认下载 NVIDIA CUDA 加速版（RTX 3070 Ti 推荐）
.\scripts\download_engine.ps1

# 无 GPU 时使用 CPU 版
$env:VOICEVOX_ENGINE_TYPE = "cpu"; .\scripts\download_engine.ps1
```

脚本会自动：
1. 从 GitHub 下载所有分卷压缩包（`voicevox_engine-windows-nvidia-0.25.1.7z.001` 及后续分卷）
2. 用 7-Zip 解压到 `./engine/`
3. 清理临时下载文件

NVIDIA 版 0.25.1 实测为 2 个分卷，共 **2.3 GB**（.001=1.9 GB，.002=405 MB），解压后 **3.9 GB**。CPU 版体积较小（未实测，约数百 MB）。

> 下载耗时：1.5 MB/s 下约 **25-30 分钟**。脚本支持断点续传（已完成的分卷会跳过）。

### 第二步：启动服务

```powershell
.\start.ps1

# 或通过 npm
npm run start:all
```

首次启动会加载 CUDA 内核，GPU 测试约 15 秒，看到 `CUDA (device_id=0): OK` 即代表 GPU 可用。
Web 界面：`http://127.0.0.1:3010`

### 可选环境变量

```powershell
$env:PORT = "3010"                 # Node.js UI 端口
$env:VOICEVOX_PORT = "50021"       # VOICEVOX Engine 端口
$env:VOICEVOX_URL = "http://127.0.0.1:50021"   # server.js 连接引擎的 URL
$env:VOICEVOX_USE_GPU = "false"    # 禁用 GPU（默认启用，仅 NVIDIA 引擎有效）
$env:SEVENZIP_PATH = "D:\Install\7zip\7z.exe"  # 自定义 7z.exe 路径
```

---

## 实测性能（RTX 3070 Ti + CUDA）

| 指标 | 数值 |
|------|------|
| 引擎启动时间 | ~15 秒（CUDA 内核加载） |
| 合成速度（28 字日语） | ~2 秒 |
| VRAM 占用 | +550 MB（模型加载后） |
| 引擎变体 | NVIDIA CUDA（非 DirectML） |

---

## API 快速测试

服务启动后，可通过 curl 直接测试（不经过 Web UI）：

```powershell
# 健康检查
curl http://127.0.0.1:3010/health

# 合成（speaker=3 是 VOICEVOX 默认说话人「四国めたん / ノーマル」）
curl -X POST http://127.0.0.1:3010/tts `
  -H "Content-Type: application/json" `
  -d '{\"text\":\"こんにちは\",\"speaker\":3}'
# → 返回 {"message":"ok", "audioUrl":"/outputs/XXXXX.wav", ...}

# 下载生成的音频
curl -o test.wav http://127.0.0.1:3010/outputs/<filename>.wav
```

可用的 speaker ID 通过 `GET /speakers` 查询，或在 Web UI 中查看。

---

## 架构说明

```
Browser (端口 3010)
    ↓
Node.js Express (server.js, 端口 3010)
    ├─ GET  /health          健康检查
    ├─ GET  /speakers        说话人列表（代理 VOICEVOX）
    ├─ GET  /speaker-info    肖像图片（代理 VOICEVOX）
    ├─ POST /tts             同步合成
    └─ POST /tts/stream      SSE 流式合成
    ↓ HTTP 调用
VOICEVOX Engine (run.exe, 端口 50021, NVIDIA CUDA 加速)
    ├─ POST /audio_query     文本 → 合成参数
    ├─ POST /synthesis       合成参数 → WAV 音频
    ├─ GET  /speakers        说话人元数据
    └─ GET  /version         引擎版本
```

### 长文本处理

- 文本 ≤ 500 字：一次合成
- 文本 > 500 字：按「、」分段，每段 ≤ 360 字，分别合成后用 `ffmpeg -f concat` 合并

---

## GPU 加速验证

启动后访问 `http://127.0.0.1:3010` 生成一段音频，同时监控 GPU 占用：

```powershell
nvidia-smi
```

实测合成时 `run.exe` 进程占用约 **500-700 MB VRAM**（模型加载后稳定）。
在 `start.ps1` 的启动日志中确认以下关键行：

```
* CUDA (device_id=0): OK
CUDA (device_id=0)を利用します
```

如果看到 `CPUを利用します` 则表示未启用 GPU，检查是否正确下载了 nvidia 变体（非 cpu 版），以及 `$env:VOICEVOX_USE_GPU` 是否被误设为 `"false"`。

---

## 常见问题与对策

### 安装阶段

**Q: winget install 报 "Access is denied"**
在**普通用户** PowerShell 中运行，不要用管理员身份（winget 已知 bug）。
```powershell
winget install 7zip.7zip
# 或
scoop install 7zip
```

**Q: 提示"无法加载脚本，因为在此系统上禁止运行脚本"**
```powershell
Get-ExecutionPolicy -List
# 如果 LocalMachine 不是 RemoteSigned，执行：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Q: 7z 或 ffmpeg 安装后命令找不到**
重启 PowerShell 终端，或手动刷新 PATH：
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
```

### 下载阶段

**Q: 下载中断后想继续**
脚本支持断点续传：
- 已完成的分卷会跳过
- 下载中途失败的分卷，**脚本会自动删除不完整文件**，重新运行时从头下载该分卷
- 如遇到脚本意外终止（如强制关闭终端），需手动删除 `.engine_download/` 里最后一个**不完整**的分卷再重试

**Q: GitHub 下载速度慢**
可使用代理：
```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
.\scripts\download_engine.ps1
```

**Q: 下载的是最新版本？**
默认版本为 `0.25.1`，可通过环境变量指定：
```powershell
$env:VOICEVOX_ENGINE_VERSION = "0.25.1"; .\scripts\download_engine.ps1
```
版本列表：https://github.com/VOICEVOX/voicevox_engine/releases

### 运行阶段

**Q: 引擎启动 60 秒内未就绪**
首次启动 NVIDIA 版会加载 CUDA 模型，可能耗时较长。如果反复失败，先尝试 CPU 版确认逻辑：
```powershell
Remove-Item -Recurse -Force .\engine
$env:VOICEVOX_ENGINE_TYPE = "cpu"; .\scripts\download_engine.ps1
.\start.ps1
```

**Q: 长文本合成时报 ffmpeg 错误**
确认 ffmpeg 已正确安装并在 PATH 中：
```powershell
ffmpeg -version
```

**Q: 生成的音频为空或损坏**
通常是 VOICEVOX Engine 崩溃。查看 `run.exe` 进程是否还活着。NVIDIA 版引擎**自带 CUDA 运行时**（无需手动安装 CUDA Toolkit），但需要有较新的 NVIDIA 显卡驱动（驱动 >= 527 版，支持 CUDA 12.x）。

**Q: `.engine_download/` 目录无法删除（"Device or resource busy"）**
解压后脚本尝试清理临时下载文件时，偶尔因文件句柄残留而失败。不影响运行（已在 `.gitignore`），可重启系统后手动删除，或直接忽略。

---

## 目录结构

```
07_voicevox_windows/
├── .gitignore
├── package.json
├── server.js                    # Node.js Express 服务器（与 Mac 版基本一致）
├── readme.md                    # 本文件
├── start.ps1                    # Windows 启动脚本
├── public/
│   └── index.html               # Web UI（与 Mac 版完全一致）
├── scripts/
│   └── download_engine.ps1      # Windows 引擎下载脚本
├── engine/                      # 下载后生成（git ignored）
│   ├── run.exe                  # VOICEVOX Engine 可执行文件
│   └── ...                      # CUDA 运行时、模型等
└── outputs/                     # 合成音频输出（git ignored）
```
