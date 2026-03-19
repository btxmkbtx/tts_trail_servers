from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import json
import re

from flask import Flask, Response, jsonify, request, stream_with_context

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = (BASE_DIR / "uploads").resolve()
NORMALIZED_DIR = (UPLOAD_DIR / "normalized").resolve()
OUTPUT_DIR = (BASE_DIR / "outputs").resolve()
VENDOR_DIR = Path(os.getenv("INDEX_TTS_VENDOR_DIR", BASE_DIR / "vendor" / "index-tts")).resolve()
CFG_PATH = Path(os.getenv("INDEX_TTS_CFG_PATH", VENDOR_DIR / "checkpoints" / "config.yaml")).resolve()
MODEL_DIR = Path(os.getenv("INDEX_TTS_MODEL_DIR", VENDOR_DIR / "checkpoints")).resolve()
UV_BIN = os.getenv("UV_BIN", "uv")
INDEX_TTS_DEVICE = os.getenv("INDEX_TTS_DEVICE", "auto")
INDEX_TTS_USE_FP16 = os.getenv("INDEX_TTS_USE_FP16", "false").lower() in {"1", "true", "yes", "on"}
INDEX_TTS_USE_CUDA_KERNEL = os.getenv("INDEX_TTS_USE_CUDA_KERNEL", "false").lower() in {"1", "true", "yes", "on"}
INDEX_TTS_USE_DEEPSPEED = os.getenv("INDEX_TTS_USE_DEEPSPEED", "false").lower() in {"1", "true", "yes", "on"}
PYTHON_SERVICE_PORT = int(os.getenv("PYTHON_SERVICE_PORT", "5012"))
REQUIRED_MODEL_FILES = [
    "bpe.model",
    "gpt.pth",
    "config.yaml",
    "s2mel.pth",
    "wav2vec2bert_stats.pt",
]

app = Flask(__name__)

for directory in (UPLOAD_DIR, NORMALIZED_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def is_within(directory: Path, target: Path) -> bool:
    try:
        target.relative_to(directory)
        return True
    except ValueError:
        return False


def normalize_media(source_path: Path) -> Path:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg is required but was not found in PATH")

    normalized_path = NORMALIZED_DIR / f"{uuid.uuid4()}.wav"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-map_metadata",
        "-1",
        str(normalized_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg conversion failed")
    return normalized_path


def missing_model_files() -> list[str]:
    missing: list[str] = []
    for file_name in REQUIRED_MODEL_FILES:
        if not (MODEL_DIR / file_name).exists():
            missing.append(file_name)
    return missing


@app.get("/health")
def health():
    return jsonify(
        {
            "ready": shutil.which(UV_BIN) is not None and VENDOR_DIR.exists() and CFG_PATH.exists() and not missing_model_files(),
            "runtime": "IndexTTS2",
            "uv": shutil.which(UV_BIN) is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "vendor_dir": str(VENDOR_DIR),
            "vendor_exists": VENDOR_DIR.exists(),
            "cfg_path": str(CFG_PATH),
            "cfg_exists": CFG_PATH.exists(),
            "model_dir": str(MODEL_DIR),
            "missing_model_files": missing_model_files(),
            "device_hint": INDEX_TTS_DEVICE,
        }
    )


@app.post("/synthesize")
def synthesize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    speaker_wav_path = data.get("speaker_wav_path")
    emo_audio_prompt_path = data.get("emo_audio_prompt_path")
    output_path = data.get("output_path")
    emo_text = (data.get("emo_text") or "").strip() or None
    use_emo_text = bool(data.get("use_emo_text", False))
    use_random = bool(data.get("use_random", False))
    emo_alpha = float(data.get("emo_alpha") or 1.0)

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not speaker_wav_path:
        return jsonify({"error": "speaker_wav_path is required"}), 400
    if not output_path:
        return jsonify({"error": "output_path is required"}), 400
    if shutil.which(UV_BIN) is None:
        return jsonify({"error": f"{UV_BIN} is not available"}), 500
    if not VENDOR_DIR.exists():
        return jsonify({"error": "IndexTTS vendor repository is missing"}), 500
    if missing_model_files():
        return jsonify({
            "error": "IndexTTS model files are missing",
            "missing_model_files": missing_model_files(),
        }), 500

    speaker_path = Path(speaker_wav_path).resolve()
    destination = Path(output_path).resolve()

    if not is_within(UPLOAD_DIR, speaker_path):
        return jsonify({"error": "speaker_wav_path must be inside uploads/"}), 400
    if not is_within(OUTPUT_DIR, destination):
        return jsonify({"error": "output_path must be inside outputs/"}), 400
    if not speaker_path.exists():
        return jsonify({"error": "speaker_wav_path does not exist"}), 400

    normalized_speaker_path = normalize_media(speaker_path)
    normalized_emo_audio_path = None

    if emo_audio_prompt_path:
        emo_path = Path(emo_audio_prompt_path).resolve()
        if not is_within(UPLOAD_DIR, emo_path):
            return jsonify({"error": "emo_audio_prompt_path must be inside uploads/"}), 400
        if not emo_path.exists():
            return jsonify({"error": "emo_audio_prompt_path does not exist"}), 400
        normalized_emo_audio_path = normalize_media(emo_path)

    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        UV_BIN,
        "run",
        "python",
        str((Path(__file__).resolve().parent / "vendor_infer.py").resolve()),
        "--vendor-dir",
        str(VENDOR_DIR),
        "--cfg-path",
        str(CFG_PATH),
        "--model-dir",
        str(MODEL_DIR),
        "--speaker",
        str(normalized_speaker_path),
        "--text",
        text,
        "--output",
        str(destination),
        "--device",
        INDEX_TTS_DEVICE,
        "--emo-alpha",
        str(emo_alpha),
    ]

    if normalized_emo_audio_path is not None:
        command.extend(["--emo-audio", str(normalized_emo_audio_path)])
    if use_emo_text:
        command.append("--use-emo-text")
    if emo_text:
        command.extend(["--emo-text", emo_text])
    if use_random:
        command.append("--use-random")
    if INDEX_TTS_USE_FP16:
        command.append("--use-fp16")
    if INDEX_TTS_USE_CUDA_KERNEL:
        command.append("--use-cuda-kernel")
    if INDEX_TTS_USE_DEEPSPEED:
        command.append("--use-deepspeed")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{VENDOR_DIR}:{env.get('PYTHONPATH', '')}" if env.get("PYTHONPATH") else str(VENDOR_DIR)

    proc = subprocess.Popen(
        command,
        cwd=VENDOR_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_lines: list[str] = []

    def _stream_stderr() -> None:
        for line in proc.stderr:
            print(line, end="", file=sys.stderr, flush=True)
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_stream_stderr, daemon=True)
    stderr_thread.start()

    stdout_data = proc.stdout.read()
    proc.wait()
    stderr_thread.join()

    stderr_data = "".join(stderr_lines)
    returncode = proc.returncode

    if returncode != 0:
        print("[IndexTTS] inference failed (returncode={})".format(returncode))
        if stderr_data.strip():
            print("[IndexTTS] stderr:\n{}".format(stderr_data.strip()))
        if stdout_data.strip():
            print("[IndexTTS] stdout:\n{}".format(stdout_data.strip()))
        return (
            jsonify(
                {
                    "error": "IndexTTS inference failed",
                    "detail": stderr_data.strip() or stdout_data.strip() or "Unknown error",
                    "stdout": stdout_data,
                    "stderr": stderr_data,
                }
            ),
            500,
        )

    runtime = "IndexTTS2"
    device = INDEX_TTS_DEVICE
    for line in stdout_data.splitlines():
        if line.startswith("RUNTIME="):
            runtime = line.split("=", 1)[1].strip() or runtime
        if line.startswith("DEVICE="):
            device = line.split("=", 1)[1].strip() or device

    return jsonify(
        {
            "message": "ok",
            "model": "IndexTeam/IndexTTS-2",
            "runtime": runtime,
            "device": device,
            "normalized_speaker_path": str(normalized_speaker_path),
            "normalized_emo_audio_path": str(normalized_emo_audio_path) if normalized_emo_audio_path else None,
            "output_path": str(destination),
        }
    )


@app.post("/synthesize/stream")
def synthesize_stream():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    speaker_wav_path = data.get("speaker_wav_path")
    emo_audio_prompt_path = data.get("emo_audio_prompt_path")
    output_path = data.get("output_path")
    emo_text = (data.get("emo_text") or "").strip() or None
    use_emo_text = bool(data.get("use_emo_text", False))
    use_random = bool(data.get("use_random", False))
    emo_alpha = float(data.get("emo_alpha") or 1.0)

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not speaker_wav_path:
        return jsonify({"error": "speaker_wav_path is required"}), 400
    if not output_path:
        return jsonify({"error": "output_path is required"}), 400
    if shutil.which(UV_BIN) is None:
        return jsonify({"error": f"{UV_BIN} is not available"}), 500
    if not VENDOR_DIR.exists():
        return jsonify({"error": "IndexTTS vendor repository is missing"}), 500
    if missing_model_files():
        return jsonify({
            "error": "IndexTTS model files are missing",
            "missing_model_files": missing_model_files(),
        }), 500

    speaker_path = Path(speaker_wav_path).resolve()
    destination = Path(output_path).resolve()

    if not is_within(UPLOAD_DIR, speaker_path):
        return jsonify({"error": "speaker_wav_path must be inside uploads/"}), 400
    if not is_within(OUTPUT_DIR, destination):
        return jsonify({"error": "output_path must be inside outputs/"}), 400
    if not speaker_path.exists():
        return jsonify({"error": "speaker_wav_path does not exist"}), 400

    try:
        normalized_speaker_path = normalize_media(speaker_path)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    normalized_emo_audio_path = None
    if emo_audio_prompt_path:
        emo_path = Path(emo_audio_prompt_path).resolve()
        if not is_within(UPLOAD_DIR, emo_path):
            return jsonify({"error": "emo_audio_prompt_path must be inside uploads/"}), 400
        if not emo_path.exists():
            return jsonify({"error": "emo_audio_prompt_path does not exist"}), 400
        try:
            normalized_emo_audio_path = normalize_media(emo_path)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 500

    destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        UV_BIN, "run", "python",
        str((Path(__file__).resolve().parent / "vendor_infer.py").resolve()),
        "--vendor-dir", str(VENDOR_DIR),
        "--cfg-path", str(CFG_PATH),
        "--model-dir", str(MODEL_DIR),
        "--speaker", str(normalized_speaker_path),
        "--text", text,
        "--output", str(destination),
        "--device", INDEX_TTS_DEVICE,
        "--emo-alpha", str(emo_alpha),
    ]
    if normalized_emo_audio_path is not None:
        command.extend(["--emo-audio", str(normalized_emo_audio_path)])
    if use_emo_text:
        command.append("--use-emo-text")
    if emo_text:
        command.extend(["--emo-text", emo_text])
    if use_random:
        command.append("--use-random")
    if INDEX_TTS_USE_FP16:
        command.append("--use-fp16")
    if INDEX_TTS_USE_CUDA_KERNEL:
        command.append("--use-cuda-kernel")
    if INDEX_TTS_USE_DEEPSPEED:
        command.append("--use-deepspeed")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{VENDOR_DIR}:{env.get('PYTHONPATH', '')}" if env.get("PYTHONPATH") else str(VENDOR_DIR)

    def generate():
        proc = subprocess.Popen(
            command,
            cwd=VENDOR_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def _drain_stdout() -> None:
            for line in proc.stdout:
                stdout_lines.append(line)

        stdout_thread = threading.Thread(target=_drain_stdout, daemon=True)
        stdout_thread.start()

        for line in proc.stderr:
            print(line, end="", file=sys.stderr, flush=True)
            stderr_lines.append(line)
            m = re.match(r'\[PROGRESS\]\s+(\d+)%\s+(.*)', line.strip())
            if m:
                event = json.dumps({
                    "type": "progress",
                    "percent": int(m.group(1)),
                    "desc": m.group(2).strip(),
                })
                yield f"data: {event}\n\n"

        proc.wait()
        stdout_thread.join()

        stdout_data = "".join(stdout_lines)
        stderr_data = "".join(stderr_lines)
        returncode = proc.returncode

        if returncode != 0:
            print("[IndexTTS] inference failed (returncode={})".format(returncode))
            detail = stderr_data.strip() or stdout_data.strip() or "Unknown error"
            yield f"data: {json.dumps({'type': 'error', 'detail': detail})}\n\n"
            return

        runtime = "IndexTTS2"
        device = INDEX_TTS_DEVICE
        for line in stdout_data.splitlines():
            if line.startswith("RUNTIME="):
                runtime = line.split("=", 1)[1].strip() or runtime
            if line.startswith("DEVICE="):
                device = line.split("=", 1)[1].strip() or device

        yield f"data: {json.dumps({'type': 'done', 'output_path': str(destination), 'model': 'IndexTeam/IndexTTS-2', 'runtime': runtime, 'device': device})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PYTHON_SERVICE_PORT, debug=False, threaded=True)
