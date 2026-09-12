from dataclasses import replace
from pathlib import Path

import pytest

from animecinemavfi.color.metadata import ColorMetadata, SDRColorPolicy
from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.errors import VFIError
from animecinemavfi.encoding.audio import AudioMuxer
from animecinemavfi.video.probe import VideoProbe


def test_probe_parsing(probe_data):
    info = VideoProbe.parse(probe_data, Path("日本語 movie.mp4"))
    assert info.fps.numerator == 24000
    assert info.color.bit_depth == 8
    assert [a.language for a in info.audio] == ["jpn", "eng"]
    assert len(info.subtitles) == 1
    assert not info.color.hdr
    assert info.start_time == 0.5


def test_ignore_cover_art(probe_data):
    probe_data["streams"].insert(
        0, {"index": 9, "codec_type": "video", "disposition": {"attached_pic": 1}}
    )
    assert VideoProbe.parse(probe_data, Path("x.mkv")).stream_index == 0


@pytest.mark.parametrize(
    "pix,depth",
    [("yuv420p10le", 10), ("gbrp12be", 12), ("p010le", 10), ("rgb24", 8), ("unknown", None)],
)
def test_bit_depth(pix, depth):
    assert ColorMetadata.parse({"pix_fmt": pix}).bit_depth == depth


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67"])
def test_hdr_never_silently_downgraded(transfer):
    color = ColorMetadata.parse(
        {
            "pix_fmt": "yuv420p10le",
            "color_transfer": transfer,
            "side_data_list": [
                {"side_data_type": "Mastering display metadata", "max_luminance": "1000/1"}
            ],
        }
    )
    assert color.hdr and color.side_data
    with pytest.raises(VFIError, match="HDR"):
        SDRColorPolicy().validate(color)


def test_audio_maps_all_tracks(probe_data):
    info = VideoProbe.parse(probe_data, Path("in.mkv"))
    maps = AudioMuxer.maps(info, Path("out.mkv"), AppConfig())
    assert maps == ["-map", "0:v:0", "-map", "1:1", "-map", "1:2", "-map", "1:3", "-map", "1:t?"]


def test_silent_video_no_required_audio_mapping(probe_data):
    info = replace(VideoProbe.parse(probe_data, Path("in.mkv")), audio=(), subtitles=())
    assert AudioMuxer.maps(info, Path("out.mp4"), AppConfig()) == ["-map", "0:v:0"]


def test_mp4_subtitle_error_is_explicit(probe_data):
    info = VideoProbe.parse(probe_data, Path("in.mkv"))
    with pytest.raises(VFIError, match="字幕"):
        AudioMuxer.validate(info, Path("out.mp4"), AppConfig())
    assert AudioMuxer.validate(
        info, Path("out.mp4"), replace(AppConfig(), preserve_subtitles=False)
    )
