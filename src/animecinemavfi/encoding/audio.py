from fractions import Fraction
from pathlib import Path

from animecinemavfi.core.config import AppConfig
from animecinemavfi.core.control import JobControl
from animecinemavfi.core.errors import VFIError
from animecinemavfi.utils.paths import media_path
from animecinemavfi.utils.process import ManagedProcess
from animecinemavfi.video.ffmpeg import FFmpegManager
from animecinemavfi.video.probe import VideoInfo
from animecinemavfi.video.timing import seconds

MP4_AUDIO = {"aac", "mp3", "ac3", "eac3", "alac"}


class AudioMuxer:
    @staticmethod
    def validate(info: VideoInfo, output: Path, config: AppConfig) -> list[str]:
        warnings = []
        if output.suffix.lower() == ".mp4":
            if config.audio_mode == "copy" and any(a.codec not in MP4_AUDIO for a in info.audio):
                raise VFIError(
                    "MP4へコピーできない音声があります。MKV出力か、音声AAC変換を選んでください。"
                )
            if config.preserve_subtitles and any(s.codec != "mov_text" for s in info.subtitles):
                raise VFIError(
                    "MP4に保持できない字幕があります。MKV出力か、字幕を除外する設定を選んでください。"
                )
            if info.attachments:
                warnings.append(
                    "MP4では添付フォント等を保持しません。保持する場合はMKVを選択してください。"
                )
        if (
            output.suffix.lower() == ".mkv"
            and config.preserve_subtitles
            and any(s.codec == "mov_text" for s in info.subtitles)
        ):
            raise VFIError(
                "mov_text字幕のMKVへのコピーは未対応です。MP4出力か字幕除外を選んでください。"
            )
        if not config.preserve_subtitles and info.subtitles:
            warnings.append("設定に従って字幕を除外します。")
        if config.audio_mode == "aac" and info.audio:
            warnings.append("全音声トラックをAAC 256kbpsへ再圧縮します。")
        return warnings

    @staticmethod
    def maps(info: VideoInfo, output: Path, config: AppConfig) -> list[str]:
        args = ["-map", "0:v:0"]
        for track in info.audio:
            args += ["-map", f"1:{track.index}"]
        if config.preserve_subtitles:
            for track in info.subtitles:
                args += ["-map", f"1:{track.index}"]
        if output.suffix.lower() == ".mkv":
            args += ["-map", "1:t?"]
        return args

    @staticmethod
    def stream_metadata(
        info: VideoInfo, source: int, original_indices: bool, config: AppConfig, output: Path
    ) -> list[str]:
        args: list[str] = []
        groups = [("a", info.audio)]
        if config.preserve_subtitles:
            groups.append(("s", info.subtitles))
        if output.suffix.lower() == ".mkv":
            groups.append(("t", info.attachment_tracks))
        for kind, tracks in groups:
            for index, track in enumerate(tracks):
                incoming = str(track.index) if original_indices else f"{kind}:{index}"
                args += [f"-map_metadata:s:{kind}:{index}", f"{source}:s:{incoming}"]
                if kind != "t":
                    args += [f"-disposition:{kind}:{index}", "+".join(track.dispositions) or "0"]
        return args

    def mux(
        self,
        ffmpeg: FFmpegManager,
        info: VideoInfo,
        silent: Path,
        output: Path,
        origin: Fraction,
        start: Fraction,
        duration: Fraction,
        config: AppConfig,
        control: JobControl,
    ) -> None:
        self.validate(info, output, config)
        prefix = [ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        tracks = output.with_name(output.stem + ".tracks" + output.suffix)
        has_tracks = bool(
            info.audio
            or (config.preserve_subtitles and info.subtitles)
            or (info.attachments and output.suffix.lower() == ".mkv")
        )
        if has_tracks:
            # Clip only companion streams. Seeking the encoded video would drop its
            # first keyframe when B-frame DTS is negative, even for output -ss 0.
            maps = [part.replace("1:", "0:") for part in self.maps(info, output, config)[2:]]
            trim = [
                *prefix,
                "-copyts",
                "-itsoffset",
                seconds(-origin - start),
                "-i",
                media_path(info.path),
                *maps,
                "-ss",
                "0",
                "-t",
                seconds(duration),
                "-c:a",
                config.audio_mode,
                "-c:s",
                "copy",
                "-c:t",
                "copy",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-avoid_negative_ts",
                "disabled",
            ]
            if config.audio_mode == "aac":
                trim += ["-b:a", "256k"]
            trim += self.stream_metadata(info, 0, True, config, output)
            trim += [media_path(tracks)]
            with ManagedProcess(trim, control, label="FFmpeg audio/subtitle trim") as proc:
                proc.input.close()
                proc.finish(timeout=3600)
        args = [*prefix, "-copyts", "-i", media_path(silent)]
        if has_tracks:
            args += ["-i", media_path(tracks)]
        args += ["-map", "0:v:0"]
        if has_tracks:
            args += ["-map", "1:a?", "-map", "1:s?", "-map", "1:t?"]
        args += [
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-avoid_negative_ts",
            "disabled",
        ]
        if output.suffix.lower() == ".mp4":
            args += [
                "-movflags",
                "+faststart",
                "-video_track_timescale",
                str(Fraction(config.output_fps).numerator),
            ]
        if has_tracks:
            args += self.stream_metadata(info, 1, False, config, output)
        args += [media_path(output)]
        with ManagedProcess(args, control, label="FFmpeg audio/subtitle mux") as proc:
            proc.input.close()
            proc.finish(timeout=3600)
        tracks.unlink(missing_ok=True)
