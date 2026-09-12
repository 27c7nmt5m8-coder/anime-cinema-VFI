import subprocess
import threading

from animecinemavfi.core.errors import Cancelled


class JobControl:
    """Cooperative pause + immediate subprocess cancellation; no GUI dependency."""

    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._run = threading.Event()
        self._run.set()
        self._lock = threading.Lock()
        self._processes: set[subprocess.Popen[bytes]] = set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def pause(self) -> None:
        self._run.clear()

    def resume(self) -> None:
        self._run.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._run.set()
        with self._lock:
            for process in self._processes:
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass

    def checkpoint(self) -> None:
        self._run.wait()
        self.raise_if_cancelled()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled("ユーザーによりキャンセルされました。")

    def register(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.add(process)
            if self.cancelled and process.poll() is None:
                process.kill()

    def unregister(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            self._processes.discard(process)
