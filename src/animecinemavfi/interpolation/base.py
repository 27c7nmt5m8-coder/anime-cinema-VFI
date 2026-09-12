from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from fractions import Fraction

from animecinemavfi.interpolation.capabilities import EngineCapabilities
from animecinemavfi.video.frame import VideoFrame

Frame = VideoFrame


class VideoInterpolationEngine(ABC):
    """Format-aware contract: output retains input format and exact interpolated PTS."""

    capabilities = EngineCapabilities()

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def interpolate(self, left: Frame, right: Frame, timestep: Fraction) -> Frame: ...

    def interpolate_many(
        self, left: Frame, right: Frame, timesteps: Sequence[Fraction]
    ) -> Iterator[Frame]:
        """Ordered lazy output. Consume fully or close engine. Timesteps inside (0,1).

        Original endpoints bypass the engine. Default adapter retains single-step engines.
        """
        self.capabilities.validate_pair(left, right)
        for timestep in timesteps:
            if not isinstance(timestep, Fraction) or not 0 < timestep < 1:
                raise ValueError("Timesteps must be Fractions inside (0, 1)")
            yield self.interpolate(left, right, timestep)

    @abstractmethod
    def close(self) -> None: ...


InterpolationEngine = VideoInterpolationEngine
