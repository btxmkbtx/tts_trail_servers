# 03_index-tts_windows

IndexTTS2 本地声音克隆服务器 —— Windows 11 版本。

基于 `03_index-tts_mac` 改造，适配 Windows 11 + NVIDIA GPU 环境。

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
| 模型下载 | `scripts/download_model.sh` | `scripts/download_model.ps1` |
| venv 激活路径 | `.venv/bin/activate` | `.venv\Scripts\Activate.ps1` |
| Python 命令 | `python3` | `python` |
| 推理设备 | MPS（Apple Silicon） | `cuda:0`（RTX 3070 Ti） |
| FP16 加速 | 关闭 | 开启（节省显存、加速推理） |
| CUDA Kernel | 不适用 | 关闭（避免 Windows MSVC 编译问题） |

`server.js` 和 `python_service/vendor_infer.py` 无需修改，代码已跨平台。`python_service/app.py` 修复了 `PYTHONPATH` 分隔符（Windows 用 `;`，Mac/Linux 用 `:`，统一改为 `os.pathsep`）。

---

## 前置依赖

### 已需要安装的工具

```powershell
# 在管理员 PowerShell 中执行
winget install astral-sh.uv   # Python 包管理器
winget install ffmpeg          # 音频处理
```

安装后**重启终端**使 PATH 生效，验证：

```powershell
uv --version
ffmpeg -version
```

### 已满足的依赖

- Python 3.12.10 ✅
- Node.js v22.14.0 ✅
- npm 11.6.1 ✅
- git-lfs 3.0.2 ✅

### PowerShell 执行策略（首次需要设置）

```powershell
#验证当前策略
#如果 CurrentUser 已经是 RemoteSigned 或 Unrestricted，就不需要再改了。
Get-ExecutionPolicy -List

#否则执行下面的命令
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## 启动服务

```powershell
cd 03_index-tts_windows

# 标准启动（自动使用 cuda:0 + FP16）
.\start.ps1

# 或通过 npm
npm run start:all
```

### 可选环境变量

```powershell
# 指定推理设备（默认 cuda:0）
$env:INDEX_TTS_DEVICE = "cuda:0"   # RTX 3070 Ti 推荐
$env:INDEX_TTS_DEVICE = "cpu"      # 无 GPU 时降级

# FP16 加速（RTX 3070 Ti 建议开启，节省约一半显存）
$env:INDEX_TTS_USE_FP16 = "true"

# 端口覆盖
$env:PORT = "3008"
$env:PYTHON_SERVICE_PORT = "5012"

# 启动示例
$env:INDEX_TTS_DEVICE = "cuda:0"; $env:INDEX_TTS_USE_FP16 = "true"; .\start.ps1
```

Web 界面：`http://127.0.0.1:3008`

---

## 下载模型权重

首次启动后，运行：

```powershell
.\scripts\download_model.ps1

# 国内网络使用镜像
$env:HF_ENDPOINT = "https://hf-mirror.com"; .\scripts\download_model.ps1

# 或通过 npm
npm run download:model
```

模型默认下载到 `./vendor/index-tts/checkpoints/`，约 10-15 GB。

---

## 架构说明

```
Node.js (端口 3008)          ← Web UI、文件上传
    ↓ HTTP 代理
Python bridge (端口 5012)    ← Flask，音频规格化（24 kHz）
    ↓ subprocess (uv run)
vendor/index-tts/            ← IndexTTS2，独立 uv 环境，GPU 推理
```

- **桥接模式**：vendor 依赖与 bridge 自身 venv 完全隔离
- **音频规格化**：ffmpeg 将上传音频统一转为 24 kHz 单声道 WAV
- **GPU 推理**：`vendor_infer.py` 自动检测 CUDA，RTX 3070 Ti 约 4-5 GB 显存占用（FP16 模式）

---

## 验证

```powershell
# 检查服务健康状态
curl http://127.0.0.1:3008/health

# 监控 GPU 显存（推理时）
nvidia-smi
```

health 接口正常返回示例：
```json
{
  "node": "ok",
  "python": "ok",
  "device": "cuda:0",
  "ffmpeg": true,
  "vendor_repo": true,
  "model_files": true
}
```

---

## 常见问题与对策

### 安装阶段

**Q: winget install ffmpeg 报 "Access is denied"**
原因：在管理员 PowerShell 中运行 winget，反而导致写入用户目录失败（winget 已知 bug）。
```powershell
# 改用普通用户 PowerShell（不要右键"以管理员身份运行"）重新运行
winget install ffmpeg

# 或改用 Scoop
irm get.scoop.sh | iex
scoop install ffmpeg
```

**Q: PowerShell 提示"无法加载脚本，因为在此系统上禁止运行脚本"**
```powershell
# 先确认当前策略
Get-ExecutionPolicy -List
# 如果 LocalMachine 已是 RemoteSigned，无需任何操作
# 否则执行：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Q: uv 或 ffmpeg 安装后找不到命令**
重启 PowerShell 终端，或手动刷新 PATH：
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
```

---

### 运行阶段

**Q: POST /synthesize/stream 返回 500，控制台显示 "Missing model files"**
模型尚未下载，需单独执行一次：
```powershell
.\scripts\download_model.ps1
```
模型约 10-15 GB，下载完成后无需再次执行。

**Q: `hf_hub_download` 报 LocalEntryNotFoundError（无法连接 Hugging Face）**
IndexTTS2 初始化时会自动下载 `amphion/MaskGCT` 模型（不在 download_model.ps1 范围内）。
先清除损坏的缓存，再重新启动让其自动下载：
```powershell
Remove-Item -Recurse -Force "C:\Users\Zhupeng\.cache\huggingface\hub\models--amphion--MaskGCT"
.\start.ps1
```
国内网络可加镜像：
```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"; .\start.ps1
```

**Q: UnicodeDecodeError: 'cp932' codec（日语/中文 Windows 编码问题）**
原因：Windows 系统区域为日语时默认编码为 cp932，无法解码 UTF-8 输出。
已在 `app.py` 的所有 `subprocess.Popen` 和 `subprocess.run` 调用中添加 `encoding="utf-8"`，以及设置 `PYTHONUTF8=1` 修复。无需手动操作。

**Q: OSError: os error 1455（页面文件太小）**
原因：Windows 内存映射（safetensors mmap）需要页面文件作为虚拟地址担保，页面文件不足时报此错。
解决：`Win+R` → `sysdm.cpl` → 高级 → 性能 → 虚拟内存 → 将页面文件设置在剩余空间充裕的盘（如 D 盘），选择"系统管理的大小" → 重启电脑。

**Q: 推理极慢（约 9 秒/迭代），nvidia-smi 显示 GPU 占用为 0%**
原因：未指定 CUDA 设备，模型跑在 CPU 上。
已在 `start.ps1` 中内置默认值，直接 `.\start.ps1` 即自动使用 `cuda:0 + FP16`。
验证 CUDA 是否可用：
```powershell
cd vendor\index-tts
uv run python -c "import torch; print(torch.cuda.is_available())"
# 应返回 True
```

**Q: Python 3.12 与 IndexTTS2 有兼容性问题**
通过 uv 安装 Python 3.11：
```powershell
uv python install 3.11
$env:PYTHON_BIN = "python3.11"; .\start.ps1
```

**Q: CUDA 推理报错，需要回退到 CPU 调试**
```powershell
$env:INDEX_TTS_DEVICE = "cpu"; $env:INDEX_TTS_USE_FP16 = "false"; .\start.ps1
```

---

### 可忽略的警告

以下警告不影响运行，无需处理：

| 警告内容 | 说明 |
|----------|------|
| `GPT2InferenceModel has generative capabilities...` | transformers 未来版本的弃用提示，需 IndexTTS 官方修复 |
| `Passing a tuple of past_key_values is deprecated...` | 同上，v4.53 才会失效 |
| `hf_xet package is not installed...` | 可选的下载加速包，模型已下载后无意义 |
| `This is a development server...` | Flask 开发模式提示，本地使用无需生产部署 |
