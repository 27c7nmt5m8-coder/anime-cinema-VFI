import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from animecinemavfi.core.control import JobControl
from animecinemavfi.utils.process import capture


@dataclass(frozen=True)
class GPUInfo:
    name: str
    cuda_available: bool
    total_mb: int | None
    free_mb: int | None
    driver: str
    torch_version: str
    cuda_version: str
    diagnostic: str = ""


class GPUManager:
    @staticmethod
    def nvidia_memory() -> dict[str, Any]:
        executable = shutil.which("nvidia-smi")
        if not executable and os.name == "nt":
            candidate = os.path.join(
                os.environ.get("WINDIR", r"C:\Windows"), "System32", "nvidia-smi.exe"
            )
            if os.path.isfile(candidate):
                executable = candidate
        if not executable:
            return {}
        try:
            result = subprocess.run(
                [
                    executable,
                    "--id=0",
                    "--query-gpu=name,driver_version,memory.total,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                timeout=5,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            name, driver, total, free = result.stdout.decode(errors="replace").strip().split(",")
            return {
                "name": name.strip(),
                "driver": driver.strip(),
                "total_mb": int(total),
                "free_mb": int(free),
            }
        except (OSError, ValueError, subprocess.SubprocessError):
            return {}

    def detect(self, control: JobControl) -> GPUInfo:
        memory = self.nvidia_memory()
        try:
            raw = capture(
                [sys.executable, "-m", "animecinemavfi.core.gpu"],
                control,
                timeout=60,
                label="GPU detection",
            )
            data = json.loads(raw)
        except Exception as exc:
            control.raise_if_cancelled()
            data = {"diagnostic": str(exc)}
        return GPUInfo(
            data.get("name", memory.get("name", "CPU / GPU未検出")),
            bool(data.get("cuda_available", False)),
            data.get("total_mb", memory.get("total_mb")),
            data.get("free_mb", memory.get("free_mb")),
            memory.get("driver", "unknown"),
            data.get("torch_version", "未導入"),
            data.get("cuda_version", "none"),
            data.get("diagnostic", ""),
        )


def _main() -> None:
    try:
        import torch

        data = {
            "torch_version": torch.__version__,
            "cuda_version": str(torch.version.cuda),
            "cuda_available": torch.cuda.is_available(),
        }
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info(0)
            data.update(
                name=torch.cuda.get_device_name(0),
                total_mb=total // 1048576,
                free_mb=free // 1048576,
            )
    except Exception as exc:
        data = {"diagnostic": str(exc)}
    print(json.dumps(data))


if __name__ == "__main__":
    _main()
