import json
import logging
import platform
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path

from animecinemavfi import __version__
from animecinemavfi.analysis.scene import SceneDetector, SceneResult
from animecinemavfi.color.metadata import SDRColorPolicy
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, VFIError
from animecinemavfi.core.extensions import (
    BasicMotionDirector,
    ModelRouter,
    MotionDirector,
    SingleModelRouter,
)
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.pair_renderer import PLAN_SIZE, PairRenderer
from animecinemavfi.encoding.audio import AudioMuxer
from animecinemavfi.encoding.encoder import Encoder
from animecinemavfi.encoding.validation import OutputValidator
from animecinemavfi.interpolation.base import VideoInterpolationEngine
from animecinemavfi.interpolation.rife import RIFEEngine
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.utils.logging import Logger
from animecinemavfi.utils.workspace import Workspace, check_disk, publish, validate_output
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoProbe
from animecinemavfi.video.reader import FFmpegReader
from animecinemavfi.video.timeline import TimelineIndex
from animecinemavfi.video.timing import (
    ceil_fraction,
    output_count,
    output_timestamp,
)

logger = logging.getLogger("animecinemavfi")


@dataclass(frozen=True)
class JobSpec:
    input: Path
    output: Path
    config: AppConfig
    preview_start: Fraction = Fraction(0)
    preview_duration: Fraction | None = None


@dataclass(frozen=True)
class Progress:
    phase: str
    completed: int = 0
    total: int = 0


@dataclass(frozen=True)
class JobResult:
    output: Path
    reference: Path | None
    report: Path
    frames: int
    interpolated: int
    protected: int
    elapsed: float
    warnings: tuple[str, ...]


EngineFactory = Callable[[JobControl, GPUInfo], VideoInterpolationEngine]


class JobManager:
    """Synchronous core; callers run it on a worker thread. Engines are replaceable."""

    def __init__(
        self,
        registry: ModelRegistry,
        logs: Logger | None = None,
        engine_factory: EngineFactory | None = None,
        director: MotionDirector | None = None,
        router_factory: Callable[[VideoInterpolationEngine], ModelRouter] | None = None,
    ) -> None:
        self.registry = registry
        self.logs = logs
        self.engine_factory = engine_factory
        self.director = director or BasicMotionDirector()
        self.router_factory = router_factory or SingleModelRouter

    def run(
        self,
        spec: JobSpec,
        control: JobControl,
        on_progress: Callable[[Progress], None] = lambda p: None,
    ) -> JobResult:
        start_clock = time.monotonic()
        try:
            return self._run(spec, control, on_progress, start_clock)
        except Cancelled:
            logger.info("Job cancelled by user")
            raise
        except Exception:
            logger.exception(
                "Job ended unsuccessfully (elapsed=%.2fs)", time.monotonic() - start_clock
            )
            raise

    def _run(
        self,
        spec: JobSpec,
        control: JobControl,
        on_progress: Callable[[Progress], None],
        start_clock: float,
    ) -> JobResult:
        config = replace(spec.config)
        config.validate()
        if spec.preview_start < 0 or (
            spec.preview_duration is not None and spec.preview_duration <= 0
        ):
            raise VFIError("プレビューの開始位置・長さが不正です。")
        output = validate_output(spec.input, spec.output)
        report_path = output.with_name(output.name + ".report.json")
        reference = (
            output.with_name(output.stem + ".original" + output.suffix)
            if spec.preview_duration
            else None
        )
        for target in (report_path, reference):
            if target and target.exists():
                raise VFIError(
                    "比較動画またはレポートが既に存在します。別の出力名を指定してください。"
                )
        if self.logs:
            self.logs.protect(spec.input, output, output.parent, self.registry.path)
        on_progress(Progress("入力・環境の確認"))
        ffmpeg = FFmpegManager(config.ffmpeg, config.ffprobe)
        versions = ffmpeg.validate(control)
        available = ffmpeg.encoders(control)
        if config.encoder not in available:
            raise VFIError(
                f"このFFmpegに{config.encoder}がありません。別のEncoderを選択してください。"
            )
        if reference and "libx264" not in available:
            raise VFIError("比較プレビューにはlibx264対応FFmpegが必要です。")
        info = VideoProbe(ffmpeg).probe(spec.input, control)
        fps = config.fps_selection.resolve(info.fps)
        config.output_fps = str(fps)
        warnings = SDRColorPolicy().validate(info.color)
        warnings += AudioMuxer.validate(info, output, config)
        if info.width % 2 or info.height % 2:
            raise VFIError("v0.1のYUV420出力には幅・高さとも偶数が必要です。")
        if info.rotation % 360:
            raise VFIError(
                "回転メタデータ付き動画はv0.1対象外です。向きを確定した動画を入力してください。"
            )
        if info.field_order not in {"progressive", "unknown"}:
            raise VFIError("インターレース映像はv0.1対象外です。先にデインターレースしてください。")
        if not self.engine_factory:
            model_preflight = self.registry.get(config.model_id)
            if self.logs:
                self.logs.protect(model_preflight.path, model_preflight.repository_path)
            model_preflight.validate_files()
        gpu = GPUManager().detect(control)
        if not self.engine_factory and gpu.torch_version == "未導入":
            raise VFIError(
                "PyTorchを利用できません。READMEのPyTorchセットアップを確認してください。"
            )
        if config.device == "cuda" and not gpu.cuda_available:
            raise VFIError(
                "CUDAを利用できません。GPU・ドライバー・PyTorch CUDA版を確認してください。"
            )
        logger.info(
            "AnimeCinemaVFI %s OS=%s GPU=%s FFmpeg=%s",
            __version__,
            platform.platform(),
            asdict(gpu),
            versions,
        )
        safe_info = asdict(info)
        safe_info.pop("path")
        logger.info("Input metadata=%s Output settings=%s", safe_info, asdict(config))
        check_disk(output.parent, config.reserve_disk_mb)
        with Workspace(output) as work, ExitStack() as stack:
            if self.logs:
                self.logs.protect(work)
            timeline = TimelineIndex(work / "timeline.sqlite", info)
            stack.callback(timeline.close)

            def scan_progress(count: int) -> None:
                check_disk(work, config.reserve_disk_mb)
                on_progress(Progress(f"全フレームの時刻確認: {count:,}フレーム"))

            timeline.build(ffmpeg, control, scan_progress)
            if timeline.vfr:
                message = "VFRまたは不規則なPTSを検出しました。実PTSからCFR化する実験対応です。原画時刻には出力1フレーム未満の丸めが生じます。"
                if not config.allow_vfr:
                    raise VFIError(message + " 確認後「VFR実験処理を許可」を有効にしてください。")
                warnings.append(message)
            if (
                config.fps_mode == "source"
                and not timeline.vfr
                and ((1 / info.fps) / info.time_base).denominator != 1
            ):
                warnings.append(
                    "入力PTSはコンテナの時刻精度で丸められています。Source倍率でも全原画PTSが出力格子に一致するとは限りません。"
                )
            if (fps / info.fps).denominator != 1:
                warnings.append(
                    "出力FPSは入力FPSの整数倍ではないため、全原画を元の時刻に配置することはできません。"
                )
            warnings.append(
                "v0.1はコマ打ち・止め絵の意図を解析しません。シーン保護以外は基本補間です。"
            )
            for message in warnings:
                logger.warning(message)
            start = spec.preview_start if spec.preview_duration else Fraction(0)
            duration = min(spec.preview_duration or timeline.duration, timeline.duration - start)
            if duration <= 0:
                raise VFIError("プレビュー開始位置が動画の終わり以降です。")
            if start * fps != int(start * fps):
                message = "プレビュー開始位置が出力格子からずれるため、一部の元フレームは出力時刻と一致しません。"
                warnings.append(message)
                logger.warning(message)
            total = output_count(duration, fps)
            first = timeline.before(start)
            # One frame after the last requested time is needed for interpolation.
            final_time = start + output_timestamp(total - 1, fps)
            last = min(timeline.before(final_time) + 1, timeline.count - 1)
            source_count = last - first + 1
            on_progress(Progress("RIFEモデルを準備"))
            if self.engine_factory:
                engine = self.engine_factory(control, gpu)
            else:
                model = self.registry.get(config.model_id)
                if self.logs:
                    self.logs.protect(model.path, model.repository_path)
                device = config.device
                if device == "auto":
                    device = "cuda" if gpu.cuda_available else "cpu"
                if device == "cpu":
                    logger.warning("CPUでRIFEを処理します。長い動画は非常に時間がかかります。")
                engine = RIFEEngine(model, control, device, config.processing_scale)
            stack.callback(engine.close)
            engine.load()
            router = self.router_factory(engine)
            reader = FFmpegReader(ffmpeg, info, control, first, source_count)
            stack.callback(reader.close)
            silent = work / "video.mp4"
            encoder = Encoder(ffmpeg, info, silent, fps, config, control)
            stack.callback(encoder.close)
            original_encoder: Encoder | None = None
            original_silent = work / "original.mp4"
            if reference:
                original_encoder = Encoder(
                    ffmpeg,
                    info,
                    original_silent,
                    fps,
                    replace(config, encoder="libx264", quality="high"),
                    control,
                )
                stack.callback(original_encoder.close)
            detector = SceneDetector(config.scene_threshold)
            stamps = timeline.stamps(first)
            stack.callback(stamps.close)
            left_stamp = next(stamps)
            left = reader.read(left_stamp.time)
            right_stamp = next(stamps, None) if source_count > 1 else None
            right = reader.read(right_stamp.time) if right_stamp else None
            scene = (
                detector.detect(left.data, right.data)
                if right is not None
                else SceneResult(False, 0)
            )
            interpolated = protected = 0
            last_update = 0.0
            renderer = PairRenderer(self.director, router, control)
            index = 0
            while index < total:
                control.checkpoint()
                timestamp = start + output_timestamp(index, fps)
                while right_stamp and timestamp >= right_stamp.time:
                    assert right is not None
                    left_stamp, left = right_stamp, right
                    if left_stamp.index >= last:
                        right_stamp, right = None, None
                    else:
                        right_stamp = next(stamps)
                        right = reader.read(right_stamp.time)
                    scene = (
                        detector.detect(left.data, right.data)
                        if right is not None
                        else SceneResult(False, 0)
                    )
                pair_end = (
                    min(total, ceil_fraction((right_stamp.time - start) * fps))
                    if right_stamp
                    else total
                )
                end = min(pair_end, index + PLAN_SIZE)
                times = [start + output_timestamp(i, fps) for i in range(index, end)]
                for rendered in renderer.render(left, right, times, scene, config.scene_protection):
                    encoder.write(rendered.frame)
                    if original_encoder:
                        original_encoder.write(rendered.original)
                    interpolated += int(rendered.interpolated)
                    protected += int(rendered.protected)
                    index += 1
                    now = time.monotonic()
                    if now - last_update >= 0.2 or index == total:
                        check_disk(work, config.reserve_disk_mb)
                        on_progress(Progress("補間・エンコード", index, total))
                        last_update = now
            while reader.remaining:
                reader.read(next(stamps).time)
            reader.finish()
            encoder.finish()
            if original_encoder:
                original_encoder.finish()
            on_progress(Progress("音声・字幕の結合"))
            final = work / ("final" + output.suffix)
            muxer = AudioMuxer()
            muxer.mux(
                ffmpeg, info, silent, final, timeline.origin, start, duration, config, control
            )
            reference_final = work / ("reference" + output.suffix)
            if reference:
                muxer.mux(
                    ffmpeg,
                    info,
                    original_silent,
                    reference_final,
                    timeline.origin,
                    start,
                    duration,
                    config,
                    control,
                )
            on_progress(Progress("出力検証"))
            OutputValidator.verify(ffmpeg, final, info, config, control, total)
            if reference:
                OutputValidator.verify(ffmpeg, reference_final, info, config, control, total)
            control.checkpoint()
            elapsed = time.monotonic() - start_clock
            report_data = {
                "application_version": __version__,
                "os": platform.platform(),
                "gpu": asdict(gpu),
                "tools": versions,
                "settings": asdict(config),
                "input": safe_info,
                "actual_duration": str(duration),
                "origin": str(timeline.origin),
                "preview_start": str(start),
                "vfr_detected": timeline.vfr,
                "output_frames": total,
                "interpolated_frames": interpolated,
                "protected_frames": protected,
                "elapsed_seconds": elapsed,
                "warnings": warnings,
                "model_id": config.model_id,
                "engine_statistics": engine.statistics() if isinstance(engine, RIFEEngine) else {},
            }
            report = work / "report.json"
            # Executable settings can contain private absolute paths. Store only the basename.
            for key in ("ffmpeg", "ffprobe"):
                report_data["settings"][key] = Path(getattr(config, key)).name  # type: ignore[index]
            report.write_text(
                json.dumps(report_data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            # Publish video last; rollback only the newly created companion files on failure.
            published: list[Path] = []
            try:
                publish(report, report_path)
                published.append(report_path)
                if reference:
                    publish(reference_final, reference)
                    published.append(reference)
                publish(final, output)
            except Exception:
                for target in published:
                    target.unlink(missing_ok=True)
                raise
        on_progress(Progress("完了", total, total))
        logger.info(
            "Completed frames=%d interpolated=%d protected=%d elapsed=%.2fs",
            total,
            interpolated,
            protected,
            elapsed,
        )
        return JobResult(
            output, reference, report_path, total, interpolated, protected, elapsed, tuple(warnings)
        )
