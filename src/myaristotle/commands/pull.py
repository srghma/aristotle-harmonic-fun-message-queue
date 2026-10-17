from pathlib import Path
import sys

from ..client import execute_pull, setup_auth_for_account
from ..config import load_config
from ..git_ops import get_current_git_repo_and_branch
from .common import RichHelpFormatter, console, err_console, resolve_target_project


def register(subparsers):
    p = subparsers.add_parser(
        "pull_force",
        help="Force pull results for target project",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("paths", nargs="*", default=[])
    p.add_argument("--config", "-c", type=Path, default=None)
    p.set_defaults(func=handle)


def handle(args):
    cfg, _ = load_config(args.config)
    resolved = resolve_target_project(cfg, args.target)

    if not resolved:
        err_console.print("[red]Could not determine target project to pull.[/red]")
        sys.exit(1)

    _, p_cfg = resolved
    repo_root, _ = get_current_git_repo_and_branch()
    api_key = setup_auth_for_account(p_cfg.account, cfg)
    paths = args.paths if args.paths else p_cfg.sync_only_paths

    execute_pull(
        p_cfg.id,
        api_key,
        paths=paths,
        cwd=repo_root,
        excludes=p_cfg.files_to_ignore,
        on_progress=lambda p: console.print(f"[dim]Sync: {p}[/dim]"),
    )
