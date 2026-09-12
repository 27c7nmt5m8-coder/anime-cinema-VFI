from fractions import Fraction
from pathlib import Path

from animecinemavfi.color.encoding import ColorEncodingOptions
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.encoding.backends import get_backend
from animecinemavfi.interpolation.base import Frame
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import ManagedProcess, write_all
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoInfo


class Encoder:
    def __init__(
        self,
        ffmpeg: FFmpegManager,
        info: VideoInfo,
        output: Path,
        fps: Fraction,
        config: AppConfig,
        control: JobControl,
    ) -> None:
        self.control = control
        color = ColorEncodingOptions.sdr(info.color, info.height, info.sar)
        self.format = color.internal_format
        self.shape = (info.height, info.width, 3)
        backend = get_backend(config.encoder)
        args = [
            ffmpeg.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{info.width}x{info.height}",
            "-framerate",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            color.filter,
            "-filter_threads",
            "1",
            "-fps_mode",
            "passthrough",
            "-enc_time_base",
            str(1 / fps),
            "-threads",
            "2",
        ]
        args += backend.options(config.quality, color)
        # MP4 intermediate keeps precise rational timestamps (MKV defaults to 1ms).
        args += [
            "-video_track_timescale",
            str(fps.numerator),
        ]
        if backend.capabilities.codec == "hevc":
            args += ["-tag:v", "hvc1"]
        args += [media_path(output)]
        self.proc = ManagedProcess(args, control, label="FFmpeg encode")

    def write(self, frame: Frame) -> None:
        self.control.checkpoint()
        if frame.format != self.format or frame.data.shape != self.shape:
            raise VFIError("Encoder入力のFrameFormat/解像度が一致しません。")
        try:
            write_all(self.proc.input, frame.data.tobytes())
        except (BrokenPipeError, OSError) as exc:
            self.control.raise_if_cancelled()
            raise self.proc.error() from exc

    def finish(self) -> None:
        try:
            self.proc.input.close()
        except OSError as exc:
            raise VFIError("エンコーダーへの入力を終了できませんでした。") from exc
        self.proc.finish(timeout=300)

    def close(self) -> None:
        self.proc.close()
