import asyncio
import os
from pathlib import Path
import sys

from aristotlelib import Project
from aristotlelib.project import AgentQuestionsSetting

from ..client import setup_auth_for_account
from ..config import load_config
from ..git_ops import get_git_branch
from ..interactive import select_account_interactive
from ..queue_manager import find_or_create_queue_file
from .common import RichHelpFormatter, console, err_console


def register(subparsers):
    p = subparsers.add_parser(
        "formalize",
        aliases=["submit"],
        help="Submit directory to Aristotle and add to config",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("target", nargs="?", default=".", help="Target project directory")
    p.add_argument("--prompt", "-p", default="formalize", help="Initial prompt")
    p.add_argument("--account", "-a", default=None, help="Aristotle account name from config.yaml")
    p.add_argument(
        "--pull",
        default="pull_and_commit_and_push",
        choices=["only_pull", "pull_and_commit", "pull_and_commit_and_push"],
        help="Pull policy",
    )
    p.add_argument("--branch", "-b", default=None, help="Branch name override")
    p.add_argument("--config", "-c", type=Path, default=None, help="Path to config.yaml")
    p.add_argument("--queue-dir", "-q", type=Path, default=None, help="Path to queue directory")
    p.set_defaults(func=handle)


def handle(args):
    target_path = Path(args.target).resolve()
    if not target_path.is_dir():
        err_console.print(f"[red]Error: Target directory '{target_path}' does not exist.[/red]")
        sys.exit(1)

    cfg, cfg_file = load_config(args.config)

    account = args.account
    if not account:
        if not cfg.accounts:
            err_console.print("[red]Error: No accounts configured in config.yaml[/red]")
            sys.exit(1)
        default_acc = os.environ.get("ARISTOTLE_ACCOUNT") or ("sochor896" if "sochor896" in cfg.accounts else next(iter(cfg.accounts.keys())))
        account = select_account_interactive(list(cfg.accounts.keys()), cfg, default_acc=default_acc)
        if not account:
            console.print("[yellow]Submission cancelled.[/yellow]")
            sys.exit(0)

    if account not in cfg.accounts:
        err_console.print(f"[red]Error: Account '{account}' not found in config accounts: {list(cfg.accounts.keys())}[/red]")
        sys.exit(1)

    setup_auth_for_account(account, cfg)
    branch = args.branch or get_git_branch(target_path)

    console.print(f"[bold cyan]🚀 Submitting '{target_path.name}' to Aristotle using account '{account}'...[/bold cyan]")
    console.print(f"[dim]Prompt: {args.prompt}[/dim]")

    async def _run_submit():
        project = await Project.create_from_directory(
            prompt=args.prompt,
            project_dir=target_path,
            agent_questions_setting=AgentQuestionsSetting.DISABLED,
        )
        proj_id = project.project_id
        console.print(f"[bold green]✅ Successfully created Aristotle project: {proj_id}[/bold green]")

        home_projects = (Path.home() / "projects").resolve()
        if target_path.parent == home_projects:
            spec_key = target_path.name
        else:
            try:
                rel = target_path.relative_to(Path.home())
                spec_key = f"~/{rel}"
            except ValueError:
                spec_key = str(target_path)

        new_entry = (
            f'  "{spec_key}":\n'
            f'    id: "{proj_id}"\n'
            f'    account: {account}\n'
            f'    pull: {args.pull}\n'
            f'    watch_queue_and_send_messages: true\n'
        )

        config_text = cfg_file.read_text(encoding="utf-8")
        if f'"{spec_key}"' in config_text or f"'{spec_key}'" in config_text or f"{spec_key}:" in config_text:
            console.print(f"[yellow]Warning: '{spec_key}' already configured in {cfg_file}[/yellow]")
        else:
            cfg_file.write_text(config_text.rstrip() + "\n" + new_entry, encoding="utf-8")
            console.print(f"[bold green]📝 Added '{spec_key}' to {cfg_file}[/bold green]")

        q_dir = (args.queue_dir or (cfg_file.parent / "queue")).resolve()
        q_file = find_or_create_queue_file(target_path, branch, q_dir, spec=spec_key)
        console.print(f"[bold green]📄 Queue file ready: {q_file}[/bold green]")

    asyncio.run(_run_submit())
