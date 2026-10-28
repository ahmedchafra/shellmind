from __future__ import annotations

from copy import deepcopy

import yaml

import shellmind.config as config_module
from shellmind.defaults import DEFAULT_CONFIG


def test_load_config_deep_merges_without_mutating_defaults(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({"ui": {"max_output_chars": 42}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    defaults_before = deepcopy(DEFAULT_CONFIG)

    loaded = config_module.load_config()

    assert loaded["ui"]["max_output_chars"] == 42
    assert loaded["ui"]["confirm_commands"] is True
    assert DEFAULT_CONFIG == defaults_before


def test_init_config_creates_directory_and_utf8_yaml(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "nested" / "shellmind"
    config_path = config_dir / "config.yaml"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    config_module.init_config()

    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == DEFAULT_CONFIG
