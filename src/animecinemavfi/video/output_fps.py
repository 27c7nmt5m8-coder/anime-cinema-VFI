from dataclasses import dataclass
from fractions import Fraction

from animecinemavfi.core.errors import VFIError
from animecinemavfi.video.timing import parse_fps


@dataclass(frozen=True)
class OutputFPS:
    mode: str = "fixed"
    fixed: str = "120"
    multiplier: int = 5

    def validate(self) -> None:
        if self.mode not in {"fixed", "source"}:
            raise VFIError("出力FPSモードが不正です。")
        parse_fps(self.fixed)
        if type(self.multiplier) is not int or not 1 <= self.multiplier <= 20:
            raise VFIError("Source倍率は1～20の整数にしてください。")

    def resolve(self, source: Fraction) -> Fraction:
        self.validate()
        if self.mode == "fixed":
            return parse_fps(self.fixed)
        if source <= 0:
            raise VFIError("Source倍率には有効な入力FPSが必要です。")
        return parse_fps(str(source * self.multiplier))

    def display(self, source: Fraction) -> str:
        rate = self.resolve(source)
        return f"{float(rate):.3f} fps ({rate})"
