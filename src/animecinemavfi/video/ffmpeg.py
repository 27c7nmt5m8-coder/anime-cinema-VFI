import shutil
from dataclasses import dataclass
from pathlib import Path

from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.process import capture


@dataclass
class FFmpegManager:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    def validate(self, control: JobControl) -> dict[str, str]:
        info = {}
        for name, value in (("ffmpeg", self.ffmpeg), ("ffprobe", self.ffprobe)):
            executable = shutil.which(value)
            if not executable and not Path(value).is_file():
                raise VFIError(f"{name}が見つかりません。設定で実行ファイルを指定してください。")
            info[name] = (
                capture([value, "-version"], control, label=name)
                .decode("utf-8", errors="replace")
                .splitlines()[0]
            )
        return info

    def encoders(self, control: JobControl) -> set[str]:
        output = capture(
            [self.ffmpeg, "-hide_banner", "-encoders"], control, label="FFmpeg encoder check"
        ).decode("utf-8", errors="replace")
        return {
            parts[1]
            for line in output.splitlines()
            if len(parts := line.split()) >= 2 and parts[0].startswith("V")
        }
