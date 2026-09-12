import logging
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from animecinemavfi import __version__
from animecinemavfi.core.config import AppConfig, ConfigManager, user_data_dir
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.job import JobManager, JobResult, JobSpec, Progress
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.ui.tasks import GuiLogHandler, LogSignals, Task
from animecinemavfi.utils.logging import Logger
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.output_fps import OutputFPS
from animecinemavfi.video.probe import VideoInfo, VideoProbe
from animecinemavfi.video.timing import parse_fps

STYLE = """
QMainWindow, QWidget { background:#111823; color:#e4eaf2; font-family:'Segoe UI','Yu Gothic UI'; font-size:13px; }
QLabel#title { font-size:28px; font-weight:700; color:#f6f9ff; }
QLabel#subtitle { color:#9dafc3; }
QLabel#input { border:1px dashed #4a6d94; border-radius:10px; padding:18px; background:#172333; }
QLineEdit, QComboBox, QDoubleSpinBox, QPlainTextEdit { background:#0c131e; border:1px solid #34465d; border-radius:5px; padding:6px; }
QPushButton { background:#23364b; border:1px solid #3e5570; border-radius:5px; padding:8px 16px; }
QPushButton:hover { background:#304a66; }
QPushButton:disabled { color:#627185; background:#1a2431; border-color:#263545; }
QPushButton#primary { background:#58d3bd; color:#09261f; font-weight:700; border:0; }
QPushButton#primary:disabled { background:#23364b; color:#627185; }
QProgressBar { background:#0c131e; border:1px solid #34465d; border-radius:5px; text-align:center; min-height:18px; }
QProgressBar::chunk { background:#419f91; }
QTabBar::tab { padding:10px 20px; background:#1a2839; }
QTabBar::tab:selected { background:#2a4158; }
QCheckBox { spacing:8px; }
QScrollArea { border:0; }
"""


class MainWindow(QMainWindow):
    def __init__(self, logs: Logger, *, startup_checks: bool = True) -> None:
        super().__init__()
        self.logs = logs
        self.config_manager = ConfigManager()
        self.registry = ModelRegistry()
        config_error = ""
        try:
            self.config = self.config_manager.load()
        except Exception as exc:
            self.config = AppConfig()
            config_error = str(exc)
        self.input_path: Path | None = None
        self.input_info: VideoInfo | None = None
        self.result: JobResult | None = None
        self.control: JobControl | None = None
        self.job_task: Task | None = None
        self.tasks: list[Task] = []
        self.controls: list[JobControl] = []
        self.probing = False
        self.paused = False
        self.closing = False
        self.gpu_busy = False
        self.setWindowTitle(f"AnimeCinemaVFI {__version__}")
        self.resize(1060, 870)
        self.setMinimumSize(850, 650)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLE)
        self._build()
        self.log_signals = LogSignals(self)
        self.log_signals.line.connect(self.log_view.appendPlainText)
        self.gui_handler = GuiLogHandler(self.log_signals)
        self.gui_handler.setFormatter(logs.formatter)
        logs.logger.addHandler(self.gui_handler)
        self._load_models()
        if config_error:
            self.status.setText(config_error)
            logs.logger.error(config_error)
        self.memory_timer = QTimer(self)
        self.memory_timer.setInterval(5000)
        self.memory_timer.timeout.connect(self._refresh_memory)
        if startup_checks:
            QTimer.singleShot(0, self._detect_gpu)
            self.memory_timer.start()

    @staticmethod
    def _button(text: str, slot: Any) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    @staticmethod
    def _combo(items: list[tuple[str, Any]], selected: Any) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(selected)))
        return combo

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("AnimeCinemaVFI")
        title.setObjectName("title")
        subtitle = QLabel(f"v{__version__}  /  Original Motion Preservation")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        process = QWidget()
        process_layout = QVBoxLayout(process)
        self.input_label = QLabel(
            "動画をここへドラッグ＆ドロップ\nまたは「ファイル選択」から読み込む"
        )
        self.input_label.setObjectName("input")
        self.input_label.setWordWrap(True)
        process_layout.addWidget(self.input_label)
        self.choose_button = self._button("ファイル選択", self._choose_input)
        process_layout.addWidget(self.choose_button)
        self.info_label = QLabel("解像度 / FPS / codec / bit depth / SDR・HDR / duration / audio")
        self.info_label.setWordWrap(True)
        process_layout.addWidget(self.info_label)
        self.form_box = QWidget()
        form = QGridLayout(self.form_box)
        self.output_edit = QLineEdit()
        self.output_button = self._button("出力先", self._choose_output)
        form.addWidget(QLabel("出力ファイル"), 0, 0)
        form.addWidget(self.output_edit, 0, 1, 1, 3)
        form.addWidget(self.output_button, 0, 4)
        self.fps_combo = self._combo(
            [
                ("60 fps", "60"),
                ("120 fps", "120"),
                ("Custom FPS", "custom"),
                ("Source ×2", "source:2"),
                ("Source ×5", "source:5"),
            ],
            self.config.output_fps,
        )
        if self.config.output_fps not in {"60", "120"}:
            self.fps_combo.setCurrentIndex(2)
        if self.config.fps_mode == "source":
            value = f"source:{self.config.source_multiplier}"
            if self.fps_combo.findData(value) < 0:
                self.fps_combo.addItem(f"Source ×{self.config.source_multiplier}", value)
            self.fps_combo.setCurrentIndex(self.fps_combo.findData(value))
        self.custom_fps = QLineEdit(self.config.output_fps)
        self.custom_fps.setPlaceholderText("例: 120000/1001")
        self.custom_fps.setEnabled(self.fps_combo.currentData() == "custom")
        self.fps_result = QLabel()
        self.fps_result.setWordWrap(True)
        self.fps_combo.currentIndexChanged.connect(self._update_fps_display)
        self.custom_fps.textChanged.connect(self._update_fps_display)
        self._update_fps_display()
        form.addWidget(QLabel("出力FPS"), 1, 0)
        form.addWidget(self.fps_combo, 1, 1)
        form.addWidget(self.custom_fps, 1, 2)
        form.addWidget(self.fps_result, 1, 3, 1, 2)
        self.encoder_combo = self._combo(
            [
                ("H.264 / CPU", "libx264"),
                ("HEVC / CPU", "libx265"),
                ("H.264 / NVENC", "h264_nvenc"),
                ("HEVC / NVENC", "hevc_nvenc"),
            ],
            self.config.encoder,
        )
        self.quality_combo = self._combo(
            [("High", "high"), ("Balanced", "balanced"), ("Fast", "fast")], self.config.quality
        )
        form.addWidget(QLabel("Encoder / Quality"), 2, 0)
        form.addWidget(self.encoder_combo, 2, 1, 1, 2)
        form.addWidget(self.quality_combo, 2, 3, 1, 2)
        self.model_combo = QComboBox()
        self.register_button = self._button("RIFEフォルダー登録", self._register_model)
        form.addWidget(QLabel("RIFE model"), 3, 0)
        form.addWidget(self.model_combo, 3, 1, 1, 2)
        form.addWidget(self.register_button, 3, 3, 1, 2)
        self.scene_check = QCheckBox("Scene Change Protection")
        self.scene_check.setChecked(self.config.scene_protection)
        self.scale_combo = self._combo(
            [("Scale 1.0", 1.0), ("Scale 0.5 / 4K推奨", 0.5), ("Scale 0.25", 0.25)],
            self.config.processing_scale,
        )
        form.addWidget(self.scene_check, 4, 0, 1, 3)
        form.addWidget(self.scale_combo, 4, 3, 1, 2)
        self.preview_start = QDoubleSpinBox()
        self.preview_start.setRange(0, 359999)
        self.preview_start.setDecimals(3)
        self.preview_start.setSuffix(" 秒から")
        self.preview_length = self._combo([("5 秒", 5), ("10 秒", 10), ("30 秒", 30)], 5)
        form.addWidget(QLabel("プレビュー区間"), 5, 0)
        form.addWidget(self.preview_start, 5, 1, 1, 2)
        form.addWidget(self.preview_length, 5, 3, 1, 2)
        process_layout.addWidget(self.form_box)
        note = QLabel(
            "v0.1: 8bit SDRの基本補間。コマ打ち・作画意図の解析はv0.2予定。\n"
            "120fpsは高画質を保証しません。まず短時間プレビューで確認してください。"
        )
        note.setWordWrap(True)
        note.setObjectName("subtitle")
        process_layout.addWidget(note)
        process_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(process)
        self.tabs.addTab(scroll, "処理")
        self.settings_box = QWidget()
        settings = QFormLayout(self.settings_box)
        self.ffmpeg_edit = QLineEdit(self.config.ffmpeg)
        self.ffprobe_edit = QLineEdit(self.config.ffprobe)
        for name, edit in (("FFmpeg", self.ffmpeg_edit), ("FFprobe", self.ffprobe_edit)):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(edit)
            row_layout.addWidget(
                self._button("参照", lambda checked=False, field=edit: self._choose_tool(field))
            )
            settings.addRow(name, row)
        self.device_combo = self._combo(
            [("Auto / CUDA優先", "auto"), ("NVIDIA CUDA", "cuda"), ("CPU / 低速", "cpu")],
            self.config.device,
        )
        settings.addRow("VFI処理デバイス", self.device_combo)
        self.audio_combo = self._combo(
            [("全音声をコピー", "copy"), ("全音声をAAC変換", "aac")], self.config.audio_mode
        )
        settings.addRow("音声", self.audio_combo)
        self.subtitles_check = QCheckBox("字幕を保持（MKV推奨）")
        self.subtitles_check.setChecked(self.config.preserve_subtitles)
        settings.addRow(self.subtitles_check)
        self.vfr_check = QCheckBox("VFR実験処理を許可（出力CFRへの時刻丸めあり）")
        self.vfr_check.setChecked(self.config.allow_vfr)
        settings.addRow(self.vfr_check)
        settings.addRow(self._button("設定を保存", self._save_settings))
        settings.addRow(
            self._button("設定・ログフォルダーを開く", lambda: self._open(user_data_dir()))
        )
        help_label = QLabel(
            "公式Practical-RIFEのmodelフォルダーを含むリポジトリを取得し、\n"
            "その中のtrain_logに4.25のPythonファイルとflownet.pklを置いて登録します。\n"
            "モデルのPythonコードは実行されます。公式配布のみ使用してください。\n\n"
            "HDR / 10bit以上 / 回転タグ / インターレースはv0.1では処理を停止します。\n"
            "MP4に保持できない音声・字幕は、設定変更が必要です。\n"
            "チャプターとグローバルメタデータはv0.1では引き継ぎません。"
        )
        help_label.setWordWrap(True)
        settings.addRow(help_label)
        self.tabs.addTab(self.settings_box, "設定")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2500)
        self.tabs.addTab(self.log_view, "ログ")
        self.gpu_label = QLabel("GPU確認待ち")
        self.gpu_label.setWordWrap(True)
        layout.addWidget(self.gpu_label)
        self.vram_label = QLabel("VRAM: 未取得")
        layout.addWidget(self.vram_label)
        self.status = QLabel("動画と公式RIFEモデルを選択してください。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        buttons = QHBoxLayout()
        self.preview_button = self._button("Preview", lambda: self._start(True))
        self.start_button = self._button("Start", lambda: self._start(False))
        self.start_button.setObjectName("primary")
        self.pause_button = self._button("Pause", self._pause)
        self.cancel_button = self._button("Cancel", self._cancel)
        self.open_original = self._button(
            "元タイミング参照", lambda: self._open(self.result.reference if self.result else None)
        )
        self.open_result = self._button(
            "出力を開く", lambda: self._open(self.result.output if self.result else None)
        )
        for button in (
            self.preview_button,
            self.start_button,
            self.pause_button,
            self.cancel_button,
            self.open_original,
            self.open_result,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        for label in (
            self.input_label,
            self.info_label,
            self.status,
            self.gpu_label,
            self.vram_label,
        ):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.setCentralWidget(root)
        self._busy(False)
        self.open_original.setEnabled(False)
        self.open_result.setEnabled(False)

    def _busy(self, busy: bool) -> None:
        for widget in (self.form_box, self.settings_box, self.choose_button):
            widget.setEnabled(not busy)
        self.start_button.setEnabled(not busy and self.input_path is not None)
        self.preview_button.setEnabled(not busy and self.input_path is not None)
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(busy and self.control is not None)

    def _track(self, task: Task, control: JobControl | None = None) -> None:
        self.tasks.append(task)
        if control:
            self.controls.append(control)

        def finished() -> None:
            self.tasks.remove(task)
            if control and control in self.controls:
                self.controls.remove(control)
            task.deleteLater()
            if self.closing and not self.tasks:
                QTimer.singleShot(0, self.close)

        task.finished.connect(finished)
        task.start()

    def _choose_input(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "入力動画", "", "動画 (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.ts);;すべて (*)"
        )
        if name:
            self.load_input(Path(name))

    def load_input(self, path: Path) -> None:
        if self.job_task or self.probing:
            return
        self.probing = True
        self.input_path = None
        self.input_info = None
        self._update_fps_display()
        self._busy(True)
        self.input_label.setText(str(path))
        self.logs.protect(path)
        self.status.setText("動画情報を取得中…")
        control = JobControl()
        ffmpeg = FFmpegManager(self.ffmpeg_edit.text(), self.ffprobe_edit.text())
        task = Task(lambda: VideoProbe(ffmpeg).probe(path, control), self)

        def ready(info: VideoInfo) -> None:
            self.input_path = path.resolve()
            self.input_info = info
            self._update_fps_display()
            mode = (
                "HDR（処理未対応）"
                if info.color.hdr
                else "SDR / 色タグ要確認"
                if info.color.transfer == "unknown"
                else "SDR"
            )
            audio = ", ".join(f"{t.codec} ({t.language})" for t in info.audio) or "なし"
            self.info_label.setText(
                f"{info.width} × {info.height}  |  {float(info.fps):.6f} fps ({info.fps})  |  {info.codec}\n"
                f"{info.color.bit_depth or '?'}bit  |  {mode}  |  {float(info.duration):.3f} 秒\n"
                f"Audio: {audio}  |  字幕: {len(info.subtitles)}\n"
                f"Color: {info.color.primaries} / {info.color.transfer} / {info.color.matrix}\n"
                "CFR/VFRは開始時の全PTS検査で確定します。"
            )
            self.output_edit.setText(str(path.with_name(path.stem + "_ACVFI.mkv")))
            self.status.setText("入力を読み込みました。プレビューまたはStartで処理できます。")

        task.succeeded.connect(ready)
        task.failed.connect(self._error)
        task.finished.connect(self._probe_finished)
        self._track(task, control)

    def _probe_finished(self) -> None:
        self.probing = False
        self._busy(False)

    def _choose_output(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "出力先", self.output_edit.text(), "Matroska (*.mkv);;MP4 (*.mp4)"
        )
        if name:
            self.output_edit.setText(name)

    def _choose_tool(self, field: QLineEdit) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "実行ファイルを選択", "", "実行ファイル (*.exe);;すべて (*)"
        )
        if name:
            field.setText(name)

    def _load_models(self) -> None:
        self.model_combo.clear()
        try:
            for model in self.registry.list():
                state = "登録済み" if model.trusted else "未登録"
                self.model_combo.addItem(f"{model.name} {model.version} / {state}", model.id)
            self.model_combo.setCurrentIndex(
                max(0, self.model_combo.findData(self.config.model_id))
            )
        except Exception as exc:
            self._error(str(exc))

    def _register_model(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "公式train_log/RIFE_HDv3.pyを選択", "", "RIFE model (RIFE_HDv3.py)"
        )
        if not selected:
            return
        model_dir = Path(selected).parent
        self.status.setText("モデルのハッシュを登録中…")
        self._busy(True)
        model_id = str(self.model_combo.currentData())
        task = Task(lambda: self.registry.register(model_id, model_dir, model_dir.parent), self)
        task.succeeded.connect(lambda _: self._load_models())
        task.failed.connect(self._error)
        task.finished.connect(lambda: self._busy(False))
        self._track(task)

    def _fps_selection(self) -> OutputFPS:
        value = str(self.fps_combo.currentData())
        if value.startswith("source:"):
            return OutputFPS("source", self.config.output_fps, int(value.split(":")[1]))
        return OutputFPS("fixed", self.custom_fps.text() if value == "custom" else value)

    def _update_fps_display(self) -> None:
        custom = self.fps_combo.currentData() == "custom"
        self.custom_fps.setEnabled(custom)
        self.custom_fps.setVisible(custom)
        try:
            selection = self._fps_selection()
            text = (
                "入力後に元FPS × 倍率を表示"
                if selection.mode == "source" and self.input_info is None
                else selection.display(self.input_info.fps if self.input_info else Fraction(1))
            )
            self.fps_result.setText(text)
            self.fps_result.setToolTip(
                "Source整数倍率は原画時刻を出力格子へ配置する基盤です。固定120 fpsとは異なります。"
            )
        except Exception as exc:
            self.fps_result.setText(str(exc))

    def _settings(self) -> AppConfig:
        selection = self._fps_selection()
        config = replace(
            self.config,
            ffmpeg=self.ffmpeg_edit.text().strip(),
            ffprobe=self.ffprobe_edit.text().strip(),
            output_fps=str(parse_fps(selection.fixed)),
            fps_mode=selection.mode,
            source_multiplier=selection.multiplier,
            encoder=self.encoder_combo.currentData(),
            quality=self.quality_combo.currentData(),
            model_id=str(self.model_combo.currentData()),
            processing_scale=float(self.scale_combo.currentData()),
            device=self.device_combo.currentData(),
            scene_protection=self.scene_check.isChecked(),
            audio_mode=self.audio_combo.currentData(),
            preserve_subtitles=self.subtitles_check.isChecked(),
            allow_vfr=self.vfr_check.isChecked(),
        )
        config.validate()
        return config

    def _save_settings(self) -> None:
        try:
            self.config = self._settings()
            self.config_manager.save(self.config)
            self.status.setText("設定を保存しました。")
        except Exception as exc:
            self._error(str(exc))

    def _start(self, preview: bool) -> None:
        if not self.input_path or self.job_task:
            return
        try:
            config = self._settings()
            output = Path(self.output_edit.text())
            if not self.output_edit.text().strip():
                raise ValueError("出力先を指定してください。")
            if preview:
                base = output
                number = 1
                while True:
                    suffix = ".preview" if number == 1 else f".preview-{number}"
                    output = base.with_name(base.stem + suffix + base.suffix)
                    if (
                        not output.exists()
                        and not output.with_name(output.name + ".acvfi-lock").exists()
                    ):
                        break
                    number += 1
            spec = JobSpec(
                self.input_path,
                output,
                config,
                Fraction(str(self.preview_start.value())) if preview else Fraction(0),
                Fraction(self.preview_length.currentData()) if preview else None,
            )
            self.config_manager.save(config)
            self.config = config
        except Exception as exc:
            self._error(str(exc))
            return
        self.control = control = JobControl()
        self.paused = False
        self.pause_button.setText("Pause")
        self._busy(True)
        self.progress_bar.setRange(0, 0)
        task = Task(
            lambda: JobManager(self.registry, self.logs).run(spec, control, task.progress.emit),
            self,
        )
        self.job_task = task
        task.progress.connect(self._progress)
        task.succeeded.connect(self._completed)
        task.failed.connect(self._error)
        task.finished.connect(self._job_finished)
        self._track(task, self.control)

    def _progress(self, progress: Progress) -> None:
        if not self.paused:
            self.status.setText(progress.phase)
        self.pause_button.setEnabled(progress.phase.startswith(("補間", "全フレーム")))
        if progress.total:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(progress.completed * 1000 // progress.total)
        else:
            self.progress_bar.setRange(0, 0)

    def _completed(self, result: JobResult) -> None:
        self.result = result
        self.open_result.setEnabled(True)
        self.open_original.setEnabled(result.reference is not None)
        self.status.setText(
            f"完了: {result.frames:,}フレーム / {result.elapsed:.1f}秒。"
            + (
                "元タイミング参照は同じFPSでフレーム保持・再圧縮した比較用動画です。"
                if result.reference
                else ""
            )
        )

    def _job_finished(self) -> None:
        self.job_task = None
        self.control = None
        self.paused = False
        self.pause_button.setText("Pause")
        self._busy(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def _pause(self) -> None:
        if self.control:
            self.paused = not self.paused
            self.control.pause() if self.paused else self.control.resume()
            self.pause_button.setText("Resume" if self.paused else "Pause")
            self.status.setText(
                "一時停止要求済み（処理境界で停止）" if self.paused else "処理を再開"
            )

    def _cancel(self) -> None:
        if self.control:
            self.control.cancel()
            self.status.setText("キャンセル中…")
            self.cancel_button.setEnabled(False)

    def _error(self, message: str) -> None:
        record = logging.LogRecord("animecinemavfi", logging.ERROR, "", 0, message, (), None)
        self.status.setText(self.logs.formatter.format(record))

    def _detect_gpu(self) -> None:
        control = JobControl()
        task = Task(lambda: GPUManager().detect(control), self)
        task.succeeded.connect(self._gpu_ready)
        task.failed.connect(self._error)
        self._track(task, control)

    def _gpu_ready(self, gpu: GPUInfo) -> None:
        self.gpu_label.setText(
            f"{gpu.name}  |  CUDA: {'利用可能' if gpu.cuda_available else '利用不可'}  |  PyTorch {gpu.torch_version} / CUDA {gpu.cuda_version} / Driver {gpu.driver}"
        )
        if gpu.total_mb is not None and gpu.free_mb is not None:
            self.vram_label.setText(
                f"VRAM 使用中 {gpu.total_mb - gpu.free_mb:,} / 合計 {gpu.total_mb:,} MB（空き {gpu.free_mb:,} MB）"
            )
        else:
            self.vram_label.setText("VRAM: 取得できません / CPU処理は利用可能（PyTorch導入が必要）")

    def _refresh_memory(self) -> None:
        if self.gpu_busy or self.closing:
            return
        self.gpu_busy = True
        task = Task(GPUManager.nvidia_memory, self)

        def ready(data: dict[str, Any]) -> None:
            if data:
                self.vram_label.setText(
                    f"VRAM 使用中 {data['total_mb'] - data['free_mb']:,} / {data['total_mb']:,} MB（空き {data['free_mb']:,} MB）"
                )

        task.succeeded.connect(ready)
        task.finished.connect(lambda: setattr(self, "gpu_busy", False))
        self._track(task)

    @staticmethod
    def _open(path: Path | None) -> None:
        if path and path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and not self.job_task and not self.probing:
            urls = event.mimeData().urls()
            if len(urls) == 1 and urls[0].isLocalFile():
                event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.load_input(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.tasks:
            self.closing = True
            self.memory_timer.stop()
            for control in self.controls:
                control.cancel()
            self.status.setText("処理を終了して閉じています…")
            event.ignore()
        else:
            self.logs.logger.removeHandler(self.gui_handler)
            event.accept()
