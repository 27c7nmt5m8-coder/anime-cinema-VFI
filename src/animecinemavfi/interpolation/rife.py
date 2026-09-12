import json
import logging
import os
import sys
from collections.abc import Iterator, Sequence
from fractions import Fraction
from typing import Any

import numpy as np

from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import OutOfMemoryError, VFIError
from animecinemavfi.interpolation.base import Frame, VideoInterpolationEngine
from animecinemavfi.interpolation.capabilities import EngineCapabilities
from animecinemavfi.interpolation.worker_runtime import MAX_TIMESTEPS
from animecinemavfi.models.registry import ModelSpec
from animecinemavfi.utils.process import ManagedProcess, read_exact, write_all

logger = logging.getLogger("animecinemavfi")


class RIFEEngine(VideoInterpolationEngine):
    capabilities = EngineCapabilities(multiple_timesteps=True)

    def __init__(
        self, model: ModelSpec, control: JobControl, device: str = "cuda", scale: float = 1.0
    ) -> None:
        self.model = model
        self.control = control
        self.device = device
        self.scale = scale
        self.proc: ManagedProcess | None = None
        self._pair: tuple[Frame, Frame] | None = None

    def load(self) -> None:
        self.model.validate_files()
        env = os.environ.copy()
        if self.device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = "-1"
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = ManagedProcess(
            [
                sys.executable,
                "-m",
                "animecinemavfi.interpolation.rife_worker",
                "--model",
                str(self.model.path),
                "--repository",
                str(self.model.repository_path),
                "--device",
                self.device,
                "--version",
                self.model.version,
            ],
            self.control,
            env=env,
            label="RIFE",
        )
        reply = self._reply()
        logger.info(
            "RIFE loaded: %s %s (runtime=%s, device=%s)",
            self.model.name,
            self.model.version,
            reply.get("version"),
            self.device,
        )

    def _reply(self) -> dict[str, Any]:
        assert self.proc
        raw = self.proc.output.readline(65536)
        self.control.raise_if_cancelled()
        if not raw:
            raise self.proc.error()
        try:
            data = json.loads(raw)
            if data.get("status") != "ok":
                message = str(data.get("message", "RIFEエラー"))
                if data.get("kind") == "oom":
                    raise OutOfMemoryError(message)
                raise VFIError("RIFE: " + message)
            return data
        except (ValueError, AttributeError) as exc:
            raise VFIError("RIFEプロセスから不正な応答を受け取りました。") from exc

    def _send(self, command: dict[str, Any]) -> None:
        assert self.proc
        self.control.checkpoint()
        write_all(self.proc.input, (json.dumps(command) + "\n").encode())

    def interpolate(self, left: Frame, right: Frame, timestep: Fraction) -> Frame:
        self.capabilities.validate_pair(left, right)
        if not isinstance(timestep, Fraction):
            raise ValueError("Timestep must be a Fraction")
        if not 0 < timestep < 1:
            return left if timestep <= 0 else right
        return next(self.interpolate_many(left, right, [timestep]))

    def interpolate_many(
        self, left: Frame, right: Frame, timesteps: Sequence[Fraction]
    ) -> Iterator[Frame]:
        self.capabilities.validate_pair(left, right)
        times = tuple(timesteps)
        if any(not isinstance(t, Fraction) or not 0 < t < 1 for t in times):
            raise ValueError("Timesteps must be Fractions inside (0, 1)")
        if not times:
            return
        if not self.proc:
            raise VFIError("RIFEモデルがロードされていません。")
        try:
            if self._pair is None or self._pair[0] is not left or self._pair[1] is not right:
                height, width, _ = left.data.shape
                self._send({"op": "pair", "width": width, "height": height})
                write_all(self.proc.input, left.data.tobytes())
                write_all(self.proc.input, right.data.tobytes())
                self._reply()
                self._pair = (left, right)
            offset = 0
            while offset < len(times):
                batch = times[offset : offset + MAX_TIMESTEPS]
                self._send(
                    {
                        "op": "infer_many",
                        "timesteps": [float(t) for t in batch],
                        "scale": self.scale,
                    }
                )
                try:
                    for index, timestep in enumerate(batch):
                        self.control.checkpoint()
                        reply = self._reply()
                        if reply.get("index") != index:
                            raise VFIError("RIFEの出力順序が不正です。")
                        raw = read_exact(self.proc.output, left.data.nbytes)
                        self.control.raise_if_cancelled()
                        if len(raw) != left.data.nbytes:
                            raise self.proc.error()
                        result = Frame(
                            np.frombuffer(raw, np.uint8).reshape(left.data.shape),
                            left.timestamp + (right.timestamp - left.timestamp) * timestep,
                            left.format,
                        )
                        offset += 1
                        yield result
                except OutOfMemoryError as exc:
                    if self.scale <= 0.25:
                        raise OutOfMemoryError(
                            "VRAMが不足しています。scale=0.25でも処理できません。GPU使用中の他アプリを閉じるか、低解像度素材で確認してください。"
                        ) from exc
                    self.scale /= 2
                    logger.warning(
                        "VRAM不足: scale=%sで未完了のtimestepを再試行します。", self.scale
                    )
        except (BrokenPipeError, OSError) as exc:
            self.control.raise_if_cancelled()
            raise self.proc.error() from exc

    def statistics(self) -> dict[str, Any]:
        if not self.proc:
            raise VFIError("RIFEモデルがロードされていません。")
        self._send({"op": "stats"})
        return self._reply()

    def close(self) -> None:
        self._pair = None
        if self.proc:
            self.proc.close()
            self.proc = None
