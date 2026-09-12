import re
from dataclasses import dataclass, field
from typing import Any

from animecinemavfi.core.errors import VFIError


@dataclass(frozen=True)
class ColorMetadata:
    primaries: str = "unknown"
    transfer: str = "unknown"
    matrix: str = "unknown"
    range: str = "unknown"
    bit_depth: int | None = None
    pixel_format: str = "unknown"
    side_data: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def hdr(self) -> bool:
        return self.transfer in {"smpte2084", "arib-std-b67"} or any(
            any(
                k in str(x.get("side_data_type", "")).lower()
                for k in ("mastering display", "content light", "dovi", "hdr")
            )
            for x in self.side_data
        )

    @classmethod
    def parse(cls, stream: dict[str, Any]) -> "ColorMetadata":
        pix = str(stream.get("pix_fmt", "unknown"))
        try:
            depth = int(stream.get("bits_per_raw_sample", 0) or 0)
        except (ValueError, TypeError):
            depth = 0
        if not depth:
            match = re.search(r"(?:p|gray)(9|10|12|14|16)(?:le|be)?$", pix)
            if match:
                depth = int(match[1])
            elif pix in {
                "yuv420p",
                "yuv422p",
                "yuv444p",
                "yuvj420p",
                "yuvj422p",
                "yuvj444p",
                "nv12",
                "nv21",
                "rgb24",
                "bgr24",
                "gbrp",
                "gray",
            }:
                depth = 8
            elif pix in {"p010le", "p010be"}:
                depth = 10

        def tag(key: str) -> str:
            value = str(stream.get(key, "unknown"))
            return "unknown" if value in {"N/A", "None", "", "unspecified", "reserved"} else value

        return cls(
            tag("color_primaries"),
            tag("color_transfer"),
            tag("color_space"),
            tag("color_range"),
            depth or None,
            pix,
            tuple(stream.get("side_data_list", [])),
        )


class SDRColorPolicy:
    """v0.1 deliberately rejects data the RGB8 pipeline cannot preserve."""

    def validate(self, color: ColorMetadata) -> list[str]:
        if color.hdr or color.primaries == "bt2020" or color.matrix.startswith("bt2020"):
            raise VFIError("HDR/BT.2020の正確なVFIはv0.7予定です。v0.1では変換せず停止します。")
        if color.bit_depth != 8:
            raise VFIError(
                "v0.1の処理対象は8bit SDRです。10bit以上／深度不明の入力は処理できません。"
            )
        if color.matrix not in {"unknown", "bt709", "smpte170m", "bt470bg"}:
            raise VFIError(f"v0.1ではこの色変換行列を扱えません: {color.matrix}")
        return (
            ["色タグの一部が不明です。解像度からBT.709/BT.601を推定します。"]
            if any(
                x == "unknown" for x in (color.matrix, color.transfer, color.primaries, color.range)
            )
            else []
        )

    @staticmethod
    def matrix(color: ColorMetadata, height: int) -> str:
        if color.matrix == "unknown":
            return "bt709" if height >= 720 else "bt601"
        return "bt709" if color.matrix == "bt709" else "bt601"

    def decode_filter(self, color: ColorMetadata, height: int) -> str:
        source_range = (
            "full" if color.range == "pc" or color.pixel_format.startswith("yuvj") else "limited"
        )
        return f"scale=in_color_matrix={self.matrix(color, height)}:in_range={source_range}:out_range=full,format=rgb24"

    def encode_filter(self, color: ColorMetadata, height: int, sar: str) -> str:
        return (
            f"scale=out_color_matrix={self.matrix(color, height)}:in_range=full:out_range=limited,"
            f"format=yuv420p,setsar={sar}:max=65535"
        )

    def output_tags(self, color: ColorMetadata, height: int) -> list[str]:
        from fractions import Fraction

        from animecinemavfi.color.encoding import ColorEncodingOptions

        return ColorEncodingOptions.sdr(color, height, Fraction(1)).ffmpeg_tags()
