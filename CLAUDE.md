# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码仓库中工作时提供指导。

## 概览

本仓库包含三个独立的 TTS（文本转语音）服务器实现，用于本地声音克隆的研究与对比，目标运行环境为 Apple Silicon（M2，16 GB 内存）。

| 项目 | 模型 | 端口 | 声音克隆 |
|------|------|------|---------|
| `01_edge-tts-server` | Microsoft Edge TTS（云端） | 3006 | 否 |
| `02_coqui-tts` | Coqui XTTS v2（本地） | 3007 + 5001 | 是（16 kHz） |
| `03_index-tts` | IndexTTS2（本地） | 3008 + 5012 | 是（24 kHz + 情感控制） |

## 系统依赖

```bash
brew install node python ffmpeg git git-lfs uv
```

- Node.js 18+、Python 3.10–3.11、ffmpeg、git-lfs、uv

## 各项目启动方式

### 01_edge-tts-server（云端 TTS）
```bash
cd 01_edge-tts-server
npm install
node edge-tts-server.js
```

### 02_coqui-tts（本地声音克隆）
```bash
cd 02_coqui-tts
bash ./start.sh              # 自动创建 venv、安装依赖、启动两个服务
# 或指定 Python 版本：
PYTHON_BIN=python3.11 bash ./start.sh
```
脚本同时启动 Node.js（端口 3007）和 Flask（端口 5001）。Web 界面：`http://127.0.0.1:3007`

### 03_index-tts（带情感控制的高级声音克隆）
```bash
cd 03_index-tts
bash ./start.sh              # 克隆 vendor 仓库、配置 uv、启动两个服务
bash ./scripts/download_model.sh   # 下载模型权重（首次启动后运行）
# 指定推理设备：
INDEX_TTS_DEVICE=mps bash ./start.sh
```
Web 界面：`http://127.0.0.1:3008`

## 架构说明

### 02_coqui-tts — 双层架构（Node.js + Python）

- **Node.js**（`server.js`，端口 3007）：提供 Web UI，处理文件上传（multer），将 TTS 请求代理到 Flask
- **Flask**（`python_service/app.py`，端口 5001）：加载 Coqui XTTS 模型，通过 ffmpeg 将音频规格化（16 kHz 单声道 WAV），用 `registry.json` 管理声音注册表
- 声音注册表将 `voice_id`（UUID）映射到说话人音频路径，支持复用声音而无需重复上传
- 模型在首次合成请求时懒加载，首次使用时自动从 Coqui 下载

### 03_index-tts — 桥接模式（Node.js + Python 桥接层 + uv 子进程）

- **Node.js**（`server.js`，端口 3008）：提供 UI，处理含情感参数的文件上传
- **Python 桥接层**（`python_service/app.py`，端口 5012）：不直接导入 IndexTTS2；将音频规格化到 24 kHz 后，在 `vendor/index-tts/` 目录中以子进程方式运行 `uv run python vendor_infer.py` 完成合成
- **vendor_infer.py**：薄封装层，实例化 vendor 仓库中的 `IndexTTS2` 并执行推理
- 桥接模式将 vendor 的依赖环境（由 `uv` 管理）与桥接层自身的 venv 完全隔离

**核心架构差异**：02 将 TTS 直接安装进自身 venv；03 通过子进程桥接，使 vendor 的 `uv` 环境完全独立。

## 主要 API 接口

### 02_coqui-tts
- `POST /tts` — multipart 表单：`text`、`language`、`speaker`（文件）或 `voice_id`
- `POST /voices/register` — 注册声音（不触发合成）
- `GET /voices` — 列出已注册的声音 ID
- `GET /health` — Node + Python 服务状态

### 03_index-tts
- `POST /tts` — multipart 表单：`text`、`speaker`（文件），可选 `emotion_speaker`、`emo_alpha`、`emo_text`、`use_emo_text`
- `GET /health` — 详细状态：uv、ffmpeg、vendor 仓库、模型文件、推理设备

### 01_edge-tts-server
- `POST /tts` — JSON 请求体 `{ "text": "..." }`，返回音频 URL

## 环境变量

### 02_coqui-tts
- `XTTS_MODEL` — 模型名称（默认：`tts_models/multilingual/multi-dataset/xtts_v2`）
- `XTTS_DEVICE` — `cpu` 或 `cuda`（默认：`cpu`）

### 03_index-tts
- `INDEX_TTS_DEVICE` — `auto`/`mps`/`cpu`/`cuda:0`（默认：`auto`）
- `INDEX_TTS_VENDOR_DIR` — IndexTTS 仓库克隆路径（默认：`vendor/index-tts`）
- `INDEX_TTS_MODEL_DIR` — 模型 checkpoints 目录
- `INDEX_TTS_USE_FP16`、`INDEX_TTS_USE_CUDA_KERNEL`、`INDEX_TTS_USE_DEEPSPEED` — CUDA 优化选项（默认：false）
- `HF_ENDPOINT` — 覆盖 Hugging Face 下载地址（如 `https://hf-mirror.com`）
- `PORT`、`PYTHON_SERVICE_PORT` — 覆盖默认端口
