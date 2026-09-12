import hashlib
import json
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from animecinemavfi.core.config import user_data_dir
from animecinemavfi.core.errors import VFIError
from animecinemavfi.interpolation.capabilities import EngineCapabilities


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    version: str
    path: Path
    repository_path: Path
    capabilities: tuple[str, ...]
    preferred_content: tuple[str, ...]
    vram_requirements: dict[str, Any]
    license_information: dict[str, Any]
    source: str
    trusted: bool
    sha256: dict[str, str]
    frame_capabilities: EngineCapabilities = EngineCapabilities()

    def validate_files(self) -> None:
        if not self.trusted:
            raise VFIError(
                "RIFE未登録です。公式モデルを配置し「RIFEフォルダー登録」を実行してください。"
            )
        for required in ("RIFE_HDv3.py", "flownet.pkl"):
            if not (self.path / required).is_file():
                raise VFIError(f"RIFEモデルに {required} がありません。")
        if "arbitrary_timestep" not in self.capabilities:
            raise VFIError("このモデルは任意timestepに対応していません。")
        if not self.sha256:
            raise VFIError("モデルのハッシュが未登録です。モデルを再登録してください。")
        for name, digest in self.sha256.items():
            candidate = (self.path / name).resolve()
            if not candidate.is_relative_to(self.path.resolve()) or not candidate.is_file():
                raise VFIError("モデルRegistry内のファイルパスが不正です。")
            with candidate.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != digest:
                    raise VFIError(
                        f"登録後にモデルファイルが変更されました: {name}。再登録が必要です。"
                    )


class ModelRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_dir() / "models.json"

    def data(self) -> dict[str, Any]:
        try:
            source = (
                self.path.read_text(encoding="utf-8")
                if self.path.exists()
                else (
                    files("animecinemavfi.models")
                    .joinpath("catalog.json")
                    .read_text(encoding="utf-8")
                )
            )
            data = json.loads(source)
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("Registry schema")
            ids = [item["id"] for item in data["models"]]
            if len(ids) != len(set(ids)) or not ids:
                raise ValueError("Registry IDs")
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VFIError(f"Model Registryを読み込めません: {exc}") from exc

    def list(self) -> list[ModelSpec]:
        specs = []
        try:
            for item in self.data()["models"]:

                def path(key: str, model_data: dict[str, Any] = item) -> Path:
                    value = Path(model_data[key]).expanduser()
                    return (value if value.is_absolute() else self.path.parent / value).resolve()

                specs.append(
                    ModelSpec(
                        item["id"],
                        item["name"],
                        item["version"],
                        path("path"),
                        path("repository_path"),
                        tuple(item["capabilities"]),
                        tuple(item["preferred_content"]),
                        item["vram_requirements"],
                        item["license_information"],
                        item["source"],
                        item.get("trusted") is True,
                        item.get("sha256", {}),
                        EngineCapabilities.from_dict(item.get("frame_capabilities", {})),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise VFIError(f"Model Registryの項目が不正です: {exc}") from exc
        return specs

    def get(self, model_id: str) -> ModelSpec:
        for spec in self.list():
            if spec.id == model_id:
                return spec
        raise VFIError(f"モデルがRegistryにありません: {model_id}")

    def register(self, model_id: str, model_dir: Path, repo_dir: Path) -> ModelSpec:
        model_dir = model_dir.resolve()
        for name in ("RIFE_HDv3.py", "flownet.pkl"):
            if not (model_dir / name).is_file():
                raise VFIError(
                    f"選択したフォルダーに{name}がありません。train_logを指定してください。"
                )
        if model_dir.name != "train_log":
            raise VFIError("公式モデルのフォルダー名はtrain_logにしてください。")
        data = self.data()
        candidates = [item for item in data["models"] if item["id"] == model_id]
        if not candidates:
            raise VFIError("登録するモデルIDがありません。")
        item = candidates[0]
        hashes = {}
        for candidate in sorted(model_dir.rglob("*")):
            if candidate.is_file() and candidate.suffix in {".py", ".pkl"}:
                with candidate.open("rb") as handle:
                    hashes[candidate.relative_to(model_dir).as_posix()] = hashlib.file_digest(
                        handle, "sha256"
                    ).hexdigest()
        item.update(
            path=str(model_dir),
            repository_path=str(repo_dir.resolve()),
            trusted=True,
            sha256=hashes,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        return self.get(model_id)
