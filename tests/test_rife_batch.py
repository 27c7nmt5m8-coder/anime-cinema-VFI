import io
import json
import sys
from fractions import Fraction as F

import numpy as np
import pytest
from conftest import TestBlendEngine

from animecinemavfi.analysis.scene import SceneResult
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, OutOfMemoryError, VFIError
from animecinemavfi.core.extensions import BasicMotionDirector, Decision, SingleModelRouter
from animecinemavfi.core.pair_renderer import PairRenderer
from animecinemavfi.interpolation.rife import RIFEEngine
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.utils.process import ManagedProcess
from animecinemavfi.video.frame import FrameFormat, VideoFrame


def frames():
    fmt = FrameFormat()
    return VideoFrame(np.zeros((4, 6, 3), np.uint8), F(0), fmt), VideoFrame(
        np.full((4, 6, 3), 200, np.uint8), F(1, 24), fmt
    )


def message(**values):
    return (json.dumps({"status": "ok", **values}) + "\n").encode()


class FakeProcess:
    def __init__(self, payload):
        self.input, self.output = io.BytesIO(), io.BytesIO(payload)

    def error(self):
        return VFIError("worker abnormal termination")

    def close(self):
        pass


def engine_with_payload(tmp_path, payload):
    engine = RIFEEngine(
        ModelRegistry(tmp_path / "models.json").get(AppConfig().model_id), JobControl(), "cpu"
    )
    engine.proc = FakeProcess(payload)
    return engine


def test_multi_timestep_order_and_one_pair_request(tmp_path):
    a, b = frames()
    steps = [F(4, 5), F(1, 5), F(3, 5), F(2, 5)]
    engine = engine_with_payload(
        tmp_path,
        message() + b"".join(message(index=i) + bytes([i]) * a.data.nbytes for i in range(4)),
    )
    result = list(engine.interpolate_many(a, b, steps))
    assert [r.timestamp for r in result] == [t / 24 for t in steps]
    assert [r.data[0, 0, 0] for r in result] == [0, 1, 2, 3]
    sent = engine.proc.input.getvalue()
    assert sent.count(b'"op": "pair"') == 1
    assert sent.count(b'"op": "infer_many"') == 1


def test_oom_retries_only_remaining_outputs_without_resending_pair(tmp_path):
    a, b = frames()
    oom = message(status="error", kind="oom", message="CUDA VRAM")
    payload = (
        message()
        + message(index=0)
        + bytes(a.data.nbytes)
        + oom
        + oom
        + message(index=0)
        + bytes([99]) * a.data.nbytes
    )
    engine = engine_with_payload(tmp_path, payload)
    result = list(engine.interpolate_many(a, b, [F(1, 5), F(2, 5)]))
    assert [r.data[0, 0, 0] for r in result] == [0, 99]
    assert [r.timestamp for r in result] == [F(1, 120), F(2, 120)]
    assert engine.scale == 0.25
    sent = engine.proc.input.getvalue()
    assert sent.count(b'"op": "pair"') == 1
    assert sent.count(b'"op": "infer_many"') == 3


def test_oom_exhaustion_is_explicit(tmp_path):
    a, b = frames()
    engine = engine_with_payload(
        tmp_path, message() + message(status="error", kind="oom", message="OOM") * 3
    )
    with pytest.raises(OutOfMemoryError, match="scale=0.25"):
        list(engine.interpolate_many(a, b, [F(1, 2)]))


def test_batch_cancel_before_second_result(tmp_path):
    a, b = frames()
    engine = engine_with_payload(tmp_path, message() + message(index=0) + bytes(a.data.nbytes))
    results = engine.interpolate_many(a, b, [F(1, 5), F(2, 5)])
    next(results)
    engine.control.cancel()
    with pytest.raises(Cancelled):
        next(results)


def test_real_subprocess_abnormal_termination(tmp_path):
    a, b = frames()
    engine = engine_with_payload(tmp_path, b"")
    engine.proc = ManagedProcess(
        [sys.executable, "-c", "import sys; sys.exit(23)"], engine.control, label="RIFE test"
    )
    try:
        with pytest.raises(VFIError):
            list(engine.interpolate_many(a, b, [F(1, 2)]))
    finally:
        engine.close()


def test_output_order_corruption_is_error(tmp_path):
    a, b = frames()
    engine = engine_with_payload(tmp_path, message() + message(index=9))
    with pytest.raises(VFIError, match="順序"):
        list(engine.interpolate_many(a, b, [F(1, 2)]))


class RecordingEngine(TestBlendEngine):
    def __init__(self):
        self.calls = []

    def interpolate_many(self, left, right, timesteps):
        self.calls.append(tuple(timesteps))
        yield from super().interpolate_many(left, right, timesteps)


def test_pair_renderer_batches_four_times_and_keeps_anchor():
    a, b = frames()
    engine = RecordingEngine()
    renderer = PairRenderer(BasicMotionDirector(), SingleModelRouter(engine), JobControl())
    result = list(renderer.render(a, b, [F(i, 120) for i in range(5)], SceneResult(False, 0), True))
    assert result[0].frame.data is a.data
    assert engine.calls == [tuple(F(i, 5) for i in range(1, 5))]
    assert [r.interpolated for r in result] == [False, True, True, True, True]


def test_cut_pair_never_calls_model_even_with_custom_director():
    class EagerDirector:
        def decide(self, context):
            return Decision.INTERPOLATE

    a, b = frames()
    engine = RecordingEngine()
    renderer = PairRenderer(EagerDirector(), SingleModelRouter(engine), JobControl())
    result = list(renderer.render(a, b, [F(i, 120) for i in range(5)], SceneResult(True, 1), True))
    assert not engine.calls
    assert sum(r.protected for r in result) == 4
    assert all(r.frame.data is a.data for r in result)
