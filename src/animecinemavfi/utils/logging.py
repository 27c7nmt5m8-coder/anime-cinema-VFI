import logging
import re
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


class PrivacyFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self._secrets: set[str] = {str(Path.home())}
        self._lock = threading.Lock()

    def protect(self, path: Path) -> None:
        with self._lock:
            self._secrets.update(
                {
                    str(path.resolve()),
                    str(path.resolve()).replace("\\", "/"),
                    str(path.resolve()).replace("\\", "\\\\"),
                }
            )

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        with self._lock:
            for secret in sorted(self._secrets, key=len, reverse=True):
                message = message.replace(secret, "<private-path>")
        # Traceback/code paths and command diagnostics from dependencies.
        message = re.sub(r"(?i)[a-z]:[\\/][^\s\"\']+", "<path>", message)
        message = re.sub(r"(?<![\w:])/(?:[^\s/\"\']+/)+[^\s\"\']*", "<path>", message)
        return message


class Logger:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.formatter = PrivacyFormatter()
        self.logger = logging.getLogger("animecinemavfi")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()
        handler = RotatingFileHandler(
            directory / "application.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(self.formatter)
        self.logger.addHandler(handler)

    def protect(self, *paths: Path) -> None:
        for path in paths:
            self.formatter.protect(path)
