"""One color decision for conversion, encoder VUI and output verification."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from animecinemavfi.color.metadata import ColorMetadata, SDRColorPolicy
from animecinemavfi.core.errors import VFIError
from animecinemavfi.video.frame import FrameFormat

UNKNOWN = {"unknown", "unspecified", "reserved", "N/A", "", "None"}


def known(value: str) -> bool:
    return value not in UNKNOWN


def normalized_range(value: str) -> str:
    return {"limited": "tv", "mpeg": "tv", "full": "pc", "jpeg": "pc"}.get(value, value)


@dataclass(frozen=True)
class ColorEncodingOptions:
    expected: ColorMetadata
    sar: Fraction
    filter: str
    internal_format: FrameFormat

    @classmethod
    def sdr(cls, source: ColorMetadata, height: int, sar: Fraction) -> "ColorEncodingOptions":
        policy = SDRColorPolicy()
        policy.validate(source)
        fallback = "bt709" if height >= 720 else "smpte170m"
        if known(source.matrix):
            fallback = "bt709" if source.matrix == "bt709" else "smpte170m"
        expected = ColorMetadata(
            primaries=source.primaries if known(source.primaries) else fallback,
            transfer=source.transfer if known(source.transfer) else fallback,
            matrix=source.matrix if known(source.matrix) else fallback,
            range="tv",
            bit_depth=8,
            pixel_format="yuv420p",
        )
        return cls(
            expected,
            sar,
            policy.encode_filter(expected, height, str(sar)),
            FrameFormat(color_primaries=expected.primaries, transfer=expected.transfer),
        )

    def ffmpeg_tags(self) -> list[str]:
        args: list[str] = []
        for flag, value in (
            ("-color_primaries", self.expected.primaries),
            ("-color_trc", self.expected.transfer),
            ("-colorspace", self.expected.matrix),
            ("-color_range", normalized_range(self.expected.range)),
        ):
            if known(value):
                args += [flag, value]
        return args


class EncoderColorPolicy(Protocol):
    def options(self, color: ColorEncodingOptions) -> list[str]: ...


def vui_parameters(color: ColorEncodingOptions) -> dict[str, str]:
    pairs = {
        "colorprim": color.expected.primaries,
        "transfer": color.expected.transfer,
        "colormatrix": color.expected.matrix,
    }
    for value in pairs.values():
        if not all(c.isalnum() or c in "-_" for c in value):
            raise VFIError("VUIの色タグに不正な値があります。")
    return {k: v for k, v in pairs.items() if known(v)}


class X264ColorPolicy:
    def options(self, color: ColorEncodingOptions) -> list[str]:
        values = vui_parameters(color)
        if known(color.expected.range):
            # x264_param_parse uses fullrange=off/on, not the x264 CLI's --range.
            values["fullrange"] = "on" if normalized_range(color.expected.range) == "pc" else "off"
        return [
            *color.ffmpeg_tags(),
            "-x264-params",
            ":".join(f"{k}={v}" for k, v in values.items()),
        ]


class X265ColorPolicy:
    def options(self, color: ColorEncodingOptions) -> list[str]:
        values = {"pools": "2", "frame-threads": "2", **vui_parameters(color)}
        if known(color.expected.range):
            values["range"] = (
                "full" if normalized_range(color.expected.range) == "pc" else "limited"
            )
        return [
            *color.ffmpeg_tags(),
            "-x265-params",
            ":".join(f"{k}={v}" for k, v in values.items()),
        ]


class NVENCColorPolicy:
    def options(self, color: ColorEncodingOptions) -> list[str]:
        # FFmpeg nvenc.c maps AVCodecContext fields into H264/HEVC VUI.
        return color.ffmpeg_tags()


def verify_color(actual: ColorMetadata, expected: ColorMetadata) -> None:
    failures = []
    for field in ("primaries", "transfer", "matrix", "range", "pixel_format", "bit_depth"):
        want, got = getattr(expected, field), getattr(actual, field)
        if want is None or (isinstance(want, str) and not known(want)):
            continue
        if field == "range":
            want, got = normalized_range(want), normalized_range(got)
        if got != want:
            failures.append(f"{field}: expected={want}, actual={got}")
    if failures:
        raise VFIError("出力Color/画素形式の検証に失敗しました: " + "; ".join(failures))
