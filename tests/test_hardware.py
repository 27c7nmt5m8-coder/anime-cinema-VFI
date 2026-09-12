import importlib.util
import os
from fractions import Fraction as F
from pathlib import Path

import numpy as np
import pytest

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.diagnostics import probe_encoder
from animecinemavfi.core.gpu import GPUManager
from animecinemavfi.interpolation.rife import RIFEEngine
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.frame import FrameFormat, VideoFrame


@pytest.mark.integration
@pytest.mark.nvenc
@pytest.mark.parametrize("encoder", ["h264_nvenc", "hevc_nvenc"])
def test_nvenc_real_vui_and_sar(encoder, ffmpeg_available):
    result = probe_encoder(FFmpegManager(), encoder, JobControl())
    if result.status == "unavailable" and not GPUManager.nvidia_memory():
        if os.environ.get("ACVFI_REQUIRE_CUDA") == "1":
            pytest.fail(result.reason)
        pytest.skip("NVENC hardware/driver unavailable: " + result.reason)
    assert result.status == "passed", result.reason


@pytest.mark.cuda
@pytest.mark.rife
def test_real_cuda_repeated_pair_memory_plateaus(tmp_path):
    def unavailable(reason):
        if os.environ.get("ACVFI_REQUIRE_CUDA") == "1":
            pytest.fail(reason)
        pytest.skip(reason)

    if not importlib.util.find_spec("torch"):
        unavailable("PyTorch is absent")
    import torch

    if not torch.cuda.is_available():
        unavailable("CUDA hardware/PyTorch unavailable")
    model_dir, repo_dir = os.environ.get("RIFE_MODEL_DIR"), os.environ.get("RIFE_REPO_DIR")
    if not model_dir or not repo_dir:
        unavailable("Set RIFE_MODEL_DIR and RIFE_REPO_DIR")
    registry = ModelRegistry(tmp_path / "models.json")
    spec = registry.register(AppConfig().model_id, Path(model_dir), Path(repo_dir))
    engine = RIFEEngine(spec, JobControl(), "cuda")
    rng = np.random.default_rng(17)
    a = VideoFrame(rng.integers(0, 256, (128, 128, 3), dtype=np.uint8), F(0), FrameFormat())
    b = VideoFrame(rng.integers(0, 256, (128, 128, 3), dtype=np.uint8), F(1, 24), FrameFormat())
    times = [F(i, 5) for i in range(1, 5)]
    try:
        engine.load()
        for _ in range(10):
            for _frame in engine.interpolate_many(a, b, times):
                pass
        baseline = engine.statistics()
        samples = []
        for _ in range(200):
            for _frame in engine.interpolate_many(a, b, times):
                pass
            samples.append(engine.statistics())
        assert samples[-1]["device_transfers"] == baseline["device_transfers"] == 2
        assert (
            max(s["allocated_bytes"] for s in samples) <= baseline["allocated_bytes"] + 2 * 1024**2
        )
        assert (
            max(s["reserved_bytes"] for s in samples) <= baseline["reserved_bytes"] + 32 * 1024**2
        )
        for _ in range(50):
            for _frame in engine.interpolate_many(a.at(a.timestamp), b.at(b.timestamp), times):
                pass
        assert engine.statistics()["allocated_bytes"] <= baseline["allocated_bytes"] + 2 * 1024**2
    finally:
        engine.close()


@pytest.mark.windows
@pytest.mark.integration
def test_windows_long_unicode_path_end_to_end(tmp_path, sample_factory, monkeypatch):
    if os.name != "nt":
        pytest.skip("Windows path semantics require Windows")
    from conftest import fake_factory

    from animecinemavfi.core.gpu import GPUInfo
    from animecinemavfi.core.job import JobManager, JobSpec

    monkeypatch.setattr(
        GPUManager, "detect", lambda *_: GPUInfo("test", False, None, None, "none", "test", "none")
    )
    # Six 24fps frames span exactly 0.25s and produce fifteen 60fps frames.
    source = sample_factory("日本語 入力.mp4", fps="24", duration="0.25", audio=2)
    directory = tmp_path
    while len(str(directory)) < 280:
        directory /= "長めのパス 空白付き"
    directory.mkdir(parents=True)
    moved = directory / source.name
    source.replace(moved)
    output = directory / "補間 出力.mp4"
    manager = JobManager(ModelRegistry(tmp_path / "models.json"), engine_factory=fake_factory)
    result = manager.run(
        JobSpec(moved, output, AppConfig(output_fps="60", quality="fast")), JobControl()
    )
    assert result.frames == 15
    assert output.exists()
