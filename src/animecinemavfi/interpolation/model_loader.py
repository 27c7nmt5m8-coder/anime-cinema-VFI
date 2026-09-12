"""Strict loader for trusted official code. Caller owns process isolation."""

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any


def load_model(model_dir: Path, repository_dir: Path, device: str, version: str) -> Any:
    import torch

    torch.set_num_threads(2)
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDAが使用できません。PyTorch CUDA版とドライバーを確認してください。")
    sys.path[:0] = [str(model_dir.resolve().parent), str(repository_dir.resolve())]
    module = importlib.import_module("train_log.RIFE_HDv3")
    model = module.Model()
    signature = inspect.signature(model.inference)
    if "timestep" not in signature.parameters or "scale" not in signature.parameters:
        raise RuntimeError("任意timestep/scaleに対応したPractical-RIFEモデルが必要です。")
    if str(getattr(model, "version", "unknown")) != version:
        raise RuntimeError(
            f"Registryと実モデルのversionが違います: {getattr(model, 'version', 'unknown')}"
        )
    # Load state dict strictly: upstream's permissive load_model can silently
    # accept a wrong checkpoint. weights_only=True avoids generic pickle objects.
    state = torch.load(model_dir / "flownet.pkl", map_location="cpu", weights_only=True)
    cleaned = {k.removeprefix("module."): v for k, v in state.items()}
    expected_keys = model.flownet.state_dict().keys()
    missing = set(expected_keys) - cleaned.keys()
    if missing:
        raise RuntimeError(f"推論用の重みが不足しています: {sorted(missing)[:5]}")
    extras = cleaned.keys() - set(expected_keys)
    if extras:
        print(f"Ignoring {len(extras)} training-only checkpoint entries", file=sys.stderr)
    model.flownet.load_state_dict({k: cleaned[k] for k in expected_keys}, strict=True)
    model.eval()
    model.device()
    return model
