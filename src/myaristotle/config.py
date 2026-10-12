from enum import Enum
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from pydantic import BaseModel, Field, field_validator
import yaml


class PullPolicy(str, Enum):
    ONLY_PULL = "only_pull"
    PULL_AND_COMMIT = "pull_and_commit"
    PULL_AND_COMMIT_AND_PUSH = "pull_and_commit_and_push"


def parse_project_id(target: str | None) -> str:
    """Extracts raw UUID if given an Aristotle web URL or returns the UUID directly."""
    if not target:
        return ""
    target_str = str(target).strip()
    match = re.search(r"projects/([0-9a-fA-F-]{36})", target_str)
    if match:
        return match.group(1)
    match_uuid = re.search(
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        target_str,
    )
    if match_uuid:
        return match_uuid.group(1)
    return target_str


def expand_env_vars(text: str) -> str:
    """Replaces ${VAR} and $VAR with the environment variable value."""
    pattern = re.compile(r"\$\{?([A-Za-z0-9_]+)\}?")

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return pattern.sub(_replace, text)


def resolve_project_dir_and_branch(
    spec: str,
    base_projects_dir: Path | None = None,
) -> tuple[Path, str | None]:
    """Resolves a project spec (dirname, ~/path, /path, or path:branch) to (repo_dir, configured_branch).

    Fails with FileNotFoundError if the directory does not exist.
    """
    base_dir = (base_projects_dir or (Path.home() / "projects")).resolve()
    clean_spec = spec.strip()

    # 1. Check if the spec as a whole exists as a directory (even if it contains colons)
    expanded = Path(os.path.expandvars(os.path.expanduser(clean_spec))).resolve()
    if expanded.is_dir():
        return expanded, None

    in_projects = (base_dir / clean_spec).resolve()
    if in_projects.is_dir():
        return in_projects, None

    # 2. Check if spec contains ':branch'
    if ":" in clean_spec:
        dir_part, branch_part = clean_spec.rsplit(":", 1)
        branch = branch_part.strip() or None

        expanded_dir = Path(os.path.expandvars(os.path.expanduser(dir_part))).resolve()
        if expanded_dir.is_dir():
            return expanded_dir, branch

        in_projects_dir = (base_dir / dir_part).resolve()
        if in_projects_dir.is_dir():
            return in_projects_dir, branch

    raise FileNotFoundError(
        f"Project directory for spec '{spec}' does not exist on disk "
        f"(checked as-is and under '{base_dir}')."
    )


class ProjectConfig(BaseModel):
    id: str
    account: str
    pull: PullPolicy = PullPolicy.PULL_AND_COMMIT_AND_PUSH
    sync_only_paths: list[str] = Field(default_factory=list)
    watch_queue_and_send_messages: bool = False
    auto_continue_on_out_of_budget: bool = True
    queue_loop_first_message: bool = False
    interval: int | None = None
    resolved_dir: Path | None = None
    configured_branch: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _clean_id(cls, v: Any) -> str:
        return parse_project_id(str(v))

    @field_validator("pull", mode="before")
    @classmethod
    def _coerce_pull(cls, v: Any) -> PullPolicy:
        if isinstance(v, PullPolicy):
            return v
        s = str(v).strip().lower()
        for p in PullPolicy:
            if p.value == s:
                return p
        return PullPolicy.PULL_AND_COMMIT_AND_PUSH


class AppConfig(BaseModel):
    accounts: dict[str, str] = Field(default_factory=dict)
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)

    def get_api_key_for_account(self, account_name: str) -> str | None:
        raw_key = self.accounts.get(account_name)
        if not raw_key:
            return None
        expanded = expand_env_vars(raw_key).strip()
        if expanded.startswith("$"):
            return os.environ.get(expanded[1:])
        return expanded


def find_default_config_path() -> Path:
    """Locates config.yaml relative to package or in ~/.config/myaristotle/."""
    env_path = os.environ.get("MYARISTOTLE_CONFIG_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path).resolve()

    home_cfg = Path.home() / ".config" / "myaristotle" / "config.yaml"
    if home_cfg.is_file():
        return home_cfg.resolve()

    return home_cfg


def load_config(config_path: Path | None = None) -> tuple[AppConfig, Path]:
    path = (config_path or find_default_config_path()).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Aristotle config file not found at: {path}")

    raw_text = path.read_text(encoding="utf-8")
    expanded_text = expand_env_vars(raw_text)
    data = yaml.safe_load(expanded_text) or {}
    config = AppConfig.model_validate(data)

    # Validate accounts and directory existence
    for proj_spec, p_cfg in config.projects.items():
        if p_cfg.account not in config.accounts:
            raise ValueError(
                f"Project '{proj_spec}' references account '{p_cfg.account}', "
                f"which is not defined in accounts: {list(config.accounts.keys())}"
            )
        repo_dir, configured_branch = resolve_project_dir_and_branch(proj_spec)
        p_cfg.resolved_dir = repo_dir
        p_cfg.configured_branch = configured_branch

    return config, path
