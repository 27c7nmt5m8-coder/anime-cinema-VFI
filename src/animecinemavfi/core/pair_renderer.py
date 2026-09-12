"""Bounded planning before inference. Protected scene cuts never reach a model."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fractions import Fraction

from animecinemavfi.analysis.scene import SceneResult
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.core.extensions import (
    Decision,
    FrameContext,
    ModelRouter,
    MotionDirector,
    SegmentKey,
)
from animecinemavfi.interpolation.base import VideoInterpolationEngine
from animecinemavfi.video.frame import VideoFrame
from animecinemavfi.video.timing import interpolation_alpha

PLAN_SIZE = 32


@dataclass(frozen=True)
class RenderedFrame:
    frame: VideoFrame
    original: VideoFrame
    interpolated: bool = False
    protected: bool = False


class PairRenderer:
    def __init__(self, director: MotionDirector, router: ModelRouter, control: JobControl) -> None:
        self.director, self.router, self.control = director, router, control

    def render(
        self,
        left: VideoFrame,
        right: VideoFrame | None,
        times: Sequence[Fraction],
        scene: SceneResult,
        protect_cuts: bool,
    ) -> Iterator[RenderedFrame]:
        if len(times) > PLAN_SIZE:
            raise ValueError("Planning batch is too large")
        plans: list[tuple[Fraction, Decision, VideoInterpolationEngine | None]] = []
        for timestamp in times:
            self.control.checkpoint()
            engine = None
            decision = Decision.HOLD_LEFT
            if right is not None and timestamp != left.timestamp:
                context = FrameContext(
                    SegmentKey(left.timestamp, right.timestamp),
                    timestamp,
                    scene.cut and protect_cuts,
                    scene.score,
                )
                if not context.scene_cut:
                    decision = self.director.decide(context)
                    if decision is Decision.INTERPOLATE:
                        engine = self.router.select(context)
            plans.append((timestamp, decision, engine))
        index = 0
        while index < len(plans):
            timestamp, decision, engine = plans[index]
            if engine is None:
                self.control.checkpoint()
                frame = right if decision is Decision.HOLD_RIGHT and right else left
                protected = (
                    right is not None
                    and timestamp != left.timestamp
                    and decision is Decision.HOLD_LEFT
                )
                yield RenderedFrame(frame.at(timestamp), left.at(timestamp), protected=protected)
                index += 1
                continue
            assert right is not None
            end = index + 1
            while end < len(plans) and plans[end][2] is engine:
                end += 1
            group = plans[index:end]
            steps = [interpolation_alpha(t, left.timestamp, right.timestamp) for t, _, _ in group]
            results = engine.interpolate_many(left, right, steps)
            for (t, _, _), frame in zip(group, results, strict=True):
                self.control.checkpoint()
                if (
                    frame.timestamp != t
                    or frame.format != left.format
                    or frame.data.shape != left.data.shape
                ):
                    raise VFIError("VFI Engineの出力時刻・形式・解像度が契約と一致しません。")
                yield RenderedFrame(frame, left.at(t), interpolated=True)
            index = end
