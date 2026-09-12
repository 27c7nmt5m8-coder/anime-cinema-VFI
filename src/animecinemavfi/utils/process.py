import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import BinaryIO, cast

from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, ProcessError


def read_exact(stream: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            break
        data.extend(part)
    return bytes(data)


def write_all(stream: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        count = stream.write(view)
        if not count:
            raise BrokenPipeError("Process input closed")
        view = view[count:]


class ManagedProcess:
    def __init__(
        self,
        args: list[str],
        control: JobControl,
        *,
        env: dict[str, str] | None = None,
        label: str = "process",
    ) -> None:
        self.control = control
        self.label = label
        self.stderr: deque[str] = deque(maxlen=100)
        try:
            self.process = subprocess.Popen(
                args,
                shell=False,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except OSError as exc:
            raise ProcessError(f"{label}を起動できません: {exc}") from exc
        control.register(self.process)
        self._drain = threading.Thread(target=self._drain_stderr, daemon=True)
        self._drain.start()

    @property
    def input(self) -> BinaryIO:
        assert self.process.stdin is not None
        return cast(BinaryIO, self.process.stdin)

    @property
    def output(self) -> BinaryIO:
        assert self.process.stdout is not None
        return cast(BinaryIO, self.process.stdout)

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        while data := self.process.stderr.readline(8192):
            self.stderr.append(data.decode("utf-8", errors="replace").rstrip())

    def error(self) -> ProcessError:
        self._drain.join(timeout=0.2)
        return ProcessError(
            f"{self.label}失敗 (exit={self.process.poll()}):\n" + "\n".join(self.stderr)
        )

    def finish(self, timeout: float = 120) -> None:
        """Wait for exit, completing resource cleanup before propagating cancellation."""
        try:
            deadline = time.monotonic() + timeout
            while self.process.poll() is None:
                self.control.raise_if_cancelled()
                if time.monotonic() >= deadline:
                    self.close()
                    raise ProcessError(f"{self.label}の終了待ちがタイムアウトしました。")
                try:
                    self.process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            self._drain.join(timeout=2)
            self.control.raise_if_cancelled()
        except Cancelled:
            self.close()
            raise
        if self.process.returncode:
            raise self.error()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        self._drain.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        self.control.unregister(self.process)

    def __enter__(self) -> "ManagedProcess":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def capture(
    args: list[str],
    control: JobControl,
    *,
    timeout: float = 30,
    label: str = "process",
    progress: Callable[[], None] | None = None,
) -> bytes:
    with ManagedProcess(args, control, label=label) as proc:
        proc.input.close()
        chunks: list[bytes] = []
        failure: list[Exception] = []

        def read() -> None:
            try:
                total = 0
                while chunk := proc.output.read(65536):
                    total += len(chunk)
                    if total > 32 * 1024 * 1024:
                        raise ProcessError(f"{label}の出力が制限を超えました。")
                    chunks.append(chunk)
            except Exception as exc:
                failure.append(exc)

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout
        while thread.is_alive():
            control.raise_if_cancelled()
            if failure:
                raise failure[0]
            if time.monotonic() > deadline:
                raise ProcessError(f"{label}がタイムアウトしました。")
            if progress:
                progress()
            thread.join(0.1)
        if failure:
            raise failure[0]
        proc.finish(timeout=10)
        return b"".join(chunks)
