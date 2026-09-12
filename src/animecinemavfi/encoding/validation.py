import json
from fractions import Fraction
from pathlib import Path

from animecinemavfi.color.encoding import ColorEncodingOptions, verify_color
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import capture
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoInfo, VideoProbe
from animecinemavfi.video.timing import parse_fps


class OutputValidator:
    @staticmethod
    def verify(
        ffmpeg: FFmpegManager,
        path: Path,
        info: VideoInfo,
        config: AppConfig,
        control: JobControl,
        expected_count: int,
    ) -> None:
        output = VideoProbe(ffmpeg).probe(path, control)
        if (output.width, output.height) != (info.width, info.height) or not path.stat().st_size:
            raise VFIError("出力映像の検証に失敗しました。")
        if len(output.audio) != len(info.audio):
            raise VFIError("音声トラック数が一致しません。出力を完了扱いにしません。")
        if config.preserve_subtitles and len(output.subtitles) != len(info.subtitles):
            raise VFIError("字幕トラック数が一致しません。出力を完了扱いにしません。")
        if path.suffix.lower() == ".mkv" and output.attachments != info.attachments:
            raise VFIError("添付ファイル数が一致しません。")
        if [a.language for a in output.audio] != [a.language for a in info.audio]:
            raise VFIError("音声トラックの言語情報が一致しません。")
        for kind, expected, actual in (
            ("音声", info.audio, output.audio),
            ("字幕", info.subtitles if config.preserve_subtitles else (), output.subtitles),
        ):
            if len(expected) != len(actual):
                raise VFIError(f"{kind}トラック数が一致しません。")
            for before, after in zip(expected, actual, strict=True):
                if before.language != after.language or set(before.dispositions) != set(
                    after.dispositions
                ):
                    raise VFIError(f"{kind}トラックのlanguage/dispositionが一致しません。")
                codec = "aac" if kind == "音声" and config.audio_mode == "aac" else before.codec
                if after.codec != codec:
                    raise VFIError(f"{kind}トラックのcodecが一致しません。")
        color = ColorEncodingOptions.sdr(info.color, info.height, info.sar)
        verify_color(output.color, color.expected)
        if not output.sar_known or output.sar != color.sar:
            raise VFIError(f"出力SARが一致しません: expected={color.sar}, actual={output.sar}")
        expected_fps = parse_fps(config.output_fps)
        tolerance = (
            Fraction(0)
            if path.suffix.lower() == ".mp4"
            else max(Fraction(1, 10000), expected_fps**2 / 1_000_000_000)
        )
        if abs(output.fps - expected_fps) > tolerance:
            raise VFIError("出力FPSが設定値と一致しません。")
        packets = capture(
            [
                ffmpeg.ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_packets",
                "-show_entries",
                "stream=nb_read_packets",
                "-of",
                "json",
                media_path(path),
            ],
            control,
            timeout=3600,
            label="FFprobe output packet verification",
        )
        count = int(json.loads(packets)["streams"][0]["nb_read_packets"])
        if count != expected_count:
            raise VFIError(f"出力フレーム数が不一致です（予定 {expected_count} / 実際 {count}）。")
