from fractions import Fraction

import numpy as np

from animecinemavfi.color.encoding import ColorEncodingOptions
from animecinemavfi.color.metadata import SDRColorPolicy
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import ManagedProcess, read_exact
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.frame import VideoFrame
from animecinemavfi.video.probe import VideoInfo


class FFmpegReader:
    def __init__(
        self,
        ffmpeg: FFmpegManager,
        info: VideoInfo,
        control: JobControl,
        first_frame: int,
        frame_count: int,
    ) -> None:
        self.format = ColorEncodingOptions.sdr(info.color, info.height, info.sar).internal_format
        self.info = info
        self.control = control
        self.remaining = frame_count
        filters = (
            f"trim=start_frame={first_frame}:end_frame={first_frame + frame_count},"
            + SDRColorPolicy().decode_filter(info.color, info.height)
        )
        self.proc = ManagedProcess(
            [
                ffmpeg.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-xerror",
                "-threads",
                "2",
                "-noautorotate",
                "-i",
                media_path(info.path),
                "-map",
                f"0:{info.stream_index}",
                "-an",
                "-sn",
                "-dn",
                "-vf",
                filters,
                "-filter_threads",
                "1",
                "-fps_mode",
                "passthrough",
                "-frames:v",
                str(frame_count),
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            control,
            label="FFmpeg decode",
        )
        self.proc.input.close()

    def read(self, timestamp: Fraction) -> VideoFrame:
        self.control.checkpoint()
        size = self.info.width * self.info.height * 3
        data = read_exact(self.proc.output, size)
        self.control.raise_if_cancelled()
        if len(data) != size:
            if self.proc.process.poll() not in (None, 0):
                raise self.proc.error()
            raise VFIError("デコードが途中で終了しました。PTS索引とフレーム数が一致しません。")
        self.remaining -= 1
        pixels = np.frombuffer(data, np.uint8).reshape(self.info.height, self.info.width, 3)
        return VideoFrame(pixels, timestamp, self.format)

    def finish(self) -> None:
        if self.remaining:
            raise VFIError("デコードしたフレーム数が予定数と一致しません。")
        self.proc.finish()

    def close(self) -> None:
        self.proc.close()
