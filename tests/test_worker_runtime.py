import gc
import weakref

import numpy as np
import pytest

from animecinemavfi.core.errors import OutOfMemoryError
from animecinemavfi.interpolation.worker_runtime import TensorPairCache

torch = pytest.importorskip("torch", reason="Torch runtime tests require CPU or CUDA PyTorch")


class Model:
    def __init__(self):
        self.identities = []
        self.fail_once = False
        self.failed_tensor = None

    def inference(self, a, b, timestep, scale):
        self.identities.append((a.data_ptr(), b.data_ptr()))
        if self.fail_once:
            self.fail_once = False
            temporary = a.clone()
            self.failed_tensor = weakref.ref(temporary)
            raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")
        return a * (1 - timestep) + b * timestep


def cache_with_pair(device="cpu"):
    model = Model()
    cache = TensorPairCache(model, device)
    cache.set_pair(bytes(6 * 4 * 3), bytes([200]) * (6 * 4 * 3), 6, 4)
    return model, cache


def test_same_gpu_tensor_inputs_are_reused_for_all_timesteps(monkeypatch):
    model, cache = cache_with_pair()
    uploads = []
    original = cache._upload

    def upload(host, padding):
        uploads.append(host)
        return original(host, padding)

    monkeypatch.setattr(cache, "_upload", upload)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: pytest.fail("unconditional empty_cache"))
    for _ in range(25):
        for t in (0.2, 0.4, 0.6, 0.8):
            data = cache.infer(t, 1.0)
            assert np.frombuffer(data, np.uint8)[0] == round(200 * t)
    assert len(uploads) == 2
    assert len(set(model.identities)) == 1
    assert cache.statistics()["pair_preparations"] == 1
    tensors = [weakref.ref(t) for t in cache.tensors]
    cache.close()
    gc.collect()
    assert all(t() is None for t in tensors)


def test_oom_releases_failed_locals_and_rebuilds_only_then():
    model, cache = cache_with_pair()
    cache.infer(0.2, 1.0)
    tensors = [weakref.ref(t) for t in cache.tensors]
    model.fail_once = True
    with pytest.raises(OutOfMemoryError):
        cache.infer(0.4, 1.0)
    gc.collect()
    assert cache.tensors is None
    assert model.failed_tensor() is None
    assert all(t() is None for t in tensors)
    cache.infer(0.4, 0.5)
    cache.infer(0.6, 0.5)
    assert cache.statistics()["pair_preparations"] == 2
    assert cache.statistics()["oom_retries"] == 1
    cache.close()
