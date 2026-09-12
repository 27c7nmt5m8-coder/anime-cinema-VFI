"""Frame storage precision, signal depth and exact timestamps are separate concepts."""

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal, TypeAlias

import numpy as np
from numpy.typing import NDArray

from animecinemavfi.core.errors import VFIError

FrameData: TypeAlias = NDArray[np.uint8 | np.uint16 | np.float16 | np.float32]
FrameDType: TypeAlias = Literal["uint8", "uint16", "float16", "float32"]


@dataclass(frozen=True)
class FrameFormat:
    dtype: FrameDType = "uint8"
    bit_depth: int = 8
    channels: tuple[str, ...] = ("R", "G", "B")
    pixel_format: str = "rgb24"
    color_primaries: str = "unknown"
    transfer: str = "unknown"
    matrix: str = "gbr"
    range: str = "pc"

    def __post_init__(self) -> None:
        sizes = {"uint8": 8, "uint16": 16, "float16": 16, "float32": 32}
        if (
            self.dtype not in sizes
            or type(self.bit_depth) is not int
            or not 1 <= self.bit_depth <= sizes[self.dtype]
        ):
            raise VFIError("FrameFormatの型・bit depthが不正です。")
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise VFIError("FrameFormatのchannelsが不正です。")

    @property
    def hdr(self) -> bool:
        return self.transfer in {"smpte2084", "arib-std-b67"}


@dataclass(frozen=True, eq=False)
class VideoFrame:
    """Packed HWC data with source-relative PTS. Consumers must not mutate pixels.

    Describing uint16/float does not imply an implemented HDR conversion.
    Planar or device storage can later be introduced behind this boundary.
    """

    data: FrameData
    timestamp: Fraction
    format: FrameFormat

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, Fraction):
            raise VFIError("フレーム時刻にはFractionを指定してください。")
        if self.data.dtype.name != self.format.dtype:
            raise VFIError("FrameFormatと画素データのdtypeが一致しません。")
        if self.data.ndim != 3 or self.data.shape[2] != len(self.format.channels):
            raise VFIError("FrameFormatとHWC画素配列の形状が一致しません。")
        if min(self.data.shape[:2]) < 1:
            raise VFIError("空のフレームは処理できません。")
        self.data.setflags(write=False)

    def at(self, timestamp: Fraction) -> "VideoFrame":
        """Retimestamp an original without copying pixels."""
        return replace(self, timestamp=timestamp)
