import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from animecinemavfi.color.metadata import ColorMetadata
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import capture
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.timing import rational


@dataclass(frozen=True)
class Track:
    index: int
    codec: str
    language: str
    default: bool
    dispositions: tuple[str, ...] = ()


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    stream_index: int
    width: int
    height: int
    fps: Fraction
    nominal_fps: Fraction
    time_base: Fraction
    duration: Fraction
    start_time: Fraction
    codec: str
    color: ColorMetadata
    audio: tuple[Track, ...]
    subtitles: tuple[Track, ...]
    attachments: int
    sar: Fraction
    rotation: int
    field_order: str
    attachment_tracks: tuple[Track, ...] = ()
    sar_known: bool = True

    @property
    def possible_vfr(self) -> bool:
        return self.fps != self.nominal_fps


class VideoProbe:
    def __init__(self, ffmpeg: FFmpegManager) -> None:
        self.ffmpeg = ffmpeg

    @staticmethod
    def parse(data: dict[str, Any], path: Path) -> VideoInfo:
        streams = data.get("streams", [])
        videos = [
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic", 0)
        ]
        if not videos:
            raise VFIError("映像トラックがありません。")
        stream = next((s for s in videos if s.get("disposition", {}).get("default")), videos[0])
        fmt = data.get("format", {})
        fps = rational(stream.get("avg_frame_rate")) or rational(stream.get("r_frame_rate"))
        time_base = rational(stream.get("time_base"))
        if fps <= 0 or time_base <= 0:
            raise VFIError("有効なfps/time_baseを取得できません。")

        def tracks(kind: str) -> tuple[Track, ...]:
            return tuple(
                Track(
                    int(s["index"]),
                    str(s.get("codec_name", "unknown")),
                    str(s.get("tags", {}).get("language", "und")),
                    bool(s.get("disposition", {}).get("default", 0)),
                    tuple(k for k, v in s.get("disposition", {}).items() if v),
                )
                for s in streams
                if s.get("codec_type") == kind
            )

        rotation = int(stream.get("tags", {}).get("rotate", 0))
        for side in stream.get("side_data_list", []):
            if "rotation" in side:
                rotation = int(side["rotation"])
        sar = rational(str(stream.get("sample_aspect_ratio", "unknown")).replace(":", "/"))
        return VideoInfo(
            path.resolve(),
            int(stream["index"]),
            int(stream["width"]),
            int(stream["height"]),
            fps,
            rational(stream.get("r_frame_rate"), fps),
            time_base,
            rational(stream.get("duration", fmt.get("duration"))),
            rational(stream.get("start_time", fmt.get("start_time"))),
            str(stream.get("codec_name", "unknown")),
            ColorMetadata.parse(stream),
            tracks("audio"),
            tracks("subtitle"),
            sum(s.get("codec_type") == "attachment" for s in streams),
            sar or Fraction(1),
            rotation,
            str(stream.get("field_order", "unknown")),
            tracks("attachment"),
            sar > 0,
        )

    def probe(self, path: Path, control: JobControl) -> VideoInfo:
        if not path.is_file():
            raise VFIError("入力動画が見つかりません。")
        raw = capture(
            [
                self.ffmpeg.ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                media_path(path),
            ],
            control,
            label="FFprobe",
        )
        try:
            return self.parse(json.loads(raw), path)
        except (KeyError, ValueError, TypeError) as exc:
            raise VFIError(f"FFprobeのメタデータが不正です: {exc}") from exc
