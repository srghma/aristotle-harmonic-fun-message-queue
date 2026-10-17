import asyncio
from pathlib import Path
import sys

from aristotlelib import Project
from rich.panel import Panel

from ..client import fetch_project_tasks, fetch_tasks_info, setup_auth_for_account, status_badge
from ..config import load_config
from .common import RichHelpFormatter, console, err_console, resolve_target_project


def register(subparsers):
    p = subparsers.add_parser(
        "last_3_tasks_my_prompts_and_its_end_message",
        help="Display status and last 3 prompts with responses",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=None, help="Project ID or project target spec")
    p.add_argument("--config", "-c", type=Path, default=None)
    p.set_defaults(func=handle)


def handle(args):
    cfg, _ = load_config(args.config)
    resolved = resolve_target_project(cfg, args.target)

    if not resolved:
        err_console.print("[red]Could not determine target project.[/red]")
        sys.exit(1)

    target_spec, p_cfg = resolved
    setup_auth_for_account(p_cfg.account, cfg)

    async def _run_status():
        proj = await Project.from_id(p_cfg.id)
        raw = await fetch_project_tasks(proj, limit=3)
        infos = await fetch_tasks_info(raw)
        console.print(f"\n[bold magenta]🚀 Target:[/bold magenta] [cyan]{target_spec}[/cyan] ({p_cfg.id})\n")
        for t in infos:
            badge = status_badge(t.raw_status, t.percent)
            console.print(Panel(
                f"Status:  {t.status}\nCreated: {t.created_at}\n\n📥 Prompt:\n{t.prompt}\n\n📤 Aristotle Response:\n{t.end_msg or '(None)'}",
                title=f"Task {t.task_id}",
                subtitle=badge.plain,
                border_style="magenta",
            ))

    asyncio.run(_run_status())
