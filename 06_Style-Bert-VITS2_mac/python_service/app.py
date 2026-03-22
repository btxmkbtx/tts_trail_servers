from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from pathlib import Path

import soundfile as sf
from flask import Flask, Response, jsonify, request, stream_with_context

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = (BASE_DIR / "models").resolve()
OUTPUT_DIR = (BASE_DIR / "outputs").resolve()
PYTHON_SERVICE_PORT = int(os.getenv("PYTHON_SERVICE_PORT", "5013"))
SBV2_DEVICE = os.getenv("SBV2_DEVICE", "auto")

app = Flask(__name__)

for directory in (MODELS_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def _resolve_device(requested: str) -> str:
    if requested and requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        # MPS has FP16/FP32 mixed-precision issues with SBV2 — fall back to CPU
    except ImportError:
        pass
    return "cpu"

DEVICE = _resolve_device(SBV2_DEVICE)

# ---------------------------------------------------------------------------
# Language mapping
# ---------------------------------------------------------------------------

def _get_language(lang_str: str):
    from style_bert_vits2.constants import Languages
    return {
        "ja": Languages.JP,
        "jp": Languages.JP,
        "en": Languages.EN,
        "zh": Languages.ZH,
        "zh-cn": Languages.ZH,
    }.get(lang_str.lower(), Languages.JP)

# ---------------------------------------------------------------------------
# Model cache
# ---------------------------------------------------------------------------

_model_cache: dict[str, object] = {}
_model_lock = threading.Lock()


def _valid_model_dirs() -> list[str]:
    """models/ 以下を最大2階層スキャンして有効なモデルディレクトリ名を返す。
    models/<name>/ と models/<group>/<name>/ の両方に対応。
    返す名前は MODELS_DIR からの相対パス（例: "jvnv-F1" or "style_bert_vits2_jvnv/jvnv-F1"）。
    """
    names = []
    if not MODELS_DIR.exists():
        return names

    def _is_valid(d: Path) -> bool:
        return (
            d.is_dir()
            and any(d.glob("*.safetensors"))
            and (d / "config.json").exists()
            and (d / "style_vectors.npy").exists()
        )

    for d in sorted(MODELS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if _is_valid(d):
            names.append(d.name)
        else:
            for sub in sorted(d.iterdir()):
                if _is_valid(sub):
                    names.append(f"{d.name}/{sub.name}")
    return names


def _parse_model_meta(model_name: str) -> dict:
    """Read config.json without loading model weights."""
    config_path = MODELS_DIR / Path(model_name) / "config.json"
    speakers = ["0"]
    styles = ["Neutral"]
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        spk2id: dict = cfg.get("speakers", {})
        if spk2id:
            speakers = list(spk2id.keys())
    # If model already loaded, get actual style names
    if model_name in _model_cache:
        loaded = _model_cache[model_name]
        if hasattr(loaded, "style2id") and loaded.style2id:
            styles = list(loaded.style2id.keys())
    return {"speakers": speakers, "styles": styles}


def _get_or_load_model(model_name: str):
    if model_name in _model_cache:
        return _model_cache[model_name]

    model_dir = MODELS_DIR / Path(model_name)
    safetensors = list(model_dir.glob("*.safetensors"))
    if not safetensors:
        raise RuntimeError(f"No .safetensors file found in {model_dir}")

    config_path = model_dir / "config.json"
    style_vec_path = model_dir / "style_vectors.npy"

    if not config_path.exists():
        raise RuntimeError(f"config.json not found in {model_dir}")
    if not style_vec_path.exists():
        raise RuntimeError(f"style_vectors.npy not found in {model_dir}")

    from style_bert_vits2.tts_model import TTSModel

    with _model_lock:
        if model_name not in _model_cache:
            print(f"[SBV2] Loading model: {model_name} on {DEVICE}", flush=True)
            model = TTSModel(
                model_path=safetensors[0],
                config_path=config_path,
                style_vec_path=style_vec_path,
                device=DEVICE,
            )
            model.load()
            # safetensors に FP16 重みが混在する場合の ABI ミスマッチを回避するため FP32 に統一
            net_g = getattr(model, "_TTSModel__net_g", None)
            if net_g is not None:
                net_g.float()
            # BERT モデルも FP32 に統一
            from style_bert_vits2.nlp import bert_models as _bert_models
            from style_bert_vits2.constants import Languages as _Languages
            for lang in (_Languages.JP, _Languages.EN, _Languages.ZH):
                try:
                    bert = _bert_models.load_model(lang)
                    bert.float()
                except Exception:
                    pass
            _model_cache[model_name] = model
            print(f"[SBV2] Model loaded: {model_name}", flush=True)

    return _model_cache[model_name]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    models = _valid_model_dirs()
    return jsonify({
        "ready": len(models) > 0,
        "runtime": "Style-Bert-VITS2",
        "device": DEVICE,
        "models_dir": str(MODELS_DIR),
        "available_models": models,
        "loaded_models": list(_model_cache.keys()),
    })


@app.get("/models")
def list_models():
    names = _valid_model_dirs()
    return jsonify({"models": names})


@app.get("/models/<model_name>")
def model_info(model_name: str):
    if model_name not in _valid_model_dirs():
        return jsonify({"error": f"Model '{model_name}' not found"}), 404
    # Load model to get accurate style list
    try:
        _get_or_load_model(model_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    meta = _parse_model_meta(model_name)
    return jsonify({"name": model_name, **meta})


@app.post("/synthesize")
def synthesize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    model_name = (data.get("model_name") or "").strip()
    output_path = data.get("output_path")
    language = (data.get("language") or "ja").strip()
    speaker_id = int(data.get("speaker_id") or 0)
    style = (data.get("style") or "Neutral").strip()
    style_weight = float(data.get("style_weight") or 5.0)
    length = float(data.get("length") or 1.0)
    sdp_ratio = float(data.get("sdp_ratio") or 0.2)
    noise = float(data.get("noise") or 0.6)
    noisew = float(data.get("noisew") or 0.8)
    pitch_scale = float(data.get("pitch_scale") or 1.0)
    intonation_scale = float(data.get("intonation_scale") or 1.0)

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not model_name:
        return jsonify({"error": "model_name is required"}), 400
    if not output_path:
        return jsonify({"error": "output_path is required"}), 400
    if model_name not in _valid_model_dirs():
        return jsonify({"error": f"Model '{model_name}' not found"}), 404

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        model = _get_or_load_model(model_name)
        lang = _get_language(language)
        sr, audio = model.infer(
            text=text,
            language=lang,
            speaker_id=speaker_id,
            style=style,
            style_weight=style_weight,
            length=length,
            sdp_ratio=sdp_ratio,
            noise=noise,
            noise_w=noisew,
            pitch_scale=pitch_scale,
            intonation_scale=intonation_scale,
        )
        sf.write(str(destination), audio, sr)
    except Exception as e:
        print(f"[SBV2] synthesis error: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "message": "ok",
        "model": f"Style-Bert-VITS2/{model_name}",
        "device": DEVICE,
        "output_path": str(destination),
    })


@app.post("/synthesize/stream")
def synthesize_stream():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    model_name = (data.get("model_name") or "").strip()
    output_path = data.get("output_path")
    language = (data.get("language") or "ja").strip()
    speaker_id = int(data.get("speaker_id") or 0)
    style = (data.get("style") or "Neutral").strip()
    style_weight = float(data.get("style_weight") or 5.0)
    length = float(data.get("length") or 1.0)
    sdp_ratio = float(data.get("sdp_ratio") or 0.2)
    noise = float(data.get("noise") or 0.6)
    noisew = float(data.get("noisew") or 0.8)
    pitch_scale = float(data.get("pitch_scale") or 1.0)
    intonation_scale = float(data.get("intonation_scale") or 1.0)

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not model_name:
        return jsonify({"error": "model_name is required"}), 400
    if not output_path:
        return jsonify({"error": "output_path is required"}), 400
    if model_name not in _valid_model_dirs():
        return jsonify({"error": f"Model '{model_name}' not found"}), 404

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    def generate():
        q: queue.Queue = queue.Queue()

        def _run() -> None:
            try:
                already_loaded = model_name in _model_cache
                if not already_loaded:
                    q.put(("progress", 20, f"モデル読み込み中: {model_name}..."))
                model = _get_or_load_model(model_name)
                q.put(("progress", 60, "音声合成中..."))
                lang = _get_language(language)
                sr, audio = model.infer(
                    text=text,
                    language=lang,
                    speaker_id=speaker_id,
                    style=style,
                    style_weight=style_weight,
                    length=length,
                    sdp_ratio=sdp_ratio,
                    noise=noise,
                    noise_w=noisew,
                    pitch_scale=pitch_scale,
                    intonation_scale=intonation_scale,
                )
                q.put(("progress", 90, "音声ファイル保存中..."))
                sf.write(str(destination), audio, sr)
                q.put(("done", None, None))
            except Exception as e:
                print(f"[SBV2] synthesis error: {e}", flush=True)
                q.put(("error", str(e), None))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while True:
            event_type, value, desc = q.get()
            if event_type == "progress":
                yield f"data: {json.dumps({'type': 'progress', 'percent': value, 'desc': desc})}\n\n"
            elif event_type == "done":
                yield f"data: {json.dumps({'type': 'done', 'output_path': str(destination), 'model': f'Style-Bert-VITS2/{model_name}', 'device': DEVICE})}\n\n"
                break
            elif event_type == "error":
                yield f"data: {json.dumps({'type': 'error', 'detail': value})}\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    print(f"[SBV2] Device: {DEVICE}", flush=True)
    print(f"[SBV2] Models dir: {MODELS_DIR}", flush=True)
    app.run(host="127.0.0.1", port=PYTHON_SERVICE_PORT, debug=False, threaded=True)
