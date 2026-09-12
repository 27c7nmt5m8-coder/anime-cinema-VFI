"""Real Qt event-loop startup and screenshot, without requiring a GPU."""

import argparse
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from animecinemavfi.core.config import user_data_dir
from animecinemavfi.ui.window import MainWindow
from animecinemavfi.utils.logging import Logger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path, default=Path("test-artifacts/gui-startup.png"))
    parser.add_argument("--font", type=Path)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    app = QApplication([])
    if args.font:
        QFontDatabase.addApplicationFont(str(args.font))
    window = MainWindow(Logger(user_data_dir() / "logs"))
    window.show()
    if args.input:
        QTimer.singleShot(100, lambda: window.load_input(args.input))
    args.screenshot.parent.mkdir(parents=True, exist_ok=True)

    def snapshot() -> None:
        if not window.grab().save(str(args.screenshot)):
            raise RuntimeError("Could not save Qt screenshot")
        window.close()

    QTimer.singleShot(4000, snapshot)
    QTimer.singleShot(15000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
