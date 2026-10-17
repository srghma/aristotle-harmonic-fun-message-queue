import asyncio
from pathlib import Path
import sys

from aristotlelib import Project

from ..client import fetch_project_tasks, fetch_tasks_info, setup_auth_for_account
from ..config import load_config
from ..git_ops import build_git_commit_message, get_current_git_repo_and_branch, git_commit_changes
from ..interactive import select_task_interactive
from .common import RichHelpFormatter, err_console, resolve_target_project


def register(subparsers):
    p = subparsers.add_parser(
        "task_to_git_message",
        help="Generate or commit git message for task",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=None)
    p.add_argument("--task-id", "-t", default=None)
    p.add_argument("--latest", action="store_true")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--config", "-c", type=Path, default=None)
    p.set_defaults(func=handle)


def handle(args):
    cfg, _ = load_config(args.config)
    repo_root, _ = get_current_git_repo_and_branch()
    resolved = resolve_target_project(cfg, args.target)

    if not resolved:
        err_console.print("[red]No projects configured.[/red]")
        sys.exit(1)

    _, p_cfg = resolved
    setup_auth_for_account(p_cfg.account, cfg)

    async def _run_msg():
        proj = await Project.from_id(p_cfg.id)
        raw = await fetch_project_tasks(proj, limit=15)
        infos = await fetch_tasks_info(raw)
        chosen = infos[0] if args.latest else select_task_interactive(infos, p_cfg.id)
        if not chosen:
            return
        msg = build_git_commit_message(chosen.task_id, chosen.status, chosen.prompt, chosen.end_msg)
        if args.commit:
            git_commit_changes(msg, push=(not args.no_push), cwd=repo_root)
        else:
            print(msg)

    asyncio.run(_run_msg())
