import json
import subprocess
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path

import numpy as np
import pytest
from conftest import fake_factory, run_ffmpeg

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import Cancelled, VFIError
from animecinemavfi.core.gpu import GPUInfo, GPUManager
from animecinemavfi.core.job import JobManager, JobSpec
from animecinemavfi.models.registry import ModelRegistry
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoProbe
from animecinemavfi.video.timeline import TimelineIndex

pytestmark = pytest.mark.integration


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        GPUManager, "detect", lambda *_: GPUInfo("test", False, None, None, "none", "test", "none")
    )
    return JobManager(ModelRegistry(tmp_path / "models.json"), engine_factory=fake_factory)


def probe_counts(path: Path):
    raw = subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_packets", "-show_streams", "-of", "json", str(path)]
    )
    return json.loads(raw)["streams"]


@pytest.mark.parametrize(
    "ext,encoder,fps,audio",
    [
        (".mp4", "libx264", "60", 2),
        (".mkv", "libx264", "120000/1001", 0),
        (".mkv", "libx265", "120", 1),
        (".mp4", "libx264", "60000/1001", 1),
    ],
)
def test_complete_media_pipeline(sample_factory, pipeline, tmp_path, ext, encoder, fps, audio):
    source = sample_factory("日本語 入力.mp4", audio=audio)
    output = tmp_path / ("補間 出力" + ext)
    config = replace(AppConfig(), output_fps=fps, encoder=encoder, quality="fast")
    result = pipeline.run(JobSpec(source, output, config), JobControl())
    streams = probe_counts(output)
    video = next(s for s in streams if s["codec_type"] == "video")
    assert int(video["nb_read_packets"]) == result.frames
    if ext == ".mp4":
        assert F(video["r_frame_rate"]) == F(fps)
    else:
        # Matroska DefaultDuration is integer ns; FFmpeg PTS precision is 1ms.
        assert abs(F(video["r_frame_rate"]) - F(fps)) < F(1, 10000)
        stamps = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_frames",
                    "-show_entries",
                    "frame=best_effort_timestamp_time",
                    "-of",
                    "json",
                    str(output),
                ]
            )
        )["frames"]
        for index, stamp in enumerate(stamps):
            assert abs(F(stamp["best_effort_timestamp_time"]) - F(index) / F(fps)) <= F(1, 1000)
    audios = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audios) == audio
    if audio == 2:
        assert [a["tags"]["language"] for a in audios] == ["jpn", "eng"]
    assert video["color_primaries"] == "bt709"
    assert not list(tmp_path.glob(".acvfi-*"))
    assert not list(tmp_path.glob("*.acvfi-lock"))
    report = json.loads(result.report.read_text(encoding="utf-8"))
    assert str(tmp_path) not in json.dumps(report)


def test_preview_sync_and_reference(sample_factory, pipeline, tmp_path):
    source = sample_factory(duration="3", fps="24", audio=2)
    output = tmp_path / "preview.mp4"
    result = pipeline.run(
        JobSpec(source, output, replace(AppConfig(), output_fps="60", quality="fast"), F(1), F(1)),
        JobControl(),
    )
    assert result.reference and result.reference.exists()
    assert result.frames == 60
    streams = probe_counts(output)
    for stream in streams:
        if stream["codec_type"] in {"video", "audio"}:
            assert abs(float(stream.get("start_time", 0))) < 0.025
            assert abs(float(stream["duration"]) - 1) < 0.03


def test_cut_never_blends(ffmpeg_available, pipeline, tmp_path):
    source = tmp_path / "cut.mp4"
    frames = [np.full((64, 96, 3), value, np.uint8) for value in [0, 0, 255, 255]]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "96x64",
            "-r",
            "4",
            "-i",
            "pipe:0",
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        input=b"".join(f.tobytes() for f in frames),
        check=True,
        capture_output=True,
    )
    result = pipeline.run(
        JobSpec(
            source, tmp_path / "cut-out.mp4", replace(AppConfig(), output_fps="16", quality="fast")
        ),
        JobControl(),
    )
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(result.output),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    output = np.frombuffer(raw, np.uint8).reshape(-1, 64, 96, 3)
    assert len(output) == 16
    assert output[:8].mean() < 3
    assert output[8:].mean() > 250
    assert result.protected == 3


def test_mkv_subtitle_and_font_mapping(sample_factory, pipeline, tmp_path):
    base = sample_factory(audio=2)
    subtitle = tmp_path / "captions.srt"
    subtitle.write_text("1\n00:00:00,100 --> 00:00:00,800\nOriginal text\n", encoding="utf-8")
    attachment = tmp_path / "note.txt"
    attachment.write_text("Synthetic attachment", encoding="utf-8")
    source = tmp_path / "tracks.mkv"
    run_ffmpeg(
        [
            "-i",
            str(base),
            "-i",
            str(subtitle),
            "-map",
            "0",
            "-map",
            "1",
            "-c",
            "copy",
            "-attach",
            str(attachment),
            "-metadata:s:t",
            "mimetype=text/plain",
            str(source),
        ]
    )
    result = pipeline.run(
        JobSpec(
            source,
            tmp_path / "tracks-out.mkv",
            replace(AppConfig(), output_fps="60", quality="fast"),
        ),
        JobControl(),
    )
    streams = probe_counts(result.output)
    assert sum(s["codec_type"] == "audio" for s in streams) == 2
    assert sum(s["codec_type"] == "subtitle" for s in streams) == 1
    assert sum(s["codec_type"] == "attachment" for s in streams) == 1


def test_vfr_detection_and_explicit_opt_in(sample_factory, pipeline, tmp_path):
    source = sample_factory(fps="24", duration="2", audio=0)
    vfr = tmp_path / "vfr.mkv"
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-vf",
            "select='if(lt(t,1),not(mod(n,2)),1)'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            str(vfr),
        ]
    )
    output = tmp_path / "vfr-out.mkv"
    config = replace(AppConfig(), output_fps="60", quality="fast")
    with pytest.raises(VFIError, match="VFR"):
        pipeline.run(JobSpec(vfr, output, config), JobControl())
    assert not output.exists()
    result = pipeline.run(JobSpec(vfr, output, replace(config, allow_vfr=True)), JobControl())
    assert json.loads(result.report.read_text())["vfr_detected"]


def test_audio_offset_preserved(sample_factory, pipeline, tmp_path):
    source = sample_factory(fps="24", duration="2", audio=1)
    offset = tmp_path / "offset.mp4"
    # Deliberately delay audio by 250ms; do not normalize streams independently.
    run_ffmpeg(
        [
            "-i",
            str(source),
            "-itsoffset",
            "0.25",
            "-i",
            str(source),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c",
            "copy",
            str(offset),
        ]
    )
    result = pipeline.run(
        JobSpec(
            offset,
            tmp_path / "offset-out.mp4",
            replace(AppConfig(), output_fps="60", quality="fast"),
        ),
        JobControl(),
    )
    source_audio = next(s for s in probe_counts(offset) if s["codec_type"] == "audio")
    output_audio = next(s for s in probe_counts(result.output) if s["codec_type"] == "audio")
    assert abs(float(source_audio["start_time"]) - float(output_audio["start_time"])) < 0.025


def test_nonzero_video_pts(sample_factory, pipeline, tmp_path):
    source = sample_factory(fps="24", duration="1", audio=1)
    offset = tmp_path / "offset-all.mkv"
    run_ffmpeg(
        ["-i", str(source), "-map", "0", "-c", "copy", "-output_ts_offset", "5", str(offset)]
    )
    result = pipeline.run(
        JobSpec(
            offset,
            tmp_path / "normalized.mp4",
            replace(AppConfig(), output_fps="60", quality="fast"),
        ),
        JobControl(),
    )
    video, audio = [s for s in probe_counts(result.output) if s["codec_type"] in {"video", "audio"}]
    assert abs(float(video["start_time"])) < 0.001
    assert abs(float(audio["start_time"])) < 0.03


def test_cancel_removes_partial_outputs(sample_factory, pipeline, tmp_path):
    source = sample_factory()
    output = tmp_path / "cancel.mp4"
    control = JobControl()

    def progress(p):
        if p.completed >= 1 and p.total:
            control.cancel()

    with pytest.raises(Cancelled):
        pipeline.run(JobSpec(source, output, AppConfig()), control, progress)
    assert not output.exists()
    assert not list(tmp_path.glob(".acvfi-*"))


def test_timestamp_index_matches_decode(sample_factory, tmp_path):
    source = sample_factory()
    info = VideoProbe(FFmpegManager()).probe(source, JobControl())
    index = TimelineIndex(tmp_path / "index.sqlite", info)
    try:
        index.build(FFmpegManager(), JobControl(), lambda n: None)
        assert index.count == 24
        assert not index.vfr
        assert index.duration == F(1001, 1000)
        assert index.before(F(1, 2)) == 11
    finally:
        index.close()
