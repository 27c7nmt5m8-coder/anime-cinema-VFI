"""Real CUDA benchmark. Same model/pixels/scale, old and new transfer paths.

Excludes decode/encode/IPC; includes inference, GPU transfer and output quantization.
Execute as a separate process. Does not produce performance values without CUDA.
"""

import argparse
import contextlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from animecinemavfi.core.config import AppConfig
from animecinemavfi.interpolation.model_loader import load_model
from animecinemavfi.interpolation.worker_runtime import TensorPairCache
from animecinemavfi.models.registry import ModelRegistry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--pairs", type=int, default=50)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--scale", type=float, choices=[1.0, 0.5, 0.25], default=1.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import torch
    import torch.nn.functional as functional

    if not torch.cuda.is_available():
        parser.error("CUDA GPU/PyTorchが必要です。性能値は生成しません。")
    if args.pairs < 5 or min(args.width, args.height) < 1 or max(args.width, args.height) > 16384:
        parser.error("pairs >=5, dimensions 1..16384 required")
    if args.output.exists():
        parser.error("出力が既に存在します。別の名前を指定してください。")
    spec = ModelRegistry(args.registry).get(AppConfig().model_id)
    spec.validate_files()
    with contextlib.redirect_stdout(sys.stderr):
        model = load_model(spec.path, spec.repository_path, "cuda", spec.version)
    rng = np.random.default_rng(42)
    pixels = [rng.integers(0, 256, (args.height, args.width, 3), dtype=np.uint8) for _ in range(2)]
    host = [torch.from_numpy(p).permute(2, 0, 1).unsqueeze(0).float() / 255 for p in pixels]
    raw = [p.tobytes() for p in pixels]
    alignment = max(128, int(128 / args.scale))
    padding = (0, -args.width % alignment, 0, -args.height % alignment)
    cache = TensorPairCache(model, "cuda")

    def legacy():
        for t in (0.2, 0.4, 0.6, 0.8):
            a, b = [functional.pad(p.to("cuda"), padding) for p in host]
            value = model.inference(a, b, timestep=t, scale=args.scale)
            data = (
                (value[0, :, : args.height, : args.width].clamp(0, 1) * 255)
                .round()
                .byte()
                .permute(1, 2, 0)
                .cpu()
                .numpy()
                .tobytes()
            )
            del a, b, value, data

    def reused():
        cache.set_pair(*raw, args.width, args.height)
        for t in (0.2, 0.4, 0.6, 0.8):
            cache.infer(t, args.scale)
        cache.release_device()

    timings = {"legacy": [], "reused": []}
    with torch.inference_mode():
        for _ in range(5):
            legacy()
            reused()
        before = cache.statistics()
        for i in range(args.pairs):
            for name in ("legacy", "reused") if i % 2 else ("reused", "legacy"):
                torch.cuda.synchronize()
                start = time.perf_counter()
                (legacy if name == "legacy" else reused)()
                torch.cuda.synchronize()
                timings[name].append(time.perf_counter() - start)
    report = {
        "gpu": torch.cuda.get_device_name(),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "model": spec.id,
        "pairs": args.pairs,
        "resolution": [args.width, args.height],
        "scale": args.scale,
        "timesteps": [0.2, 0.4, 0.6, 0.8],
        "scope": "inference + transfer + output quantization; excludes decode/encode/IPC",
        "seconds_per_pair": {
            name: {"median": statistics.median(values), "samples": values}
            for name, values in timings.items()
        },
        "new_measured_device_transfers": cache.statistics()["device_transfers"]
        - before["device_transfers"],
        "legacy_transfers_from_loop": args.pairs * 8,
    }
    cache.close()
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
