from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run IndexTTS2 inference inside the vendor uv environment")
    parser.add_argument("--vendor-dir", required=True)
    parser.add_argument("--cfg-path", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--speaker", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--emo-audio")
    parser.add_argument("--emo-alpha", type=float, default=1.0)
    parser.add_argument("--use-emo-text", action="store_true")
    parser.add_argument("--emo-text")
    parser.add_argument("--use-random", action="store_true")
    parser.add_argument("--use-fp16", action="store_true")
    parser.add_argument("--use-cuda-kernel", action="store_true")
    parser.add_argument("--use-deepspeed", action="store_true")
    return parser.parse_args()


def resolve_device(requested: str) -> str:
    import torch

    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda:0"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main() -> int:
    args = parse_args()
    vendor_dir = Path(args.vendor_dir).resolve()
    sys.path.insert(0, str(vendor_dir))

    from indextts.infer_v2 import IndexTTS2

    device = resolve_device(args.device)
    use_fp16 = bool(args.use_fp16 and device.startswith("cuda"))
    use_cuda_kernel = bool(args.use_cuda_kernel and device.startswith("cuda"))
    use_deepspeed = bool(args.use_deepspeed and device.startswith("cuda"))

    tts = IndexTTS2(
        cfg_path=args.cfg_path,
        model_dir=args.model_dir,
        use_fp16=use_fp16,
        device=device,
        use_cuda_kernel=use_cuda_kernel,
        use_deepspeed=use_deepspeed,
    )

    def _progress(value, desc=""):
        print(f"[PROGRESS] {int(value * 100):3d}%  {desc}", file=sys.stderr, flush=True)

    tts.gr_progress = _progress

    tts.infer(
        spk_audio_prompt=args.speaker,
        text=args.text,
        output_path=args.output,
        emo_audio_prompt=args.emo_audio,
        emo_alpha=args.emo_alpha,
        use_emo_text=args.use_emo_text,
        emo_text=args.emo_text,
        use_random=args.use_random,
        verbose=True,
    )

    print(f"OUTPUT={args.output}")
    print(f"DEVICE={device}")
    print("RUNTIME=IndexTTS2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
