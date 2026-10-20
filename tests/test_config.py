import os
from pathlib import Path
import pytest
import yaml

from myaristotle.config import (
    AppConfig,
    PullPolicy,
    expand_env_vars,
    load_config,
    resolve_project_dir_and_branch,
)


def test_expand_env_vars(monkeypatch):
    monkeypatch.setenv("TEST_KEY_123", "secret-token")
    assert expand_env_vars("Bearer ${TEST_KEY_123}") == "Bearer secret-token"
    assert expand_env_vars("Bearer $TEST_KEY_123") == "Bearer secret-token"


def test_resolve_project_dir_and_branch(tmp_path):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    repo1 = projects_dir / "myrepo"
    repo1.mkdir()

    # 1. Just dirname format
    d1, b1 = resolve_project_dir_and_branch("myrepo", base_projects_dir=projects_dir)
    assert d1 == repo1
    assert b1 is None

    # 2. Dirname with branch
    d2, b2 = resolve_project_dir_and_branch("myrepo:feature", base_projects_dir=projects_dir)
    assert d2 == repo1
    assert b2 == "feature"

    # 3. Directory containing colons in its name
    repo_colon = projects_dir / "repo:with:colons"
    repo_colon.mkdir()
    d3, b3 = resolve_project_dir_and_branch("repo:with:colons", base_projects_dir=projects_dir)
    assert d3 == repo_colon
    assert b3 is None

    # 4. Non-existent directory must fail
    with pytest.raises(FileNotFoundError, match="does not exist on disk"):
        resolve_project_dir_and_branch("nonexistent_repo", base_projects_dir=projects_dir)


def test_load_valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123456")
    repo = tmp_path / "repo"
    repo.mkdir()

    cfg_data = {
        "accounts": {
            "main_acc": "${MY_API_KEY}"
        },
        "projects": {
            str(repo) + ":main": {
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
    assert f"{repo}:main" in app_cfg.projects
    proj = app_cfg.projects[f"{repo}:main"]
    assert proj.pull == PullPolicy.PULL_AND_COMMIT_AND_PUSH
    assert proj.watch_queue_and_send_messages is True
    assert proj.resolved_dir == repo
    assert proj.configured_branch == "main"


def test_fail_when_dir_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123456")
    cfg_data = {
        "accounts": {"main_acc": "${MY_API_KEY}"},
        "projects": {
            "totally_missing_project_dir": {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main_acc",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="does not exist on disk"):
        load_config(cfg_file)


def test_invalid_account_reference(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    cfg_data = {
        "accounts": {"acc1": "key1"},
        "projects": {
            str(repo): {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "non_existent_acc",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="not defined in accounts"):
        load_config(cfg_file)


def test_files_to_ignore_default_and_custom(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123")
    repo = tmp_path / "repo"
    repo.mkdir()

    cfg_data = {
        "accounts": {"main": "${MY_API_KEY}"},
        "files_to_ignore": ["*.typ", "notes/"],
        "projects": {
            str(repo): {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main",
                "files_to_ignore": ["custom_local.txt"],
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    app_cfg, _ = load_config(cfg_file)
    assert app_cfg.files_to_ignore == ["*.typ", "notes/"]
    proj = app_cfg.projects[str(repo)]
    assert proj.files_to_ignore == ["*.typ", "notes/", "custom_local.txt"]


def test_files_to_ignore_default_empty_when_not_set(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123")
    repo = tmp_path / "repo"
    repo.mkdir()

    cfg_data = {
        "accounts": {"main": "${MY_API_KEY}"},
        "projects": {
            str(repo): {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    app_cfg, _ = load_config(cfg_file)
    assert app_cfg.files_to_ignore == []
    proj = app_cfg.projects[str(repo)]
    assert proj.files_to_ignore == []


def test_hibernate_after_queues_of_all_exhausted_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123")
    repo = tmp_path / "myrepo"
    repo.mkdir()

    cfg_data = {
        "accounts": {"main": "${MY_API_KEY}"},
        "hibernate_after_queues_of_all_exhausted": ["myrepo"],
        "projects": {
            str(repo): {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    app_cfg, _ = load_config(cfg_file)
    assert app_cfg.hibernate_after_queues_of_all_exhausted == ["myrepo"]


def test_hibernate_after_queues_of_all_exhausted_invalid_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "ak_123")
    repo = tmp_path / "myrepo"
    repo.mkdir()

    cfg_data = {
        "accounts": {"main": "${MY_API_KEY}"},
        "hibernate_after_queues_of_all_exhausted": ["non_existent_project"],
        "projects": {
            str(repo): {
                "id": "6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
                "account": "main",
            }
        }
    }
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.dump(cfg_data), encoding="utf-8")

    with pytest.raises(ValueError, match="hibernate_after_queues_of_all_exhausted references unknown project"):
        load_config(cfg_file)
