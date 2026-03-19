# 03 IndexTTS comparison scaffold

这是一个用于和 [02_coqui-tts](../02_coqui-tts) 做主观效果对比的 **IndexTTS2** 骨架项目。

目标：

- 保持与 [02_coqui-tts/public/index.html](../02_coqui-tts/public/index.html) 类似的 UI 体验
- 继续使用 **Node.js + Python** 分层结构
- 通过独立目录隔离 IndexTTS2 的依赖与运行方式
- 在本机 `macOS + Apple Silicon MPS` 上优先尝试运行

> 这是一个**可启动的骨架**，不是已经完全下载好模型的成品。首次真正生成前，还需要下载 IndexTTS2 模型权重。

## 目录结构

```text
03_index-tts/
├─ package.json
├─ server.js
├─ start.sh
├─ scripts/
│  └─ download_model.sh
├─ public/
│  └─ index.html
├─ python_service/
│  ├─ app.py
│  ├─ requirements.txt
│  └─ vendor_infer.py
├─ uploads/
├─ outputs/
└─ vendor/
```

## 运行方式概览

这个项目分成两层：

1. **Node 层**

   - 提供 Web UI
   - 接收上传文件
   - 调用 Python 服务
2. **Python bridge 层**

   - 接收 Node 请求
   - 用 `ffmpeg` 把参考媒体转换成 `24kHz / mono / wav`
   - 通过 **官方 IndexTTS 仓库的 `uv` 环境** 调用 `IndexTTS2`

和 [02_coqui-tts](../02_coqui-tts) 不同的是：

- 03 不直接把 IndexTTS2 依赖塞进本项目 `.venv`
- 03 会在 `vendor/index-tts` 下维护 **官方仓库副本** 和它自己的 `uv` 环境

## 已确认的本机条件

当前这台 Mac 已确认：

- Apple M2
- 16 GB RAM
- `arm64`
- MPS 可用
- `uv` 已安装
- `git-lfs` 已安装
- `ffmpeg` 已安装

因此可以尝试本地体验 IndexTTS2，但性能和稳定性仍不保证优于 Linux + CUDA。

## 启动脚本

在 [03_index-tts](.) 目录执行：

```bash
bash ./start.sh
```

脚本会：

- 安装 Node 依赖
- 创建 bridge Python `.venv`
- 安装 bridge Python 依赖
- 自动克隆官方仓库到 `vendor/index-tts`
- 自动执行 `uv sync`
- 启动 Python bridge 和 Node Web 服务

为避免官方仓库中的示例媒体触发 Git LFS 配额问题，启动脚本默认会使用 `GIT_LFS_SKIP_SMUDGE=1` 方式克隆仓库源码；真正需要的大模型权重由 [03_index-tts/scripts/download_model.sh](03_index-tts/scripts/download_model.sh) 单独下载。

默认端口：

- Node UI: `3008`
- Python bridge: `5012`

访问地址：

```text
http://127.0.0.1:3008/
```

## 下载模型

IndexTTS2 真正推理前，需要下载模型权重。

执行：

```bash
bash ./scripts/download_model.sh
```

它会按官方建议使用 Hugging Face CLI 下载：

- 仓库：`IndexTeam/IndexTTS-2`
- 目标目录：`vendor/index-tts/checkpoints`

如果访问 Hugging Face 较慢，可先设置镜像：

```bash
export HF_ENDPOINT="https://hf-mirror.com"
```

然后再执行下载脚本。

## 主要环境变量

### Node / bridge

- `PORT`: Node 端口，默认 `3008`
- `PYTHON_SERVICE_PORT`: Python bridge 端口，默认 `5012`
- `PYTHON_BIN`: bridge `.venv` 创建时使用的 Python，默认 `python3`

### IndexTTS vendor

- `INDEX_TTS_VENDOR_DIR`: 官方仓库目录，默认 `vendor/index-tts`
- `INDEX_TTS_MODEL_DIR`: 模型目录，默认 `vendor/index-tts/checkpoints`
- `INDEX_TTS_CFG_PATH`: 配置文件，默认 `vendor/index-tts/checkpoints/config.yaml`
- `INDEX_TTS_DEVICE`: `auto` / `mps` / `cpu` / `cuda:0`
- `INDEX_TTS_USE_FP16`: 默认 `false`
- `INDEX_TTS_USE_CUDA_KERNEL`: 默认 `false`
- `INDEX_TTS_USE_DEEPSPEED`: 默认 `false`

对当前 Mac，建议先这样：

```bash
INDEX_TTS_DEVICE=mps bash ./start.sh
```

如果 MPS 不稳定，再退回：

```bash
INDEX_TTS_DEVICE=cpu bash ./start.sh
```

## API 约定

### `GET /health`

返回 Node + Python bridge 的健康状态，以及 IndexTTS vendor 目录/模型文件是否齐全。

### `POST /tts`

`multipart/form-data` 参数：

- `text`: 要合成的文本
- `language`: 用于对比记录的语言代码
- `speaker`: 参考音频或视频
- `emotion_speaker`: 可选，情感参考音频或视频
- `emo_alpha`: 可选，默认建议 `0.6`
- `use_emo_text`: 可选，是否启用文本情感引导
- `emo_text`: 可选，情感描述文本
- `use_random`: 可选，是否启用随机情感采样

## 与 02_coqui-tts 的主要差异

- [02_coqui-tts](../02_coqui-tts) 使用 Coqui XTTS
- 03 使用 **IndexTTS2** 官方仓库
- 02 当前对上传素材统一转为 `16kHz`
- 03 当前按 IndexTTS2 需求转为 `24kHz`
- 02 的 `language` 直接传入 XTTS
- 03 的 `language` 主要保留为比较用途，IndexTTS2 更依赖文本本身

## 当前状态说明

本骨架已完成：

- 独立目录与运行入口
- Node Web 服务
- Python bridge 服务
- 与 02 类似的前端页面
- 对官方仓库与模型文件的健康检查
- 通过 `uv run` 调用 `IndexTTS2` 的推理包装脚本

尚未保证：

- IndexTTS2 在当前 Mac 上一定稳定运行
- MPS 模式一定比 CPU 更快或更稳
- 情感控制参数一定符合你最终主观偏好

## 下一步建议

你可以继续让我做：

1. 真正启动 03 并验证 `/health`
2. 下载官方模型并做第一次推理
3. 再做一个统一比较页，把 02 和 03 放到同一个页面里 A/B 播放
