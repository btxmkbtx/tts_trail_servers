from __future__ import annotations

import os
import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from TTS.api import TTS

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = (BASE_DIR / "uploads").resolve()
NORMALIZED_DIR = (UPLOAD_DIR / "normalized").resolve()
OUTPUT_DIR = (BASE_DIR / "outputs").resolve()
VOICE_DIR = (UPLOAD_DIR / "voices").resolve()
VOICE_REGISTRY_PATH = (VOICE_DIR / "registry.json").resolve()
MODEL_NAME = os.getenv("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
DEVICE = os.getenv("XTTS_DEVICE", "cpu")

app = Flask(__name__)

_tts = None
_tts_lock = threading.Lock()
_voice_lock = threading.Lock()


for directory in (UPLOAD_DIR, NORMALIZED_DIR, OUTPUT_DIR, VOICE_DIR):
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


def read_voice_registry() -> dict[str, dict[str, str]]:
    if not VOICE_REGISTRY_PATH.exists():
        return {}

    try:
        with VOICE_REGISTRY_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass

    return {}


def write_voice_registry(registry: dict[str, dict[str, str]]) -> None:
    VOICE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with VOICE_REGISTRY_PATH.open("w", encoding="utf-8") as file:
        json.dump(registry, file, ensure_ascii=False, indent=2)


def create_or_update_voice(
    source_path: Path,
    voice_id: str | None = None,
    source_name: str | None = None,
) -> tuple[str, Path]:
    normalized_path = normalize_audio(source_path)
    assigned_voice_id = (voice_id or "").strip() or str(uuid.uuid4())

    if not assigned_voice_id.replace("-", "").replace("_", "").isalnum():
        raise RuntimeError("voice_id must contain only letters, numbers, '-' or '_'")

    saved_voice_path = VOICE_DIR / f"{assigned_voice_id}.wav"
    shutil.move(str(normalized_path), str(saved_voice_path))

    with _voice_lock:
        registry = read_voice_registry()
        effective_source_name = (source_name or "").strip() or source_path.name
        registry[assigned_voice_id] = {
            "voice_id": assigned_voice_id,
            "normalized_speaker_path": str(saved_voice_path),
            "source_path": str(source_path),
            "training_file_name": effective_source_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_voice_registry(registry)

    return assigned_voice_id, saved_voice_path


def get_voice_path(voice_id: str) -> Path | None:
    with _voice_lock:
        registry = read_voice_registry()
        entry = registry.get(voice_id)

    if not entry:
        return None

    normalized_speaker_path = entry.get("normalized_speaker_path")
    if not normalized_speaker_path:
        return None

    voice_path = Path(normalized_speaker_path).resolve()
    if not is_within(VOICE_DIR, voice_path):
        return None
    if not voice_path.exists():
        return None

    return voice_path


def list_voices() -> list[dict[str, str]]:
    with _voice_lock:
        registry = read_voice_registry()

    rows: list[dict[str, str]] = []
    for voice_id, entry in registry.items():
        voice_path_value = entry.get("normalized_speaker_path")
        if not voice_path_value:
            continue

        voice_path = Path(voice_path_value).resolve()
        if not is_within(VOICE_DIR, voice_path):
            continue
        if not voice_path.exists():
            continue

        rows.append(
            {
                "voice_id": voice_id,
                "training_file_name": entry.get("training_file_name", Path(entry.get("source_path", "")).name),
                "normalized_speaker_path": str(voice_path),
                "created_at": entry.get("created_at", ""),
            }
        )

    rows.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return rows


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
            "voice_count": len(list_voices()),
        }
    )


@app.get("/voices")
def voices():
    return jsonify(
        {
            "message": "ok",
            "voices": list_voices(),
        }
    )


@app.post("/voices/register")
def register_voice():
    data = request.get_json(silent=True) or {}

    speaker_wav_path = data.get("speaker_wav_path")
    speaker_original_name = (data.get("speaker_original_name") or "").strip() or None
    requested_voice_id = (data.get("voice_id") or "").strip() or None

    if not speaker_wav_path:
        return jsonify({"error": "speaker_wav_path is required"}), 400

    speaker_path = Path(speaker_wav_path).resolve()

    if not is_within(UPLOAD_DIR, speaker_path):
        return jsonify({"error": "speaker_wav_path must be inside uploads/"}), 400

    if not speaker_path.exists():
        return jsonify({"error": "speaker_wav_path does not exist"}), 400

    try:
        voice_id, normalized_speaker_path = create_or_update_voice(
            source_path=speaker_path,
            voice_id=requested_voice_id,
            source_name=speaker_original_name,
        )
    except Exception as exc:
        return (
            jsonify(
                {
                    "error": "voice registration failed",
                    "detail": str(exc),
                }
            ),
            500,
        )

    return jsonify(
        {
            "message": "ok",
            "voice_id": voice_id,
            "normalized_speaker_path": str(normalized_speaker_path),
        }
    )


@app.post("/synthesize")
def synthesize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    language = (data.get("language") or "ja").strip()
    speaker_wav_path = data.get("speaker_wav_path")
    speaker_original_name = (data.get("speaker_original_name") or "").strip() or None
    voice_id = (data.get("voice_id") or "").strip() or None
    output_path = data.get("output_path")

    if not text:
        return jsonify({"error": "text is required"}), 400

    if not speaker_wav_path and not voice_id:
        return jsonify({"error": "speaker_wav_path or voice_id is required"}), 400

    if not output_path:
        return jsonify({"error": "output_path is required"}), 400

    destination = Path(output_path).resolve()

    if not is_within(OUTPUT_DIR, destination):
        return jsonify({"error": "output_path must be inside outputs/"}), 400

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        normalized_speaker_path: Path
        used_voice_id: str | None = voice_id
        voice_source = "existing"

        if speaker_wav_path:
            speaker_path = Path(speaker_wav_path).resolve()
            if not is_within(UPLOAD_DIR, speaker_path):
                return jsonify({"error": "speaker_wav_path must be inside uploads/"}), 400
            if not speaker_path.exists():
                return jsonify({"error": "speaker_wav_path does not exist"}), 400

            used_voice_id, normalized_speaker_path = create_or_update_voice(
                source_path=speaker_path,
                voice_id=voice_id,
                source_name=speaker_original_name,
            )
            voice_source = "new"
        else:
            existing_voice_path = get_voice_path(voice_id or "")
            if not existing_voice_path:
                return jsonify({"error": "voice_id does not exist"}), 400
            normalized_speaker_path = existing_voice_path

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
            "voice_id": used_voice_id,
            "voice_source": voice_source,
            "normalized_speaker_path": str(normalized_speaker_path),
            "output_path": str(destination),
        }
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
