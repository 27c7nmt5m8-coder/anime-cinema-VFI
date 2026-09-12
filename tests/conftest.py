import os
import shutil
import subprocess
from pathlib import Path

import pytest

from animecinemavfi.core.control import JobControl
from animecinemavfi.core.gpu import GPUInfo
from animecinemavfi.interpolation.base import Frame, VideoInterpolationEngine

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestBlendEngine(VideoInterpolationEngine):
    """Deterministic test double. Never offered as an AI engine in the app."""

    __test__ = False

    def load(self):
        pass

    def interpolate(self, left, right, timestep) -> Frame:
        data = (
            (left.data.astype(float) * (1 - float(timestep)) + right.data * float(timestep))
            .round()
            .astype("uint8")
        )

        return Frame(
            data, left.timestamp + (right.timestamp - left.timestamp) * timestep, left.format
        )

    def close(self):
        pass


def fake_factory(control: JobControl, gpu: GPUInfo) -> VideoInterpolationEngine:
    return TestBlendEngine()


@pytest.fixture
def ffmpeg_available():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe unavailable")


def run_ffmpeg(args: list[str]) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
        timeout=45,
    )


@pytest.fixture
def sample_factory(tmp_path, ffmpeg_available):
    def make(name="sample.mp4", fps="24000/1001", duration="1.001", audio=1) -> Path:
        output = tmp_path / name
        args = ["-f", "lavfi", "-i", f"testsrc2=size=128x72:rate={fps}:duration={duration}"]
        for i in range(audio):
            args += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={440 + i * 220}:sample_rate=48000:duration={duration}",
            ]
        args += ["-map", "0:v"]
        for i in range(audio):
            args += [
                "-map",
                f"{i + 1}:a",
                f"-metadata:s:a:{i}",
                "language=" + ("jpn" if i == 0 else "eng"),
            ]
        args += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(output),
        ]
        run_ffmpeg(args)
        return output

    return make


@pytest.fixture
def probe_data():
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24000/1001",
                "r_frame_rate": "24000/1001",
                "time_base": "1/24000",
                "duration": "10.01",
                "start_time": "0.5",
                "pix_fmt": "yuv420p",
                "sample_aspect_ratio": "1:1",
                "color_primaries": "bt709",
                "color_transfer": "bt709",
                "color_space": "bt709",
            },
            {"index": 1, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "jpn"}},
            {"index": 2, "codec_type": "audio", "codec_name": "aac", "tags": {"language": "eng"}},
            {"index": 3, "codec_type": "subtitle", "codec_name": "subrip"},
        ],
        "format": {"duration": "10.5"},
    }
