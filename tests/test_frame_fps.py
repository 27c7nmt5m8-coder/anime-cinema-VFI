from dataclasses import replace
from fractions import Fraction as F

import numpy as np
import pytest

from animecinemavfi.core.config import AppConfig, ConfigManager
from animecinemavfi.core.errors import VFIError
from animecinemavfi.interpolation.capabilities import EngineCapabilities
from animecinemavfi.interpolation.rife import RIFEEngine
from animecinemavfi.video.frame import FrameFormat, VideoFrame
from animecinemavfi.video.output_fps import OutputFPS


@pytest.mark.parametrize(
    "source,multiplier,expected",
    [
        (F(24000, 1001), 5, F(120000, 1001)),
        (F(24), 5, F(120)),
        (F(25), 5, F(125)),
        (F(30000, 1001), 2, F(60000, 1001)),
    ],
)
def test_source_multiplier(source, multiplier, expected):
    assert OutputFPS("source", multiplier=multiplier).resolve(source) == expected
    for n in (0, 1, 23, 1_000_000):
        assert F(n * multiplier) / expected == F(n) / source


def test_fixed_120_is_distinct_and_display_is_exact():
    assert OutputFPS().resolve(F(24000, 1001)) == 120
    assert OutputFPS("source").display(F(24000, 1001)) == "119.880 fps (120000/1001)"


def test_config_migration_and_multiplier_roundtrip(tmp_path):
    manager = ConfigManager(tmp_path / "config.json")
    manager.path.write_text('{"schema_version":1,"output_fps":"60"}')
    assert manager.load().fps_mode == "fixed"
    config = replace(AppConfig(), fps_mode="source", source_multiplier=5)
    manager.save(config)
    assert manager.load() == config


@pytest.mark.parametrize(
    "dtype,bits,pix",
    [
        ("uint8", 8, "rgb24"),
        ("uint16", 10, "rgb48le"),
        ("float16", 16, "rgbf16"),
        ("float32", 32, "rgbf32"),
    ],
)
def test_frame_precision_contract(dtype, bits, pix):
    format = FrameFormat(dtype=dtype, bit_depth=bits, pixel_format=pix)
    frame = VideoFrame(np.zeros((4, 6, 3), dtype=dtype), F(1, 24), format)
    assert frame.data.dtype.name == dtype
    assert not frame.data.flags.writeable
    assert frame.at(F(2, 24)).data is frame.data
    assert frame.at(F(2, 24)).timestamp == F(2, 24)


@pytest.mark.parametrize(
    "format",
    [
        FrameFormat(dtype="uint16", bit_depth=10, pixel_format="rgb48le"),
        FrameFormat(transfer="smpte2084"),
        FrameFormat(transfer="arib-std-b67"),
        FrameFormat(color_primaries="bt2020"),
    ],
)
def test_rife_rejects_high_depth_and_hdr(format):
    assert not RIFEEngine.capabilities.supports(format)
    left = VideoFrame(np.zeros((4, 6, 3), dtype=format.dtype), F(0), format)
    with pytest.raises(VFIError, match="FrameFormat"):
        RIFEEngine.capabilities.validate_pair(left, left.at(F(1, 24)))


def test_future_capability_negotiation():
    caps = EngineCapabilities(
        pixel_formats=("rgbf32",), dtypes=("float32",), bit_depths=(32,), hdr=True, wide_gamut=True
    )
    assert caps.supports(
        FrameFormat(
            dtype="float32",
            bit_depth=32,
            pixel_format="rgbf32",
            transfer="smpte2084",
            color_primaries="bt2020",
        )
    )
    assert not caps.supports(FrameFormat())
    assert RIFEEngine.capabilities.supports(FrameFormat())


def test_frame_cannot_lie_about_dtype_or_use_float_timestamp():
    with pytest.raises(VFIError, match="dtype"):
        VideoFrame(np.zeros((4, 6, 3), np.uint16), F(0), FrameFormat())
    with pytest.raises(VFIError, match="Fraction"):
        VideoFrame(np.zeros((4, 6, 3), np.uint8), 0.1, FrameFormat())
