from dataclasses import replace
from fractions import Fraction as F

import numpy as np
import pytest
from conftest import run_ffmpeg

from animecinemavfi.color.encoding import (
    ColorEncodingOptions,
    NVENCColorPolicy,
    X264ColorPolicy,
    X265ColorPolicy,
    verify_color,
)
from animecinemavfi.color.metadata import ColorMetadata
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.encoding.backends import get_backend
from animecinemavfi.encoding.encoder import Encoder
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.frame import VideoFrame
from animecinemavfi.video.probe import VideoProbe

BT709 = ColorMetadata("bt709", "bt709", "bt709", "tv", 8, "yuv420p")


@pytest.mark.parametrize(
    "field", ["primaries", "transfer", "matrix", "range", "pixel_format", "bit_depth"]
)
def test_known_output_information_cannot_disappear(field):
    with pytest.raises(VFIError, match=field):
        verify_color(replace(BT709, **{field: None if field == "bit_depth" else "unknown"}), BT709)


def test_unknown_expectation_accepts_known_output():
    verify_color(BT709, ColorMetadata())
    verify_color(ColorMetadata(), ColorMetadata())


def test_intended_range_and_pixel_format_conversion():
    options = ColorEncodingOptions.sdr(
        replace(BT709, range="pc", pixel_format="yuvj444p"), 1080, F(4, 3)
    )
    verify_color(BT709, options.expected)
    assert "out_range=limited" in options.filter
    assert options.sar == F(4, 3)


@pytest.mark.parametrize(
    "policy,key,range_value",
    [
        (X264ColorPolicy(), "-x264-params", "fullrange=off"),
        (X265ColorPolicy(), "-x265-params", "range=limited"),
    ],
)
def test_encoder_specific_vui(policy, key, range_value):
    color = replace(BT709, primaries="bt470bg", transfer="smpte170m", matrix="bt470bg")
    args = policy.options(ColorEncodingOptions.sdr(color, 1080, F(1)))
    parameters = args[args.index(key) + 1]
    assert "colorprim=bt470bg:transfer=smpte170m:colormatrix=bt470bg" in parameters
    assert range_value in parameters
    if key == "-x264-params":
        assert ":range=" not in parameters
    else:
        assert "pools=2:frame-threads=2" in parameters


def test_nvenc_uses_codec_context_tags():
    options = ColorEncodingOptions.sdr(BT709, 1080, F(1))
    assert NVENCColorPolicy().options(options) == options.ffmpeg_tags()
    for name in ("h264_nvenc", "hevc_nvenc"):
        assert get_backend(name).capabilities.hardware == "nvidia"
        assert not get_backend(name).capabilities.hdr


@pytest.mark.integration
@pytest.mark.parametrize("encoder", ["libx264", "libx265"])
@pytest.mark.parametrize("sar", [F(4, 3), F(1001, 1000)])
@pytest.mark.parametrize(
    "color",
    [
        BT709,
        replace(BT709, primaries="smpte170m", transfer="smpte170m", matrix="smpte170m"),
        replace(BT709, primaries="bt470bg", transfer="smpte170m", matrix="bt470bg"),
        replace(BT709, range="pc", pixel_format="yuvj420p"),
        ColorMetadata(bit_depth=8, pixel_format="yuv420p"),
    ],
)
def test_container_and_bitstream_vui(encoder, color, sar, ffmpeg_available, probe_data, tmp_path):
    manager, control = FFmpegManager(), JobControl()
    assert encoder in manager.encoders(control), f"Required test encoder missing: {encoder}"
    info = replace(
        VideoProbe.parse(probe_data, tmp_path / "input"),
        width=128,
        height=72,
        color=color,
        sar=sar,
    )
    output = tmp_path / "色タグ テスト.mp4"
    options = ColorEncodingOptions.sdr(color, info.height, info.sar)
    instance = Encoder(
        manager, info, output, F(24), replace(AppConfig(), encoder=encoder, quality="fast"), control
    )
    try:
        for i in range(3):
            instance.write(
                VideoFrame(np.full((72, 128, 3), 100, np.uint8), F(i, 24), options.internal_format)
            )
        instance.finish()
    finally:
        instance.close()
    actual = VideoProbe(manager).probe(output, control)
    verify_color(actual.color, options.expected)
    assert actual.sar == sar
    codec = get_backend(encoder).capabilities.codec
    raw = tmp_path / f"elementary.{codec}"
    run_ffmpeg(
        [
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-bsf:v",
            f"{codec}_mp4toannexb",
            "-f",
            codec,
            str(raw),
        ]
    )
    # Without the container's colr box, metadata must come from SPS/VUI.
    elementary = VideoProbe(manager).probe(raw, control)
    verify_color(elementary.color, options.expected)
    assert elementary.sar == sar
