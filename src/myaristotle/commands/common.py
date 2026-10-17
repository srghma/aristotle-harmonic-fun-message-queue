from pathlib import Path
import sys

from rich.console import Console
from rich_argparse import RichHelpFormatter

RichHelpFormatter.styles.update({
    "argparse.groups": "bold magenta",
    "argparse.args": "bold cyan",
    "argparse.metavar": "yellow",
    "argparse.help": "default",
    "argparse.prog": "bold magenta",
    "argparse.syntax": "bold yellow",
})

console = Console()
err_console = Console(stderr=True)


def resolve_target_project(cfg, target_input: str | None = None) -> tuple[str, any] | None:
    """Finds matching (spec, project_config) from input, current git directory, or config."""
    from ..git_ops import get_current_git_repo_and_branch

    # 1. Exact match on spec key or project ID
    if target_input:
        for spec, p in cfg.projects.items():
            if target_input == spec or target_input == p.id or target_input in spec:
                return spec, p

        cand = Path(target_input).resolve()
        if cand.is_dir():
            for spec, p in cfg.projects.items():
                if p.resolved_dir == cand or cand.name in spec:
                    return spec, p

    # 2. Match from current git repo / current working directory
    repo_root, _ = get_current_git_repo_and_branch()
    cur_dir = Path.cwd().resolve()
    for spec, p in cfg.projects.items():
        if repo_root and (p.resolved_dir == repo_root or repo_root.name in spec):
            return spec, p
        if p.resolved_dir == cur_dir or cur_dir.name in spec:
            return spec, p

    # 3. Fallback to first configured project
    if not target_input and cfg.projects:
        return next(iter(cfg.projects.items()))

    return None
