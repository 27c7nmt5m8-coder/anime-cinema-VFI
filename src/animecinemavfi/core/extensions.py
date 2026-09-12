"""Small contracts for later roadmap steps. No placeholder UI features."""

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Protocol

from animecinemavfi.interpolation.base import Frame, VideoInterpolationEngine
from animecinemavfi.video.frame import FrameFormat as FrameFormat


@dataclass(frozen=True)
class SegmentKey:
    start: Fraction
    end: Fraction


@dataclass(frozen=True)
class FrameContext:
    segment: SegmentKey
    timestamp: Fraction
    scene_cut: bool
    scene_score: float


class Decision(Enum):
    INTERPOLATE = "interpolate"
    HOLD_LEFT = "hold_left"
    HOLD_RIGHT = "hold_right"


class MotionDirector(Protocol):
    def decide(self, context: FrameContext) -> Decision: ...


class BasicMotionDirector:
    def decide(self, context: FrameContext) -> Decision:
        return Decision.HOLD_LEFT if context.scene_cut else Decision.INTERPOLATE


class ModelRouter(Protocol):
    def select(self, context: FrameContext) -> VideoInterpolationEngine: ...


class SingleModelRouter:
    def __init__(self, engine: VideoInterpolationEngine) -> None:
        self.engine = engine

    def select(self, context: FrameContext) -> VideoInterpolationEngine:
        return self.engine


@dataclass(frozen=True)
class ArtifactReport:
    accepted: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetryPlan:
    segment: SegmentKey
    actions: tuple[str, ...] = (
        "same_model_settings",
        "alternate_model",
        "reduce_strength",
        "original",
    )


class ArtifactInspector(Protocol):
    def inspect(self, frame: Frame, context: FrameContext) -> ArtifactReport: ...


class SemanticAnalyzer(Protocol):
    def analyze(self, frame: Frame, context: FrameContext) -> dict[str, object]: ...


class QualityEngine(Protocol):
    def process(self, frame: Frame, original_preservation: float) -> Frame: ...


class HDREngine(Protocol):
    def supports(self, format: FrameFormat) -> bool: ...
