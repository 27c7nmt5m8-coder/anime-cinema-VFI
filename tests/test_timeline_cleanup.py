import os
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from conftest import fake_factory

import animecinemavfi.utils.workspace as workspace_module
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.job import JobManager, JobSpec, Progress
from animecinemavfi.models.registry import ModelRegistry

pytestmark = pytest.mark.integration


def _assert_database_is_releasable(path: Path) -> None:
    if os.name == "nt":
        probe = path.with_name("timeline-cleanup-probe.sqlite")
        path.rename(probe)
        probe.rename(path)
        return

    descriptors = Path("/proc/self/fd")
    if not descriptors.is_dir():
        pytest.skip("Open-file inspection is unavailable on this platform")
    expected = str(path.resolve())
    open_descriptors = []
    for descriptor in descriptors.iterdir():
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target.removesuffix(" (deleted)") == expected:
            open_descriptors.append(descriptor.name)
    assert not open_descriptors, f"timeline database is still open on fd {open_descriptors}"


@pytest.mark.parametrize("cancel", [False, True], ids=["preview", "cancel"])
def test_job_releases_timeline_before_workspace_cleanup(
    sample_factory: Callable[..., Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    monkeypatch.setattr(
        GPUManager,
        "detect",
        lambda *_: GPUInfo("test", False, None, None, "none", "test", "none"),
    )
    checked: list[Path] = []
    real_rmtree = workspace_module.shutil.rmtree

    def checked_rmtree(path: str | os.PathLike[str]) -> None:
        database = Path(path) / "timeline.sqlite"
        if database.exists():
            _assert_database_is_releasable(database)
            checked.append(database)
        real_rmtree(path)

    monkeypatch.setattr(workspace_module.shutil, "rmtree", checked_rmtree)
    source = sample_factory(fps="8", duration="0.5", audio=0)
    manager = JobManager(ModelRegistry(tmp_path / "models.json"), engine_factory=fake_factory)
    control = JobControl()
    spec = JobSpec(
        source,
        tmp_path / "output.mp4",
        replace(AppConfig(), output_fps="16", quality="fast"),
        preview_duration=Fraction(1, 4),
    )

    def progress(update: Progress) -> None:
        if cancel and update.completed >= 1 and update.total:
            control.cancel()

    if cancel:
        with pytest.raises(Cancelled):
            manager.run(spec, control, progress)
    else:
        manager.run(spec, control, progress)

    assert len(checked) == 1
