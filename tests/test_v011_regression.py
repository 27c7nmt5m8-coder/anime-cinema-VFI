import json
from dataclasses import replace
from fractions import Fraction as F

import pytest
from conftest import fake_factory, run_ffmpeg

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.job import JobManager, JobSpec
from animecinemavfi.encoding.validation import OutputValidator
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.utils.paths import extended_windows_path
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoProbe


def test_windows_path_normalization():
    path = "C:\\" + "日本語 folder\\" * 25 + "input.mp4"
    assert extended_windows_path(path) == "\\\\?\\" + path
    assert (
        extended_windows_path("\\\\server\\share\\" + "part\\" * 60)
        == "\\\\?\\UNC\\server\\share\\" + "part\\" * 60
    )
    assert extended_windows_path("C:\\短い path.mp4") == "C:\\短い path.mp4"
    assert extended_windows_path("\\\\?\\" + path) == "\\\\?\\" + path


def test_registry_frame_capabilities_and_legacy_migration(tmp_path):
    registry = ModelRegistry(tmp_path / "models.json")
    spec = registry.get(AppConfig().model_id)
    assert spec.frame_capabilities.bit_depths == (8,)
    assert spec.frame_capabilities.multiple_timesteps
    data = registry.data()
    del data["models"][0]["frame_capabilities"]
    registry.path.write_text(json.dumps(data))
    assert registry.get(spec.id).frame_capabilities.bit_depths == (8,)
    assert not registry.get(spec.id).frame_capabilities.hdr


@pytest.mark.parametrize("sar,known", [(F(1), True), (F(4, 3), False)])
def test_output_sar_loss_fails_before_publish(probe_data, tmp_path, monkeypatch, sar, known):
    source = replace(VideoProbe.parse(probe_data, tmp_path / "source"), sar=F(4, 3))
    output_info = replace(source, sar=sar, sar_known=known, color=replace(source.color, range="tv"))
    output = tmp_path / "out.mp4"
    output.write_bytes(b"test")
    monkeypatch.setattr(VideoProbe, "probe", lambda *_: output_info)
    with pytest.raises(VFIError, match="SAR"):
        OutputValidator.verify(FFmpegManager(), output, source, AppConfig(), JobControl(), 24)


@pytest.mark.integration
def test_source_multiplier_full_pipeline_and_tracks(sample_factory, tmp_path, monkeypatch):
    monkeypatch.setattr(
        GPUManager, "detect", lambda *_: GPUInfo("test", False, None, None, "none", "test", "none")
    )
    source = sample_factory("元fps 入力.mp4", fps="24000/1001", duration="1.001", audio=2)
    config = AppConfig(fps_mode="source", source_multiplier=5, quality="fast")
    job = JobManager(ModelRegistry(tmp_path / "models.json"), engine_factory=fake_factory)
    result = job.run(JobSpec(source, tmp_path / "source-x5.mp4", config), JobControl())
    info = VideoProbe(FFmpegManager()).probe(result.output, JobControl())
    assert info.fps == F(120000, 1001)
    assert result.frames == 120
    assert [t.language for t in info.audio] == ["jpn", "eng"]
    data = json.loads(result.report.read_text())
    assert data["settings"]["fps_mode"] == "source"
    assert data["settings"]["source_multiplier"] == 5
    assert data["settings"]["output_fps"] == "120000/1001"


@pytest.mark.integration
def test_dispositions_subtitle_language_and_attachment_survive_batching(
    sample_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        GPUManager, "detect", lambda *_: GPUInfo("test", False, None, None, "none", "test", "none")
    )
    source = sample_factory(audio=2)
    subtitle = tmp_path / "日本語 字幕.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:00,900\nSynthetic test\n", encoding="utf-8")
    attachment = tmp_path / "添付.txt"
    attachment.write_text("Generated test attachment", encoding="utf-8")
    rich = tmp_path / "tracks.mkv"
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-i",
            str(subtitle),
            "-map",
            "0",
            "-map",
            "1:0",
            "-c",
            "copy",
            "-metadata:s:s:0",
            "language=jpn",
            "-disposition:s:0",
            "forced",
            "-disposition:a:0",
            "0",
            "-disposition:a:1",
            "default+hearing_impaired",
            "-attach",
            str(attachment),
            "-metadata:s:t:0",
            "mimetype=text/plain",
            str(rich),
        ]
    )
    job = JobManager(ModelRegistry(tmp_path / "models.json"), engine_factory=fake_factory)
    result = job.run(
        JobSpec(
            rich,
            tmp_path / "result.mkv",
            AppConfig(fps_mode="source", source_multiplier=5, quality="fast"),
        ),
        JobControl(),
    )
    before = VideoProbe(FFmpegManager()).probe(rich, JobControl())
    after = VideoProbe(FFmpegManager()).probe(result.output, JobControl())
    for expected, actual in zip(
        before.audio + before.subtitles, after.audio + after.subtitles, strict=True
    ):
        assert actual.language == expected.language
        assert set(actual.dispositions) == set(expected.dispositions)
    assert after.attachments == 1
