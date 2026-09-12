"""Fetch the pinned official repository + optionally the official weight archive.

Nothing is copied into the app package. User invokes this setup helper explicitly.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from animecinemavfi.core.config import AppConfig
from animecinemavfi.models.registry import ModelRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("external/Practical-RIFE"))
    parser.add_argument("--download-model", action="store_true")
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args()
    catalog = json.loads(
        files("animecinemavfi.models").joinpath("catalog.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in catalog["models"] if item["id"] == AppConfig().model_id)
    repository = args.repository.resolve()
    if not repository.exists():
        repository.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--no-checkout", entry["source"], str(repository)], check=True
        )
        subprocess.run(
            ["git", "-C", str(repository), "checkout", "--detach", entry["upstream_commit"]],
            check=True,
        )
    else:
        revision = subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"], text=True
        ).strip()
        if revision != entry["upstream_commit"]:
            raise RuntimeError(
                "Existing repository has another revision. Use a new --repository directory."
            )
    if not args.download_model:
        print("Place the official model in train_log. Download:", entry["download_url"])
        return 0
    model_dir = repository / "train_log"
    if model_dir.exists():
        raise RuntimeError(
            "train_log already exists. Register it manually or choose a new repository directory."
        )
    # The Drive ID is taken only from the bundled official catalog URL.
    parts = urlparse(entry["download_url"]).path.split("/")
    model_id = parts[parts.index("d") + 1]
    url = "https://drive.google.com/uc?export=download&id=" + model_id
    with tempfile.TemporaryDirectory(prefix="acvfi-model-") as temporary:
        archive = Path(temporary) / "model.zip"
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as target:
            total = 0
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > 512 * 1024 * 1024:
                    raise RuntimeError("Model download exceeds 512 MiB.")
                target.write(block)
        if not zipfile.is_zipfile(archive):
            raise RuntimeError(
                "Drive returned a confirmation page. Download manually from: "
                + entry["download_url"]
            )
        with archive.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        print("Downloaded archive SHA256:", digest)
        unpacked = Path(temporary) / "unpacked"
        with zipfile.ZipFile(archive) as bundle:
            if sum(item.file_size for item in bundle.infolist()) > 512 * 1024 * 1024:
                raise RuntimeError("Unpacked model exceeds 512 MiB.")
            for item in bundle.infolist():
                path = (unpacked / item.filename).resolve()
                if (
                    not path.is_relative_to(unpacked.resolve())
                    or ((item.external_attr >> 16) & 0o170000) == 0o120000
                ):
                    raise RuntimeError("Unsafe model archive path.")
                if (
                    not item.is_dir()
                    and item.filename.startswith("train_log/")
                    and path.suffix in {".py", ".pkl"}
                ):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as source, path.open("wb") as target:
                        shutil.copyfileobj(source, target)
        extracted = unpacked / "train_log"
        for required in ("RIFE_HDv3.py", "IFNet_HDv3.py", "flownet.pkl"):
            if not (extracted / required).is_file():
                raise RuntimeError("Incomplete official model archive.")
        shutil.copytree(extracted, model_dir)
    ModelRegistry(args.registry).register(entry["id"], model_dir, repository)
    print(f"Registered {entry['name']} {entry['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
