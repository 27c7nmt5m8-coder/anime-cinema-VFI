import argparse
import json
import signal
import sys
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path

from animecinemavfi.core.config import AppConfig, user_data_dir
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.diagnostics import diagnose
from animecinemavfi.core.job import JobManager, JobSpec
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.utils.logging import Logger
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoProbe


def main() -> int:
    parser = argparse.ArgumentParser(prog="animecinemavfi")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui")
    diagnostics = sub.add_parser("diagnose")
    diagnostics.add_argument(
        "--encoders", action="store_true", help="実エンコードとVUI検証（NVENC含む）"
    )
    diagnostics.add_argument("--output", type=Path, help="診断JSON保存先（上書き禁止）")
    probe = sub.add_parser("probe")
    probe.add_argument("input", type=Path)
    register = sub.add_parser("register-model")
    register.add_argument("directory", type=Path)
    register.add_argument("--repository", type=Path)
    register.add_argument("--registry", type=Path)
    process = sub.add_parser("process")
    process.add_argument("input", type=Path)
    process.add_argument("output", type=Path)
    fps_group = process.add_mutually_exclusive_group()
    fps_group.add_argument("--fps", default="120")
    fps_group.add_argument("--source-multiplier", type=int, help="元FPSの整数倍率（例:5）")
    process.add_argument(
        "--encoder", default="libx264", choices=["libx264", "libx265", "h264_nvenc", "hevc_nvenc"]
    )
    process.add_argument("--quality", default="high", choices=["high", "balanced", "fast"])
    process.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    process.add_argument("--scale", default=1.0, type=float, choices=[1.0, 0.5, 0.25])
    process.add_argument("--preview-start", default="0")
    process.add_argument("--preview-seconds")
    process.add_argument("--registry", type=Path)
    process.add_argument("--allow-vfr", action="store_true")
    process.add_argument("--audio-aac", action="store_true")
    process.add_argument("--drop-subtitles", action="store_true")
    for child in (probe, process, diagnostics):
        child.add_argument("--ffmpeg", default="ffmpeg")
        child.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    logs = Logger(user_data_dir() / "logs")
    if args.command in (None, "gui"):
        from PySide6.QtWidgets import QApplication

        from animecinemavfi.ui.window import MainWindow

        app = QApplication(sys.argv[:1])
        app.setApplicationName("AnimeCinemaVFI")
        window = MainWindow(logs)
        window.show()
        return app.exec()
    control = JobControl()
    signal.signal(signal.SIGINT, lambda *_: control.cancel())
    try:
        if args.command == "diagnose":
            info = diagnose(
                FFmpegManager(args.ffmpeg, args.ffprobe), control, encoders=args.encoders
            )
            text = json.dumps(info, ensure_ascii=False, indent=2)
            if args.output:
                with args.output.open("x", encoding="utf-8") as handle:
                    handle.write(text + "\n")
            print(text)
            if any(item["status"] == "failed" for item in info.get("encoder_tests", [])):
                return 1
        elif args.command == "probe":
            video_info = VideoProbe(FFmpegManager(args.ffmpeg, args.ffprobe)).probe(
                args.input, control
            )
            print(json.dumps(asdict(video_info), default=str, ensure_ascii=False, indent=2))
        elif args.command == "register-model":
            registry = ModelRegistry(args.registry)
            model_id = AppConfig().model_id
            model_spec = registry.register(
                model_id, args.directory, args.repository or args.directory.parent
            )
            print(f"Registered {model_spec.name} {model_spec.version}")
        else:
            config = replace(
                AppConfig(),
                output_fps=args.fps,
                fps_mode="source" if args.source_multiplier is not None else "fixed",
                source_multiplier=args.source_multiplier
                if args.source_multiplier is not None
                else 5,
                encoder=args.encoder,
                quality=args.quality,
                device=args.device,
                processing_scale=args.scale,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
                allow_vfr=args.allow_vfr,
                audio_mode="aac" if args.audio_aac else "copy",
                preserve_subtitles=not args.drop_subtitles,
            )
            spec = JobSpec(
                args.input,
                args.output,
                config,
                Fraction(args.preview_start),
                Fraction(args.preview_seconds) if args.preview_seconds else None,
            )
            result = JobManager(ModelRegistry(args.registry), logs).run(
                spec, control, lambda p: print(f"{p.phase}: {p.completed}/{p.total}", flush=True)
            )
            print(f"Completed: {result.output}")
        return 0
    except Exception as exc:
        logs.logger.exception("Command failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 130 if control.cancelled else 1


if __name__ == "__main__":
    raise SystemExit(main())
