# Local XTTS sample (Node + Python)

这是一个**最小可运行**的本地声音克隆示例：

- **Node.js**：提供上传接口
- **Python + Coqui XTTS**：根据参考音频合成语音
- **ffmpeg**：把任意上传音频统一转换成 `16kHz / mono / wav`
- **最小前端页面**：浏览器直接上传文本和参考音频
- **输出目录**：`outputs/`

> 注意：这个示例依赖开源 TTS 模型。请只使用**你本人或已明确授权**的声音样本。

## 目录结构

```text
02_mytts/
├─ package.json
├─ server.js
├─ start.sh
├─ public/
│  └─ index.html
├─ uploads/
├─ outputs/
└─ python_service/
   ├─ app.py
   └─ requirements.txt
```

## 先决条件

- Node.js **18+**
- Python **3.10 ~ 3.11**（建议）
- `ffmpeg`（很多音频处理链路会用到，建议提前安装）

macOS 可先安装：

```bash
brew install ffmpeg
```

## 1. 安装 Node 依赖

在 `02_mytts` 目录执行：

```bash
npm install
```

## 2. 创建 Python 虚拟环境并安装依赖

如果以前创建过，最稳妥的方式是删除 `.venv` 后重建：

```bash
rm -rf .venv
```

开始创建

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r python_service/requirements.txt
```

当前示例已固定兼容版本：

- `TTS==0.22.0`
- `torch==2.5.1`
- `torchaudio==2.5.1`
- `transformers==4.41.2`

这样可以避免 `cannot import name 'BeamSearchScorer' from 'transformers'` 这类 5.x 版本兼容问题。
同时也能避免较新的 `torch` 在加载 XTTS checkpoint 时触发 `weights_only` 默认行为变更导致的加载失败。

> 第一次真正合成时，XTTS 模型会自动下载，耗时会比较久。

如果 `TTS` 安装时遇到 `torch` 相关问题，建议直接安装项目里固定的兼容版本，再重新执行：

```bash
pip install torch==2.5.1 torchaudio==2.5.1
pip install -r python_service/requirements.txt
```

如果你之前已经装过错误版本的 `transformers` 或 `torch`，建议在激活 `.venv` 后执行一次：

```bash
pip uninstall -y torch torchaudio transformers
pip install -r python_service/requirements.txt
```

## 3. 启动 Python XTTS 服务

```bash
source .venv/bin/activate
python python_service/app.py
```

默认监听：`http://127.0.0.1:5001`

可选环境变量：

- `XTTS_MODEL`：默认 `tts_models/multilingual/multi-dataset/xtts_v2`
- `XTTS_DEVICE`：默认 `cpu`

例如：

```bash
XTTS_DEVICE=cpu python python_service/app.py
```

## 4. 启动 Node API

另开一个终端，在 `02_mytts` 目录执行：

```bash
npm start
```

默认监听：`http://127.0.0.1:3007`

## 3+4 一键启动

如果你希望自动检查依赖并同时启动 Node + Python，可直接执行：

```bash
bash ./start.sh
```

或者：

```bash
npm run start:all
```

如果你想指定虚拟环境使用的 Python 版本，可以在启动前传入 `PYTHON_BIN`：

```bash
PYTHON_BIN=python3.11 bash ./start.sh
```

或者：

```bash
PYTHON_BIN=python3.11 npm run start:all
```

脚本会：

- 自动创建 `.venv`（如果不存在）
- 自动安装 Python 依赖（首次）
- 自动安装 Node 依赖（首次）
- 同时启动 Python XTTS 服务和 Node Web 服务

注意：

- `PYTHON_BIN` 只在**首次创建** `.venv` 时决定虚拟环境绑定的 Python 版本。
- 如果 `.venv` 已存在，脚本会继续复用当前环境。
- 想切换版本时，先删除 `.venv` 再重新执行启动命令。

## 5. 发送测试请求（voice_id 可复用）

准备一个**干净的参考人声**，例如 `sample.wav`：

- 建议 6~15 秒
- 背景噪音尽量少
- 单人说话
- 与目标语言尽量接近

首次上传参考音频（会自动生成 `voice_id`）：

```bash
curl -X POST http://127.0.0.1:3007/tts \
  -F 'text=こんにちは、これはローカルXTTSのテストです。' \
  -F 'language=ja' \
  -F 'speaker=@./sample.wav'
```

返回示例：

```json
{
  "message": "ok",
  "audioUrl": "/outputs/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.wav",
  "voiceId": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
  "voiceSource": "new",
  "speakerSample": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.wav",
  "language": "ja",
  "model": "tts_models/multilingual/multi-dataset/xtts_v2"
}
```

后续可直接复用 `voice_id`（无需再次上传音频）：

```bash
curl -X POST http://127.0.0.1:3007/tts \
  -F 'text=こんにちは、これはvoice_id再利用のテストです。' \
  -F 'language=ja' \
  -F 'voice_id=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy'
```

浏览器打开返回的地址即可试听，例如：

```text
http://127.0.0.1:3007/outputs/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.wav
```

## 6. 使用前端页面

启动后直接访问：

```text
http://127.0.0.1:3007/
```

页面支持：

- 输入要合成的文本
- 选择语言代码
- 从下拉框选择已保存的 `voice_id`
- 或上传新的参考音频（自动生成新的 `voice_id`）
- 自动提交到后端
- 返回后直接试听生成结果

## API 说明

### `GET /health`

检查 Node 和 Python 服务状态。

### `POST /tts`

`multipart/form-data` 参数：

- `text`: 要合成的文本
- `language`: 语言代码，例如 `ja`、`en`、`zh-cn`
- `voice_id`: 已保存声音 ID（可选）
- `speaker`: 参考音频文件（可选，传入后会先转成 `16kHz/mono wav` 并生成/更新 voice）

> `voice_id` 与 `speaker` 至少提供一个。

### `GET /voices`

获取已保存的 `voice_id` 列表（供前端下拉框使用）。

### `POST /voices/register`

仅注册声音，不做合成。`multipart/form-data` 参数：

- `speaker`: 参考音频文件（必填）
- `voice_id`: 自定义 ID（可选，不传则自动生成）

## 说明与限制

- 这是**最小示例**，未做鉴权、限流、队列、自动清理。
- CPU 可运行，但速度会比较慢。
- 第一次推理通常最慢，因为要加载模型。
- 声音克隆效果强依赖参考音频质量。
- 上传音频会先经过 `ffmpeg` 标准化处理。
- 某些环境下 `TTS`/`torch` 安装会因平台而需要额外调整。

## 下一步可扩展

你后续可以继续加：

1. 自动删除旧音频
2. 多说话人样本管理
3. 输出 MP3
4. 把 Node 和 Python 合并成 Docker 部署
