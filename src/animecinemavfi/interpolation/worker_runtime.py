"""Torch pair lifetime. No torch import on the GUI/control process path."""

from typing import Any

import numpy as np

from animecinemavfi.core.errors import OutOfMemoryError

MAX_TIMESTEPS = 32


class TensorPairCache:
    def __init__(self, model: Any, device: str) -> None:
        import torch

        self.torch, self.model, self.device = torch, model, device
        self.host: tuple[Any, Any] | None = None
        self.tensors: tuple[Any, Any] | None = None
        self.scale: float | None = None
        self.width = self.height = 0
        self.pair_preparations = self.device_transfers = self.inferences = self.oom_retries = 0

    def set_pair(self, raw_a: bytes, raw_b: bytes, width: int, height: int) -> None:
        self.release_device()
        self.host = None
        if not 1 <= width <= 16384 or not 1 <= height <= 16384:
            raise ValueError("Invalid dimensions")
        if len(raw_a) != width * height * 3 or len(raw_b) != width * height * 3:
            raise ValueError("Incomplete frame payload")
        self.width, self.height = width, height
        self.host = tuple(
            self.torch.from_numpy(np.frombuffer(raw, np.uint8).copy().reshape(height, width, 3))
            for raw in (raw_a, raw_b)
        )  # type: ignore[assignment]

    def release_device(self) -> None:
        self.tensors = None
        self.scale = None

    def _upload(self, host: Any, padding: tuple[int, int, int, int]) -> Any:
        # RGB8 transfer instead of a four-times-larger CPU float32 buffer.
        tensor = host.to(self.device)
        if self.device == "cuda":
            self.device_transfers += 1
        tensor = tensor.permute(2, 0, 1).unsqueeze(0).float() / 255
        return self.torch.nn.functional.pad(tensor, padding)

    def prepare(self, scale: float) -> tuple[Any, Any]:
        if scale not in {1.0, 0.5, 0.25}:
            raise ValueError("Invalid scale")
        if self.host is None:
            raise ValueError("No frame pair")
        if self.tensors is None or self.scale != scale:
            self.release_device()
            alignment = max(128, int(128 / scale))
            padding = (0, (-self.width) % alignment, 0, (-self.height) % alignment)
            self.tensors = (
                self._upload(self.host[0], padding),
                self._upload(self.host[1], padding),
            )
            self.scale = scale
            self.pair_preparations += 1
        return self.tensors

    def infer(self, timestep: float, scale: float) -> bytes:
        if not 0 < timestep < 1:
            raise ValueError("Invalid timestep")
        try:
            with self.torch.inference_mode():
                return self._infer(timestep, scale)
        except self.torch.cuda.OutOfMemoryError as exc:
            # Traceback owns failed inference tensors: release it before empty_cache.
            exc.__traceback__ = None
            self.release_device()
            self.oom_retries += 1
            if self.device == "cuda":
                self.torch.cuda.empty_cache()
            raise OutOfMemoryError("CUDA VRAM不足") from None

    def _infer(self, timestep: float, scale: float) -> bytes:
        a, b = self.prepare(scale)
        result = self.model.inference(a, b, timestep=timestep, scale=scale)
        data = (
            (result[0, :, : self.height, : self.width].clamp(0, 1) * 255)
            .round()
            .byte()
            .permute(1, 2, 0)
            .cpu()
            .numpy()
            .tobytes()
        )
        self.inferences += 1
        return data

    def statistics(self) -> dict[str, int]:
        stats = {
            "pair_preparations": self.pair_preparations,
            "device_transfers": self.device_transfers,
            "inferences": self.inferences,
            "oom_retries": self.oom_retries,
        }
        if self.device == "cuda":
            stats.update(
                allocated_bytes=self.torch.cuda.memory_allocated(),
                reserved_bytes=self.torch.cuda.memory_reserved(),
            )
        return stats

    def close(self) -> None:
        self.release_device()
        self.host = None
