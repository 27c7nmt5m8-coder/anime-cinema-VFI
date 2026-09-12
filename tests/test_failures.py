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


def test_cancelled_finish_releases_process_resources():
    control = JobControl()
    with ManagedProcess([sys.executable, "-c", "import time;time.sleep(30)"], control) as process:
        control.cancel()
        with pytest.raises(Cancelled):
            process.finish()
        # Cancellation must finish cleanup before the caller receives the exception.
        assert process.process.returncode is not None
        assert process.input.closed
        assert process.output.closed


def test_delayed_stderr_reader_tolerates_closed_pipe(monkeypatch):
    release = threading.Event()
    failures = []
    drain_stderr = ManagedProcess._drain_stderr

    def delayed_drain(process):
        release.wait(timeout=10)
        try:
            drain_stderr(process)
        except Exception as exc:
            failures.append(exc)

    monkeypatch.setattr(ManagedProcess, "_drain_stderr", delayed_drain)
    with ManagedProcess([sys.executable, "-c", "pass"], JobControl()) as process:
        try:
            process.close()
        finally:
            release.set()
            process._drain.join(timeout=5)
        assert not process._drain.is_alive()
        assert not failures


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
