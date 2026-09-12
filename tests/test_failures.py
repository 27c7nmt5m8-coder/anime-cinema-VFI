import sys
import threading
from dataclasses import replace

import pytest
from conftest import TestBlendEngine

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, ProcessError, VFIError
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.job import JobManager, JobSpec
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.utils.process import ManagedProcess, capture


def test_external_process_failure_reports_stderr():
    with pytest.raises(ProcessError, match="synthetic failure"):
        capture(
            [sys.executable, "-c", "import sys;sys.stderr.write('synthetic failure');sys.exit(7)"],
            JobControl(),
        )


def test_cancel_interrupts_blocked_external_reader():
    control = JobControl()
    with ManagedProcess([sys.executable, "-c", "import time;time.sleep(30)"], control) as process:
        timer = threading.Timer(0.1, control.cancel)
        timer.start()
        assert process.output.read(1) == b""
        with pytest.raises(Cancelled):
            process.finish()
        timer.join()
        assert process.process.poll() is not None


@pytest.mark.integration
def test_model_failure_cleans_workspace(sample_factory, tmp_path, monkeypatch):
    source = sample_factory(audio=0)
    monkeypatch.setattr(
        GPUManager, "detect", lambda *_: GPUInfo("test", False, None, None, "none", "test", "none")
    )

    class FailingEngine(TestBlendEngine):
        def load(self):
            raise VFIError("synthetic model load failure")

    output = tmp_path / "failed.mp4"
    manager = JobManager(
        ModelRegistry(tmp_path / "models.json"), engine_factory=lambda *_: FailingEngine()
    )
    with pytest.raises(VFIError, match="synthetic model"):
        manager.run(JobSpec(source, output, replace(AppConfig(), output_fps="60")), JobControl())
    assert not output.exists()
    assert not list(tmp_path.glob(".acvfi-*"))
    assert not list(tmp_path.glob("*.acvfi-lock"))
