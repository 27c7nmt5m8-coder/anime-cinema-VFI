import logging
import threading
from fractions import Fraction

import numpy as np
import pytest

from animecinemavfi.analysis.scene import SceneDetector
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, VFIError
from animecinemavfi.core.extensions import BasicMotionDirector, Decision, FrameContext, SegmentKey
from animecinemavfi.utils.logging import PrivacyFormatter
from animecinemavfi.utils.workspace import Workspace, check_disk, publish, validate_output


def test_scene_boundary():
    black = np.zeros((72, 128, 3), dtype=np.uint8)
    white = np.full_like(black, 255)
    scene = SceneDetector().detect(black, white)
    assert scene.cut
    assert not SceneDetector().detect(black, black).cut
    ctx = FrameContext(
        SegmentKey(Fraction(0), Fraction(1, 24)), Fraction(1, 120), scene.cut, scene.score
    )
    assert BasicMotionDirector().decide(ctx) == Decision.HOLD_LEFT


def test_cancel_unblocks_pause():
    control = JobControl()
    control.pause()
    result = []

    def work():
        try:
            control.checkpoint()
        except Cancelled:
            result.append("cancelled")

    worker = threading.Thread(target=work)
    worker.start()
    control.cancel()
    worker.join(2)
    assert result == ["cancelled"]


def test_pause_then_resume():
    control = JobControl()
    control.pause()
    result = threading.Event()
    worker = threading.Thread(target=lambda: (control.checkpoint(), result.set()))
    worker.start()
    assert not result.wait(0.05)
    control.resume()
    worker.join(2)
    assert result.is_set()


def test_paths_unicode_spaces_and_no_overwrite(tmp_path):
    original = tmp_path / "原画 movie.mp4"
    original.write_bytes(b"original")
    with pytest.raises(VFIError):
        validate_output(original, original)
    target = tmp_path / "補間 movie.mkv"
    assert validate_output(original, target) == target
    candidate = tmp_path / "temporary.mkv"
    candidate.write_bytes(b"new")
    target.write_bytes(b"existing")
    with pytest.raises(OSError):
        publish(candidate, target)
    assert target.read_bytes() == b"existing"


def test_workspace_cleanup_on_failure(tmp_path):
    output = tmp_path / "output.mkv"
    with pytest.raises(RuntimeError), Workspace(output) as work:
        (work / "partial.mp4").write_bytes(b"partial")
        raise RuntimeError("test")
    assert not work.exists()
    assert not output.with_name(output.name + ".acvfi-lock").exists()


def test_disk_full(tmp_path):
    with pytest.raises(VFIError, match="ディスク"):
        check_disk(tmp_path, 10**15)


def test_log_redacts_paths(tmp_path):
    formatter = PrivacyFormatter()
    source = tmp_path / "private person" / "秘密.mp4"
    formatter.protect(source)
    record = logging.LogRecord("test", logging.ERROR, "", 0, f"Failure on {source}", (), None)
    assert str(source) not in formatter.format(record)
    assert "private person" not in formatter.format(record)
