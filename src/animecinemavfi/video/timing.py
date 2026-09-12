from decimal import Decimal, localcontext
from fractions import Fraction

from animecinemavfi.core.errors import VFIError

# Named broadcast rates are normalized only at the user-input boundary.
RATE_ALIASES = {"23.976": "24000/1001", "29.97": "30000/1001", "59.94": "60000/1001"}


def parse_fps(value: str) -> Fraction:
    try:
        rate = Fraction(RATE_ALIASES.get(value.strip(), value.strip()))
    except (ValueError, ZeroDivisionError) as exc:
        raise VFIError("FPSは60、120、24000/1001のように指定してください。") from exc
    if not 1 <= rate <= 480 or rate.denominator > 1_000_000:
        raise VFIError("出力FPSは1～480、分母は1000000以下にしてください。")
    return rate


def rational(value: object, default: Fraction = Fraction(0)) -> Fraction:
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return default


def seconds(value: Fraction) -> str:
    with localcontext() as ctx:
        ctx.prec = 32
        return format(Decimal(value.numerator) / Decimal(value.denominator), ".12f")


def ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def output_count(duration: Fraction, fps: Fraction) -> int:
    return max(0, ceil_fraction(duration * fps))


def output_timestamp(index: int, fps: Fraction) -> Fraction:
    if index < 0 or fps <= 0:
        raise ValueError("Invalid output clock")
    return Fraction(index, 1) / fps


def interpolation_alpha(t: Fraction, left: Fraction, right: Fraction) -> Fraction:
    if right <= left or not left <= t <= right:
        raise ValueError("Invalid interpolation interval")
    return (t - left) / (right - left)
