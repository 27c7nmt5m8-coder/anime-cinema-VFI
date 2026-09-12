import json
from dataclasses import replace

import pytest

from animecinemavfi.core.config import AppConfig, ConfigManager
from animecinemavfi.core.errors import VFIError
from animecinemavfi.models.registry import ModelRegistry


def test_config_roundtrip(tmp_path):
    manager = ConfigManager(tmp_path / "日本語 folder" / "config.json")
    expected = replace(AppConfig(), output_fps="60000/1001", scene_protection=False)
    manager.save(expected)
    assert manager.load() == expected
    assert not manager.path.with_suffix(".tmp").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("scene_protection", "false"),
        ("encoder", "invalid"),
        ("schema_version", 9),
        ("processing_scale", 0.3),
    ],
)
def test_config_rejects_bad_values(field, value):
    with pytest.raises(VFIError):
        replace(AppConfig(), **{field: value}).validate()


def test_config_bad_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(VFIError):
        ConfigManager(path).load()


def test_default_registry_and_model_identity(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path / "models.json")
    model = registry.get(AppConfig().model_id)
    assert model.version == "4.25"
    assert "arbitrary_timestep" in model.capabilities
    assert model.license_information["code"] == "MIT"
    assert not model.trusted
    monkeypatch.chdir(tmp_path)
    assert registry.get(model.id).path == model.path


def test_model_hash_tamper(tmp_path):
    registry = ModelRegistry(tmp_path / "models.json")
    model_dir = tmp_path / "train_log"
    model_dir.mkdir()
    (model_dir / "RIFE_HDv3.py").write_text("# test only", encoding="utf-8")
    (model_dir / "flownet.pkl").write_bytes(b"not a model: registration does not execute")
    model = registry.register(AppConfig().model_id, model_dir, tmp_path)
    model.validate_files()
    (model_dir / "flownet.pkl").write_bytes(b"changed")
    with pytest.raises(VFIError, match="変更"):
        model.validate_files()


def test_duplicate_model_ids(tmp_path):
    registry = ModelRegistry(tmp_path / "models.json")
    data = registry.data()
    data["models"].append(data["models"][0].copy())
    registry.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(VFIError):
        registry.list()
