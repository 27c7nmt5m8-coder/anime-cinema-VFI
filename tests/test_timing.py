from fractions import Fraction as F

import pytest

from animecinemavfi.core.errors import VFIError
from animecinemavfi.video.timeline import cadence_is_variable
from animecinemavfi.video.timing import (
    interpolation_alpha,
    output_count,
    output_timestamp,
    parse_fps,
    seconds,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("23.976", F(24000, 1001)),
        ("24.000", F(24)),
        ("25", F(25)),
        ("29.97", F(30000, 1001)),
        ("30", F(30)),
        ("50", F(50)),
        ("59.94", F(60000, 1001)),
        ("60", F(60)),
        ("120000/1001", F(120000, 1001)),
    ],
)
def test_fps(text, expected):
    assert parse_fps(text) == expected


@pytest.mark.parametrize("value", ["0", "-1", "481", "nan", "1/0", "abc"])
def test_invalid_fps(value):
    with pytest.raises(VFIError):
        parse_fps(value)


def test_long_clock_no_accumulating_error():
    rate = F(24000, 1001)
    input_index = 24 * 60 * 60 * 3
    original = F(input_index) / rate
    assert output_timestamp(input_index * 5, rate * 5) == original
    assert output_count(F(10800), rate * 5) == 1294706
    assert abs(F(seconds(original)) - original) < F(1, 10**11)


def test_24_to_120_anchors():
    for i in range(240):
        assert output_timestamp(i * 5, F(120)) == F(i, 24)
    assert interpolation_alpha(F(1, 120), F(0), F(1, 24)) == F(1, 5)


def test_half_open_clock_and_last_hold():
    assert output_count(F(1), F(60)) == 60
    assert output_timestamp(59, F(60)) < 1
    assert output_count(F(1001, 1000), F(60)) == 61


def test_quantized_mkv_timing_is_not_vfr():
    fps = F(24000, 1001)
    for i in range(500):
        time = F(round(F(i) / fps * 1000), 1000)
        assert not cadence_is_variable(i, time, fps, F(1, 1000))
    assert cadence_is_variable(2, F(1, 4), F(24), F(1, 1000))
