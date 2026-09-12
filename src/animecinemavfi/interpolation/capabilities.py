from dataclasses import dataclass
from typing import Any

from animecinemavfi.core.errors import VFIError
from animecinemavfi.video.frame import FrameFormat, VideoFrame


@dataclass(frozen=True)
class EngineCapabilities:
    pixel_formats: tuple[str, ...] = ("rgb24",)
    dtypes: tuple[str, ...] = ("uint8",)
    bit_depths: tuple[int, ...] = (8,)
    matrices: tuple[str, ...] = ("gbr",)
    ranges: tuple[str, ...] = ("pc",)
    hdr: bool = False
    wide_gamut: bool = False
    arbitrary_timestep: bool = True
    multiple_timesteps: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineCapabilities":
        if not isinstance(data, dict):
            raise ValueError("Invalid frame capabilities")
        values = dict(data)
        for name in ("pixel_formats", "dtypes", "bit_depths", "matrices", "ranges"):
            if name in values:
                if not isinstance(values[name], (list, tuple)):
                    raise ValueError("Invalid capability list")
                values[name] = tuple(values[name])
        for name in ("hdr", "wide_gamut", "arbitrary_timestep", "multiple_timesteps"):
            if name in values and type(values[name]) is not bool:
                raise ValueError("Invalid capability flag")
        return cls(**values)

    def supports(self, format: FrameFormat) -> bool:
        return (
            format.pixel_format in self.pixel_formats
            and format.dtype in self.dtypes
            and format.bit_depth in self.bit_depths
            and format.matrix in self.matrices
            and format.range in self.ranges
            and format.channels == ("R", "G", "B")
            and (self.hdr or not format.hdr)
            and (self.wide_gamut or format.color_primaries != "bt2020")
        )

    def validate_pair(self, left: VideoFrame, right: VideoFrame) -> None:
        if not self.supports(left.format) or not self.supports(right.format):
            raise VFIError("このVFI Engineでは入力FrameFormat/HDR/bit depthを扱えません。")
        if left.format != right.format or left.data.shape != right.data.shape:
            raise VFIError("補間ペアの形式・解像度が一致しません。")
        if right.timestamp <= left.timestamp:
            raise VFIError("補間ペアのタイムスタンプが逆順または同一です。")
