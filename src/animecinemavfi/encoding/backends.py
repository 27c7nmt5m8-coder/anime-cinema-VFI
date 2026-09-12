from dataclasses import dataclass

from animecinemavfi.color.encoding import (
    ColorEncodingOptions,
    EncoderColorPolicy,
    NVENCColorPolicy,
    X264ColorPolicy,
    X265ColorPolicy,
)
from animecinemavfi.core.errors import VFIError

PRESETS = {"fast": (23, "fast", "p3"), "balanced": (20, "medium", "p5"), "high": (17, "slow", "p6")}


@dataclass(frozen=True)
class EncoderCapabilities:
    codec: str
    hardware: str
    pixel_formats: tuple[str, ...] = ("yuv420p",)
    bit_depths: tuple[int, ...] = (8,)
    hdr: bool = False
    color_metadata: bool = True


@dataclass(frozen=True)
class EncoderBackend:
    name: str
    capabilities: EncoderCapabilities
    color_policy: EncoderColorPolicy

    def quality_options(self, quality: str) -> list[str]:
        crf, preset, _ = PRESETS[quality]
        return ["-preset", preset, "-crf", str(crf)]

    def options(self, quality: str, color: ColorEncodingOptions) -> list[str]:
        caps = self.capabilities
        if color.expected.hdr or color.expected.bit_depth not in caps.bit_depths:
            raise VFIError("v0.1 EncoderではHDR/高bit depth出力は許可されていません。")
        if color.expected.pixel_format not in caps.pixel_formats:
            raise VFIError("Encoderで未対応のpixel formatです。")
        return [
            "-c:v",
            self.name,
            "-pix_fmt",
            color.expected.pixel_format,
            *self.quality_options(quality),
            *self.color_policy.options(color),
        ]


class NVENCBackend(EncoderBackend):
    def quality_options(self, quality: str) -> list[str]:
        crf, _, preset = PRESETS[quality]
        return ["-preset", preset, "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]


BACKENDS: dict[str, EncoderBackend] = {
    "libx264": EncoderBackend(
        "libx264", EncoderCapabilities("h264", "software"), X264ColorPolicy()
    ),
    "libx265": EncoderBackend(
        "libx265", EncoderCapabilities("hevc", "software"), X265ColorPolicy()
    ),
    "h264_nvenc": NVENCBackend(
        "h264_nvenc", EncoderCapabilities("h264", "nvidia"), NVENCColorPolicy()
    ),
    "hevc_nvenc": NVENCBackend(
        "hevc_nvenc", EncoderCapabilities("hevc", "nvidia"), NVENCColorPolicy()
    ),
}


def get_backend(name: str) -> EncoderBackend:
    try:
        return BACKENDS[name]
    except KeyError as exc:
        raise VFIError(f"未登録のEncoder backendです: {name}") from exc
