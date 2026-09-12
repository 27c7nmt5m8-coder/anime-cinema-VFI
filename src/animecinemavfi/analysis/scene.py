from dataclasses import dataclass

import numpy as np

from animecinemavfi.video.frame import FrameData


@dataclass(frozen=True)
class SceneResult:
    cut: bool
    score: float


class SceneDetector:
    """Conservative v0.1 RGB distance + color histogram; not a semantic detector."""

    def __init__(self, threshold: float = 0.32) -> None:
        self.threshold = threshold

    def detect(self, left: FrameData, right: FrameData) -> SceneResult:
        if left.shape != right.shape:
            return SceneResult(True, 1.0)
        step_y = max(1, left.shape[0] // 90)
        step_x = max(1, left.shape[1] // 160)
        a = left[::step_y, ::step_x].astype(np.float32) / 255
        b = right[::step_y, ::step_x].astype(np.float32) / 255
        difference = float(np.abs(a - b).mean())
        histogram = 0.0
        for channel in range(3):
            ha, _ = np.histogram(a[..., channel], bins=16, range=(0, 1))
            hb, _ = np.histogram(b[..., channel], bins=16, range=(0, 1))
            histogram += float(np.abs(ha - hb).sum()) / (2 * ha.sum()) / 3
        score = max(difference, histogram * min(1, difference / 0.12))
        return SceneResult(score >= self.threshold, score)
