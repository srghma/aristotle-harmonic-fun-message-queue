import os
from pathlib import Path
import pytest
import yaml

from myaristotle.config import AppConfig, PullPolicy, expand_env_vars, load_config


def test_expand_env_vars(monkeypatch):
    monkeypatch.setenv("TEST_KEY_123", "secret-token")
    assert expand_env_vars("Bearer ${TEST_KEY_123}") == "Bearer secret-token"
    assert expand_env_vars("Bearer $TEST_KEY_123") == "Bearer secret-token"


def test_load_valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123456")
    cfg_data = {
        "accounts": {
            "main_acc": "${MY_API_KEY}"
        },
        "projects": {
            "~/projects/repo:main": {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main_acc",
                "pull": "pull_and_commit_and_push",
                "sync_only_paths": ["src/"],
                "watch_queue_and_send_messages": True,
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    app_cfg, resolved = load_config(cfg_file)
    assert app_cfg.get_api_key_for_account("main_acc") == "ak_123456"
    assert "~/projects/repo:main" in app_cfg.projects
    proj = app_cfg.projects["~/projects/repo:main"]
    assert proj.pull == PullPolicy.PULL_AND_COMMIT_AND_PUSH
    assert proj.watch_queue_and_send_messages is True
    assert proj.sync_only_paths == ["src/"]


def test_invalid_account_reference(tmp_path):
    cfg_data = {
        "accounts": {"acc1": "key1"},
        "projects": {
            "~/projects/repo:main": {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "non_existent_acc",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="not defined in accounts"):
        load_config(cfg_file)
