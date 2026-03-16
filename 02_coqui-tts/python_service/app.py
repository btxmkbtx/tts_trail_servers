from __future__ import annotations

import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from flask import Flask, jsonify, request
from TTS.api import TTS

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = (BASE_DIR / "uploads").resolve()
NORMALIZED_DIR = (UPLOAD_DIR / "normalized").resolve()
OUTPUT_DIR = (BASE_DIR / "outputs").resolve()
MODEL_NAME = os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
DEVICE = os.getenv("XTTS_DEVICE", "cpu")

app = Flask(__name__)

_tts = None
_tts_lock = threading.Lock()


for directory in (UPLOAD_DIR, NORMALIZED_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def is_within(directory: Path, target: Path) -> bool:
    try:
        target.relative_to(directory)
        return True
    except ValueError:
        return False


def load_tts() -> TTS:
    global _tts
    if _tts is None:
        with _tts_lock:
            if _tts is None:
                _tts = TTS(MODEL_NAME).to(DEVICE)
    return _tts


def normalize_audio(source_path: Path) -> Path:
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
        "16000",
        "-map_metadata",
        "-1",
        str(normalized_path),
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg conversion failed")

    return normalized_path


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "model": MODEL_NAME,
            "device": DEVICE,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "loaded": _tts is not None,
        }
    )


@app.post("/synthesize")
def synthesize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    language = (data.get("language") or "ja").strip()
    speaker_wav_path = data.get("speaker_wav_path")
    output_path = data.get("output_path")

    if not text:
        return jsonify({"error": "text is required"}), 400

    if not speaker_wav_path:
        return jsonify({"error": "speaker_wav_path is required"}), 400

    if not output_path:
        return jsonify({"error": "output_path is required"}), 400

    speaker_path = Path(speaker_wav_path).resolve()
    destination = Path(output_path).resolve()

    if not is_within(UPLOAD_DIR, speaker_path):
        return jsonify({"error": "speaker_wav_path must be inside uploads/"}), 400

    if not is_within(OUTPUT_DIR, destination):
        return jsonify({"error": "output_path must be inside outputs/"}), 400

    if not speaker_path.exists():
        return jsonify({"error": "speaker_wav_path does not exist"}), 400

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        normalized_speaker_path = normalize_audio(speaker_path)
        tts = load_tts()
        tts.tts_to_file(
            text=text,
            speaker_wav=str(normalized_speaker_path),
            language=language,
            file_path=str(destination),
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "error": "xtts synthesis failed",
                    "detail": str(exc),
                }
            ),
            500,
        )

    return jsonify(
        {
            "message": "ok",
            "model": MODEL_NAME,
            "normalized_speaker_path": str(normalized_speaker_path),
            "output_path": str(destination),
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
