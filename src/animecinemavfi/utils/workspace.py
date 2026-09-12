import os
import shutil
import tempfile
from pathlib import Path

from animecinemavfi.core.errors import VFIError


def validate_output(input_path: Path, output_path: Path) -> Path:
    target = output_path.expanduser().resolve()
    if target == input_path.expanduser().resolve():
        raise VFIError("入力動画と出力先は別のファイルにしてください。")
    if target.suffix.lower() not in {".mp4", ".mkv"}:
        raise VFIError("出力形式は.mkvまたは.mp4を指定してください。")
    if target.exists():
        raise VFIError("出力ファイルは既に存在します。別の名前を指定してください。")
    if not target.parent.is_dir():
        raise VFIError("出力先フォルダーがありません。")
    return target


def check_disk(directory: Path, reserve_mb: int) -> None:
    if shutil.disk_usage(directory).free < reserve_mb * 1048576:
        raise VFIError(f"ディスク空き容量が不足しています（安全余裕 {reserve_mb} MB）。")


class Workspace:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.lock_path = output.with_name(output.name + ".acvfi-lock")
        self.path: Path | None = None

    def __enter__(self) -> Path:
        try:
            with self.lock_path.open("x", encoding="utf-8") as handle:
                handle.write(str(os.getpid()))
        except FileExistsError as exc:
            raise VFIError(
                "同じ出力先のジョブが処理中、または終了確認待ちです（.acvfi-lock）。"
            ) from exc
        try:
            self.path = Path(tempfile.mkdtemp(prefix=".acvfi-", dir=self.output.parent))
            (self.path / "OWNER").write_text(
                "AnimeCinemaVFI temporary workspace\n", encoding="utf-8"
            )
            return self.path
        except Exception:
            self.lock_path.unlink(missing_ok=True)
            raise

    def __exit__(self, *args: object) -> None:
        try:
            if self.path:
                shutil.rmtree(self.path)
        finally:
            self.lock_path.unlink(missing_ok=True)


def publish(source: Path, target: Path) -> None:
    """No overwrite even if another application creates the destination mid-job."""
    if os.name == "nt":
        os.rename(source, target)  # Windows rename fails if destination exists.
    else:
        os.link(source, target)  # atomic no-clobber, same volume as workspace.
        source.unlink()
