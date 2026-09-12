import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import ManagedProcess
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoInfo


@dataclass(frozen=True)
class FrameStamp:
    index: int
    time: Fraction


def cadence_is_variable(index: int, time: Fraction, fps: Fraction, tick: Fraction) -> bool:
    # Container quantization (e.g. 41/42ms in MKV at 24000/1001) is not VFR.
    return abs(time - Fraction(index, 1) / fps) > max(2 * tick, Fraction(1, 100000))


class TimelineIndex:
    def __init__(self, path: Path, info: VideoInfo) -> None:
        self.connection = sqlite3.connect(path)
        self.info = info
        self.origin = Fraction(0)
        self.duration = Fraction(0)
        self.count = 0
        self.vfr = False

    def build(
        self, ffmpeg: FFmpegManager, control: JobControl, progress: Callable[[int], None]
    ) -> None:
        db = self.connection
        db.execute("CREATE TABLE frames (i INTEGER PRIMARY KEY, pts INTEGER NOT NULL UNIQUE)")
        args = [
            ffmpeg.ffprobe,
            "-v",
            "error",
            "-select_streams",
            str(self.info.stream_index),
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp,pkt_duration,duration,width,height,pix_fmt,color_transfer,interlaced_frame",
            "-of",
            "compact=p=0:nk=0",
            media_path(self.info.path),
        ]
        previous: int | None = None
        first: int | None = None
        last_duration = 0
        with ManagedProcess(args, control, label="FFprobe timestamp scan") as proc:
            proc.input.close()
            while raw := proc.output.readline(65536):
                control.checkpoint()
                fields = dict(
                    part.split("=", 1)
                    for part in raw.decode("utf-8", errors="replace").strip().split("|")
                    if "=" in part
                )
                if "best_effort_timestamp" not in fields:
                    continue  # side-data-only records
                if fields.get("color_transfer") in {"smpte2084", "arib-std-b67"}:
                    raise VFIError("HDRフレームを検出しました。v0.1では処理できません。")
                if fields.get("interlaced_frame") == "1":
                    raise VFIError("インターレースフレームを検出しました。")
                for key, expected in (
                    ("width", str(self.info.width)),
                    ("height", str(self.info.height)),
                    ("pix_fmt", self.info.color.pixel_format),
                ):
                    if key in fields and fields[key] != expected:
                        raise VFIError("映像の途中で解像度または画素形式が変わっています。")
                try:
                    pts = int(fields["best_effort_timestamp"])
                except ValueError as exc:
                    raise VFIError(
                        "タイムスタンプ不明のフレームがあります。入力を確認してください。"
                    ) from exc
                if previous is not None and pts <= previous:
                    raise VFIError(
                        "重複または逆行するPTSを検出しました。v0.1では安全に処理できません。"
                    )
                if first is None:
                    first = pts
                    self.origin = pts * self.info.time_base
                normalized = (pts - first) * self.info.time_base
                self.vfr |= cadence_is_variable(
                    self.count, normalized, self.info.fps, self.info.time_base
                )
                db.execute("INSERT INTO frames VALUES (?, ?)", (self.count, pts))
                self.count += 1
                previous = pts
                try:
                    last_duration = int(fields.get("duration", fields.get("pkt_duration", "0")))
                except ValueError:
                    last_duration = 0
                if self.count % 500 == 0:
                    db.commit()
                    progress(self.count)
            proc.finish()
        if not self.count or first is None or previous is None:
            raise VFIError("デコードできるフレームがありません。")
        db.commit()
        tail = last_duration * self.info.time_base if last_duration > 0 else 1 / self.info.fps
        self.duration = (previous - first) * self.info.time_base + tail
        progress(self.count)

    def before(self, time: Fraction) -> int:
        pts = (self.origin + time) / self.info.time_base
        row = self.connection.execute(
            "SELECT i FROM frames WHERE pts <= ? ORDER BY pts DESC LIMIT 1",
            (pts.numerator // pts.denominator,),
        ).fetchone()
        return int(row[0]) if row else 0

    def stamps(self, start: int = 0) -> Iterator[FrameStamp]:
        for index, pts in self.connection.execute(
            "SELECT i, pts FROM frames WHERE i >= ? ORDER BY i", (start,)
        ):
            yield FrameStamp(index, pts * self.info.time_base - self.origin)

    def close(self) -> None:
        self.connection.close()
