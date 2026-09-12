import importlib.util
import json
import os
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.job import JobManager, JobSpec
from animecinemavfi.models.registry import ModelRegistry

pytestmark = [pytest.mark.rife, pytest.mark.integration]


def test_official_rife_short_video(sample_factory, tmp_path):
    model_dir, repo_dir = os.environ.get("RIFE_MODEL_DIR"), os.environ.get("RIFE_REPO_DIR")
    if not model_dir or not repo_dir or not importlib.util.find_spec("torch"):
        pytest.skip("Set RIFE_MODEL_DIR and RIFE_REPO_DIR for official model test")
    registry = ModelRegistry(tmp_path / "models.json")
    registry.register(AppConfig().model_id, Path(model_dir), Path(repo_dir))
    source = sample_factory(fps="24", duration="5", audio=1)
    artifact_dir = Path(os.environ.get("VFI_TEST_ARTIFACTS", tmp_path))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    output = artifact_dir / "rife-4.25-preview-60fps.mp4"
    result = JobManager(registry).run(
        JobSpec(
            source,
            output,
            replace(AppConfig(), output_fps="60", device="cpu", quality="fast"),
            preview_duration=Fraction(5),
        ),
        JobControl(),
    )
    assert result.frames == 300
    assert result.interpolated > 0
    assert result.reference and result.reference.exists()
    assert json.loads(result.report.read_text(encoding="utf-8"))["model_id"] == AppConfig().model_id


def test_official_rife_source_multiplier(sample_factory, tmp_path):
    model_dir, repo_dir = os.environ.get("RIFE_MODEL_DIR"), os.environ.get("RIFE_REPO_DIR")
    if not model_dir or not repo_dir or not importlib.util.find_spec("torch"):
        pytest.skip("Set RIFE_MODEL_DIR and RIFE_REPO_DIR for official model test")
    registry = ModelRegistry(tmp_path / "models.json")
    registry.register(AppConfig().model_id, Path(model_dir), Path(repo_dir))
    source = sample_factory(fps="24000/1001", duration="1.001", audio=2)
    result = JobManager(registry).run(
        JobSpec(
            source,
            tmp_path / "source-x5.mp4",
            replace(
                AppConfig(), fps_mode="source", source_multiplier=5, device="cpu", quality="fast"
            ),
        ),
        JobControl(),
    )
    data = json.loads(result.report.read_text(encoding="utf-8"))
    assert result.frames == 120
    assert result.interpolated > 0
    assert data["settings"]["output_fps"] == "120000/1001"
    stats = data["engine_statistics"]
    assert stats["inferences"] == result.interpolated
    assert stats["pair_preparations"] * 4 == stats["inferences"]
    assert stats["device_transfers"] == 0  # CPU result is not a CUDA benchmark.
