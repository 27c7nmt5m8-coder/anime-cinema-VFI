"""Real small encoder probes; compiled NVENC is not evidence of working hardware."""

import logging
import platform
import tempfile
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from animecinemavfi import __version__
from animecinemavfi.color.encoding import ColorEncodingOptions, verify_color
from animecinemavfi.color.metadata import ColorMetadata
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.gpu import GPUManager
from animecinemavfi.encoding.backends import BACKENDS, get_backend
from animecinemavfi.encoding.encoder import Encoder
from animecinemavfi.utils.logging import PrivacyFormatter
from animecinemavfi.utils.process import capture
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.frame import VideoFrame
from animecinemavfi.video.probe import VideoInfo, VideoProbe


@dataclass(frozen=True)
class EncoderDiagnostic:
    encoder: str
    status: str
    reason: str
    color: dict[str, Any] | None = None


def probe_encoder(ffmpeg: FFmpegManager, name: str, control: JobControl) -> EncoderDiagnostic:
    backend = get_backend(name)
    if name not in ffmpeg.encoders(control):
        return EncoderDiagnostic(name, "unavailable", "FFmpegにencoderが含まれていません。")
    encoded = False
    try:
        with tempfile.TemporaryDirectory(prefix="acvfi-diagnostic-") as directory:
            path = Path(directory) / "色確認 sample.mp4"
            source_color = ColorMetadata("bt709", "bt709", "bt709", "tv", 8, "yuv420p")
            info = VideoInfo(
                path,
                0,
                128,
                72,
                Fraction(24),
                Fraction(24),
                Fraction(1, 24),
                Fraction(1, 8),
                Fraction(0),
                "rawvideo",
                source_color,
                (),
                (),
                0,
                Fraction(4, 3),
                0,
                "progressive",
            )
            color = ColorEncodingOptions.sdr(source_color, 72, info.sar)
            encoder = Encoder(
                ffmpeg, info, path, Fraction(24), AppConfig(encoder=name, quality="fast"), control
            )
            try:
                for i in range(3):
                    encoder.write(
                        VideoFrame(
                            np.full((72, 128, 3), 96, np.uint8),
                            Fraction(i, 24),
                            color.internal_format,
                        )
                    )
                encoder.finish()
            finally:
                encoder.close()
            encoded = True
            video = VideoProbe(ffmpeg).probe(path, control)
            verify_color(video.color, color.expected)
            if not video.sar_known or video.sar != info.sar:
                raise ValueError(f"SAR mismatch: {video.sar}")
            codec = backend.capabilities.codec
            elementary = Path(directory) / f"vui.{codec}"
            capture(
                [
                    ffmpeg.ffmpeg,
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-c:v",
                    "copy",
                    "-bsf:v",
                    f"{codec}_mp4toannexb",
                    "-f",
                    codec,
                    str(elementary),
                ],
                control,
                label="Diagnostic elementary stream",
                timeout=30,
            )
            raw = VideoProbe(ffmpeg).probe(elementary, control)
            verify_color(raw.color, color.expected)
            if not raw.sar_known or raw.sar != info.sar:
                raise ValueError("Elementary stream SAR mismatch")
            return EncoderDiagnostic(
                name,
                "passed",
                "3-frame encode + container/SPS VUI/SAR/8bit verified",
                asdict(raw.color),
            )
    except Exception as exc:
        control.raise_if_cancelled()
        record = logging.LogRecord("diagnostic", logging.ERROR, "", 0, str(exc), (), None)
        reason = PrivacyFormatter().format(record)
        absent_hardware = any(
            marker in str(exc).lower()
            for marker in (
                "cannot load libcuda",
                "cannot load nvcuda",
                "cannot load nvencodeapi",
                "no nvenc capable devices",
                "no capable devices found",
                "driver does not support",
                "minimum required nvidia driver",
                "unsupported device",
                "cuda_error_no_device",
            )
        )
        status = (
            "unavailable"
            if not encoded and backend.capabilities.hardware == "nvidia" and absent_hardware
            else "failed"
        )
        return EncoderDiagnostic(name, status, reason)


def diagnose(
    ffmpeg: FFmpegManager, control: JobControl, *, encoders: bool = False
) -> dict[str, Any]:
    info: dict[str, Any] = {
        "application_version": __version__,
        "os": platform.platform(),
        "python": platform.python_version(),
        "recommended_rife_python": "3.11",
        "gpu": asdict(GPUManager().detect(control)),
        "tools": ffmpeg.validate(control),
        "encoder_capabilities": {
            name: asdict(backend.capabilities) for name, backend in BACKENDS.items()
        },
    }
    if encoders:
        info["encoder_tests"] = [asdict(probe_encoder(ffmpeg, name, control)) for name in BACKENDS]
    return info
