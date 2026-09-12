import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from animecinemavfi.core.errors import VFIError
from animecinemavfi.video.output_fps import OutputFPS


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "AnimeCinemaVFI"


@dataclass
class AppConfig:
    schema_version: int = 1
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    output_fps: str = "120"
    fps_mode: str = "fixed"
    source_multiplier: int = 5
    encoder: str = "libx264"
    quality: str = "high"
    device: str = "auto"
    processing_scale: float = 1.0
    scene_protection: bool = True
    scene_threshold: float = 0.32
    audio_mode: str = "copy"
    preserve_subtitles: bool = True
    allow_vfr: bool = False
    model_id: str = "practical-rife-4.25"
    reserve_disk_mb: int = 512

    def validate(self) -> None:
        expected = AppConfig()
        for item in fields(self):
            value, default = getattr(self, item.name), getattr(expected, item.name)
            if type(value) is not type(default):
                raise VFIError(f"設定の型が不正です: {item.name}")
        if self.schema_version != 1:
            raise VFIError("設定ファイルのバージョンが未対応です。")
        self.fps_selection.validate()
        for field, values in {
            "encoder": {"libx264", "libx265", "h264_nvenc", "hevc_nvenc"},
            "quality": {"fast", "balanced", "high"},
            "device": {"auto", "cuda", "cpu"},
            "audio_mode": {"copy", "aac"},
        }.items():
            if getattr(self, field) not in values:
                raise VFIError(f"設定が不正です: {field}")
        if self.processing_scale not in {1.0, 0.5, 0.25}:
            raise VFIError("processing_scaleは1.0 / 0.5 / 0.25から選択してください。")
        if not 0 < self.scene_threshold < 1 or self.reserve_disk_mb < 16:
            raise VFIError("シーン閾値またはディスク予約値が不正です。")

    @property
    def fps_selection(self) -> OutputFPS:
        return OutputFPS(self.fps_mode, self.output_fps, self.source_multiplier)


class ConfigManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("object required")
            config = AppConfig(**data)
            config.validate()
            return config
        except (OSError, ValueError, TypeError) as exc:
            raise VFIError(f"設定を読み込めません。config.jsonを確認してください: {exc}") from exc

    def save(self, config: AppConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, self.path)
