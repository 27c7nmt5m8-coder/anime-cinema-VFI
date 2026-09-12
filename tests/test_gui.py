from PySide6.QtWidgets import QApplication

from animecinemavfi.ui.window import MainWindow
from animecinemavfi.utils.logging import Logger


def test_window_starts_without_gpu_or_model(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    logs = Logger(tmp_path / "logs")
    window = MainWindow(logs, startup_checks=False)
    window.show()
    app.processEvents()
    assert window.isVisible()
    assert not window.start_button.isEnabled()
    assert window.model_combo.count() == 1
    window.fps_combo.setCurrentIndex(2)
    assert window.custom_fps.isEnabled()
    window.custom_fps.setText("120000/1001")
    assert window._settings().output_fps == "120000/1001"
    window.close()
    app.processEvents()


def wait_until(app, condition, seconds=5):
    import time

    from PySide6.QtTest import QTest

    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert condition(), "GUI signal/worker timed out"


def test_source_fps_label(tmp_path, monkeypatch, probe_data):
    from animecinemavfi.video.probe import VideoProbe

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Logger(tmp_path / "logs"), startup_checks=False)
    window.input_info = VideoProbe.parse(probe_data, tmp_path / "input.mp4")
    window.fps_combo.setCurrentIndex(window.fps_combo.findData("source:5"))
    assert window.fps_result.text() == "119.880 fps (120000/1001)"
    assert window._settings().fps_mode == "source"
    assert window._settings().source_multiplier == 5
    assert not window.custom_fps.isEnabled()
    window.close()
    app.processEvents()


def test_start_pause_resume_cancel_worker(tmp_path, monkeypatch):
    import threading

    from PySide6.QtCore import QThread
    from PySide6.QtTest import QTest

    from animecinemavfi.core.job import JobManager, Progress

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    reached = threading.Event()
    ticks = []

    def work(self, spec, control, progress):
        assert QThread.currentThread() != app.thread()
        progress(Progress("補間・エンコード", 0, 10000))
        while True:
            control.checkpoint()
            ticks.append(len(ticks))
            reached.set()
            threading.Event().wait(0.01)

    monkeypatch.setattr(JobManager, "run", work)
    window = MainWindow(Logger(tmp_path / "logs"), startup_checks=False)
    window.input_path = tmp_path / "日本語 input.mp4"
    window.output_edit.setText(str(tmp_path / "out.mp4"))
    try:
        window._start(False)
        wait_until(app, lambda: reached.is_set() and window.pause_button.isEnabled())
        window._pause()
        assert window.pause_button.text() == "Resume"
        QTest.qWait(50)
        count = len(ticks)
        QTest.qWait(50)
        assert len(ticks) == count
        window._pause()
        wait_until(app, lambda: len(ticks) > count)
        assert window.pause_button.text() == "Pause"
        window._cancel()
        wait_until(app, lambda: window.job_task is None)
        assert window.control is None
        assert not window.paused
    finally:
        window._cancel()
        if window.job_task:
            wait_until(app, lambda: window.job_task is None)
        window.close()
        app.processEvents()
