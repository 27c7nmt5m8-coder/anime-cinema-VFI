import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    def __init__(self, work: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.work = work

    def run(self) -> None:
        try:
            self.succeeded.emit(self.work())
        except Exception as exc:
            logging.getLogger("animecinemavfi").error("%s", exc)
            self.failed.emit(str(exc))


class LogSignals(QObject):
    line = Signal(str)


class GuiLogHandler(logging.Handler):
    def __init__(self, signals: LogSignals) -> None:
        super().__init__()
        self.signals = signals

    def emit(self, record: logging.LogRecord) -> None:
        self.signals.line.emit(self.format(record))
