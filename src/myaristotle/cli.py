import argparse
import asyncio
import os
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aristotlelib import Project
from aristotlelib.project import AgentQuestionsSetting

from .client import (
    execute_pull,
    fetch_project_tasks,
    fetch_tasks_info,
    get_task_info,
    setup_auth_for_account,
    status_badge,
)
from .config import load_config
from .git_ops import (
    build_git_commit_message,
    extract_first_line_prompt,
    get_current_git_repo_and_branch,
    get_git_branch,
    git_commit_changes,
)
from .queue_manager import (
    find_or_create_queue_file,
    get_queue_file_path,
    pop_next_message,
    read_queue,
)
from .watcher import run_watcher

console = Console()
err_console = Console(stderr=True)


def select_account_interactive(accounts: list[str], cfg, default_acc: str | None = None) -> str | None:
    if not sys.stdin.isatty():
        if default_acc and default_acc in accounts:
            return default_acc
        return accounts[0] if accounts else None

    if len(accounts) == 1:
        return accounts[0]

    import readchar
    from readchar import key as K
    from rich.console import Group
    from rich.live import Live

    selected_idx = accounts.index(default_acc) if (default_acc and default_acc in accounts) else 0

    proj_counts = {}
    for p in cfg.projects.values():
        proj_counts[p.account] = proj_counts.get(p.account, 0) + 1

    def render_ui() -> Panel:
        table = Table(box=None, expand=True, show_header=True, header_style="bold dim")
        table.add_column("", width=3)
        table.add_column("#", width=3, style="dim")
        table.add_column("Account Name", width=22)
        table.add_column("Projects", width=14)
        table.add_column("API Key Status", width=20)

        for idx, acc in enumerate(accounts):
            is_sel = idx == selected_idx
            prefix = "[bold cyan]❯[/bold cyan]" if is_sel else " "
            style = "bold cyan" if is_sel else ""

            key_val = cfg.get_api_key_for_account(acc)
            key_status = "[green]✓ Key present[/green]" if key_val else "[red]✗ Key missing[/red]"
            count = proj_counts.get(acc, 0)
            proj_str = f"[dim]{count} active[/dim]" if count else "[dim]0 active[/dim]"

            table.add_row(prefix, str(idx + 1), Text(acc, style=style), proj_str, key_status)

        return Panel(
            Group(
                table,
                Text("\n[↑/k] Up  [↓/j] Down  [1-9] Jump  [Enter] Select  [q/Esc] Cancel", style="dim italic"),
            ),
            title="[bold magenta]👤 Select Aristotle Account[/bold magenta]",
            border_style="cyan",
            expand=False,
        )

    with Live(render_ui(), console=console, screen=True, auto_refresh=False) as live:
        while True:
            live.update(render_ui(), refresh=True)
            k = readchar.readkey()
            if k in (K.UP, "k", "K"):
                selected_idx = max(0, selected_idx - 1)
            elif k in (K.DOWN, "j", "J"):
                selected_idx = min(len(accounts) - 1, selected_idx + 1)
            elif k in (K.ENTER, K.CR):
                return accounts[selected_idx]
            elif k in (K.ESC, "q", "Q", K.CTRL_C, K.CTRL_D):
                return None
            elif k.isdigit() and 1 <= int(k) <= len(accounts):
                return accounts[int(k) - 1]


def select_task_interactive(tasks_info: list, project_id: str):
    if not sys.stdin.isatty():
        return tasks_info[0] if tasks_info else None

    import readchar
    from readchar import key as K
    from rich.live import Live

    selected_idx = 0

    def render_ui() -> Panel:
        table = Table(box=None, expand=True, show_header=True, header_style="bold dim")
        table.add_column("", width=3)
        table.add_column("Status", width=16)
        table.add_column("Task ID", width=10)
        table.add_column("Created", width=12)
        table.add_column("Prompt", overflow="ellipsis")

        for idx, item in enumerate(tasks_info):
            is_sel = idx == selected_idx
            prefix = "[bold cyan]❯[/bold cyan]" if is_sel else " "
            style = "bold cyan" if is_sel else ""
            created_short = item.created_at[5:16] if len(item.created_at) >= 16 else item.created_at
            first_line = extract_first_line_prompt(item.prompt, max_chars=50)

            table.add_row(
                prefix,
                status_badge(item.raw_status, item.percent),
                Text(item.task_id[:8], style=style),
                Text(created_short, style="dim"),
                Text(first_line, style=style),
            )

        cur = tasks_info[selected_idx]
        details = Table.grid(padding=(0, 2))
        details.add_column(style="bold")
        details.add_column()
        details.add_row("Task ID:", f"[cyan]{cur.task_id}[/cyan]")
        details.add_row("Status:", status_badge(cur.raw_status, cur.percent))
        details.add_row("Created:", f"[dim]{cur.created_at}[/dim]")

        preview_group = [
            table,
            Text("─" * 40, style="dim"),
            details,
            Text("\n📥 My Prompt:", style="bold cyan"),
            Panel(cur.prompt.strip() or "(No prompt)", border_style="dim", expand=True),
        ]

        if cur.is_terminal and cur.end_msg:
            preview_group.extend([
                Text("📤 Aristotle Response:", style="bold green"),
                Panel(cur.end_msg.strip(), border_style="dim", expand=True),
            ])

        preview_group.append(
            Text(
                "\n[↑/k] Up  [↓/j] Down  [1-9] Jump  [Enter] Select & Commit  [q/Esc] Cancel",
                style="dim italic",
            )
        )

        return Panel(
            table,
            title=f"[bold magenta]🧠 Aristotle Task Selector[/bold magenta] [dim]• {project_id}[/dim]",
            border_style="cyan",
        )

    with Live(render_ui(), console=console, screen=True, auto_refresh=False) as live:
        while True:
            live.update(render_ui(), refresh=True)
            k = readchar.readkey()
            if k in (K.UP, "k", "K"):
                selected_idx = max(0, selected_idx - 1)
            elif k in (K.DOWN, "j", "J"):
                selected_idx = min(len(tasks_info) - 1, selected_idx + 1)
            elif k in (K.ENTER, K.CR):
                return tasks_info[selected_idx]
            elif k in (K.ESC, "q", "Q", K.CTRL_C, K.CTRL_D):
                return None
            elif k.isdigit() and 1 <= int(k) <= len(tasks_info):
                selected_idx = int(k) - 1


def main():
    parser = argparse.ArgumentParser(description="myaristotle - Aristotle task watcher, puller, and queue runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. watch_and_pull
    p_watch = subparsers.add_parser("watch_and_pull", aliases=["watch", "wp", "watch_branches", "wb"])
    p_watch.add_argument("--config", "-c", type=Path, default=None, help="Path to config.yaml")
    p_watch.add_argument("--queue-dir", "-q", type=Path, default=None, help="Path to queue directory")
    p_watch.add_argument("--interval", "-i", type=int, default=None, help="Polling interval in seconds")
    p_watch.add_argument("--branch", "-b", type=str, default=None, help="Filter specific branch or target spec")
    p_watch.add_argument("--backlog-dir", "-k", type=Path, default=None, help="Path to queue backlog directory")

    # 2. status / last3
    p_last = subparsers.add_parser("last_3_tasks_my_prompts_and_its_end_message", aliases=["last3", "status"])
    p_last.add_argument("target", nargs="?", default=None, help="Project ID or project target spec")
    p_last.add_argument("--config", "-c", type=Path, default=None)

    # 3. pull_force
    p_pull = subparsers.add_parser("pull_force", aliases=["pull"])
    p_pull.add_argument("target", nargs="?", default=None)
    p_pull.add_argument("paths", nargs="*", default=[])
    p_pull.add_argument("--config", "-c", type=Path, default=None)

    # 4. commit_msg
    p_msg = subparsers.add_parser("task_to_git_message", aliases=["commit_msg", "msg"])
    p_msg.add_argument("target", nargs="?", default=None)
    p_msg.add_argument("--task-id", "-t", default=None)
    p_msg.add_argument("--latest", action="store_true")
    p_msg.add_argument("--commit", action="store_true")
    p_msg.add_argument("--no-push", action="store_true")
    p_msg.add_argument("--config", "-c", type=Path, default=None)

    # 5. queue commands
    p_q = subparsers.add_parser("queue")
    q_subs = p_q.add_subparsers(dest="queue_action", required=True)

    q_list = q_subs.add_parser("list", aliases=["ls"])
    q_list.add_argument("--config", "-c", type=Path, default=None)

    q_show = q_subs.add_parser("show")
    q_show.add_argument("target")
    q_show.add_argument("--config", "-c", type=Path, default=None)

    q_pop = q_subs.add_parser("pop")
    q_pop.add_argument("target")
    q_pop.add_argument("--config", "-c", type=Path, default=None)

    # 6. submit / formalize command
    p_sub = subparsers.add_parser("submit", aliases=["formalize", "new"], help="Submit directory to Aristotle and add to config")
    p_sub.add_argument("target", nargs="?", default=".", help="Target project directory (default: current directory)")
    p_sub.add_argument("--prompt", "-p", default="formalize", help="Initial prompt (default: 'formalize')")
    p_sub.add_argument("--account", "-a", default=None, help="Aristotle account name from config.yaml (if omitted, opens interactive selector)")
    p_sub.add_argument("--pull", default="pull_and_commit_and_push", choices=["only_pull", "pull_and_commit", "pull_and_commit_and_push"], help="Pull policy")
    p_sub.add_argument("--branch", "-b", default=None, help="Branch name override")
    p_sub.add_argument("--config", "-c", type=Path, default=None, help="Path to config.yaml")
    p_sub.add_argument("--queue-dir", "-q", type=Path, default=None, help="Path to queue directory")

    args = parser.parse_args()

    if args.command in ("watch_and_pull", "watch", "wp", "watch_branches", "wb"):
        asyncio.run(run_watcher(
            config_path=args.config,
            queue_dir=args.queue_dir,
            backlog_dir=args.backlog_dir,
            interval_override=args.interval,
            filter_branch=args.branch,
        ))

    elif args.command in ("last_3_tasks_my_prompts_and_its_end_message", "last3", "status"):
        cfg, _ = load_config(args.config)
        target_spec = args.target
        p_cfg = None

        if target_spec and target_spec in cfg.projects:
            p_cfg = cfg.projects[target_spec]
        else:
            repo_root, _ = get_current_git_repo_and_branch()
            for spec, p in cfg.projects.items():
                if repo_root and (p.resolved_dir == repo_root or repo_root.name in spec):
                    p_cfg = p
                    target_spec = spec
                    break
            if not p_cfg and cfg.projects:
                target_spec, p_cfg = next(iter(cfg.projects.items()))

        if not p_cfg:
            err_console.print("[red]Could not determine target project.[/red]")
            sys.exit(1)

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

    elif args.command in ("pull_force", "pull"):
        cfg, _ = load_config(args.config)
        repo_root, _ = get_current_git_repo_and_branch()
        p_cfg = None
        for spec, p in cfg.projects.items():
            if args.target and (args.target in spec or p.id == args.target):
                p_cfg = p
                break
            if not args.target and repo_root and (p.resolved_dir == repo_root or repo_root.name in spec):
                p_cfg = p
                break

        if not p_cfg:
            err_console.print("[red]Could not determine target project to pull.[/red]")
            sys.exit(1)

        api_key = setup_auth_for_account(p_cfg.account, cfg)
        paths = args.paths if args.paths else p_cfg.sync_only_paths
        execute_pull(p_cfg.id, api_key, paths=paths, cwd=repo_root)

    elif args.command in ("task_to_git_message", "commit_msg", "msg"):
        cfg, _ = load_config(args.config)
        repo_root, curr_branch = get_current_git_repo_and_branch()
        p_cfg = None
        for spec, p in cfg.projects.items():
            if args.target and (args.target in spec or p.id == args.target):
                p_cfg = p
                break
            if not args.target and repo_root and (p.resolved_dir == repo_root or repo_root.name in spec):
                p_cfg = p
                break

        if not p_cfg and cfg.projects:
            p_cfg = next(iter(cfg.projects.values()))

        if not p_cfg:
            err_console.print("[red]No projects configured.[/red]")
            sys.exit(1)

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

    elif args.command == "queue":
        cfg, cfg_file = load_config(args.config)
        q_dir = (args.config.parent / "queue") if args.config else (cfg_file.parent / "queue")

        if args.queue_action in ("list", "ls"):
            table = Table(title="[bold magenta]Aristotle Queues[/bold magenta]")
            table.add_column("Project Spec")
            table.add_column("Queued Tasks")
            table.add_column("Queue File")
            for spec, p in cfg.projects.items():
                branch = p.configured_branch or get_git_branch(p.resolved_dir)
                q_file = find_or_create_queue_file(p.resolved_dir, branch, q_dir, spec=spec)
                items = read_queue(q_file)
                table.add_row(spec, f"[cyan]{len(items)}[/cyan]", q_file.name)
            console.print(table)

        elif args.queue_action == "show":
            p_cfg = cfg.projects.get(args.target)
            if p_cfg:
                branch = p_cfg.configured_branch or get_git_branch(p_cfg.resolved_dir)
                q_file = find_or_create_queue_file(p_cfg.resolved_dir, branch, q_dir, spec=args.target)
            else:
                q_file = get_queue_file_path(args.target, q_dir)
            items = read_queue(q_file)
            if not items:
                console.print(f"[dim]Queue for '{args.target}' ({q_file.name}) is empty.[/dim]")
            for idx, item in enumerate(items, 1):
                console.print(Panel(item, title=f"#{idx}", border_style="cyan"))

        elif args.queue_action == "pop":
            b_dir = cfg_file.parent / "queue_backlog"
            p_cfg = cfg.projects.get(args.target)
            if p_cfg:
                branch = p_cfg.configured_branch or get_git_branch(p_cfg.resolved_dir)
                q_file = find_or_create_queue_file(p_cfg.resolved_dir, branch, q_dir, spec=args.target)
            else:
                q_file = get_queue_file_path(args.target, q_dir)
            top = pop_next_message(q_file, loop_first=False, backlog_dir=b_dir)
            if top:
                console.print(f"[green]Popped top message (archived to backlog):[/green]\n{top}")
            else:
                console.print(f"[yellow]Queue for '{args.target}' ({q_file.name}) is already empty.[/yellow]")

    elif args.command in ("submit", "formalize", "new"):
        target_path = Path(args.target).resolve()
        if not target_path.is_dir():
            err_console.print(f"[red]Error: Target directory '{target_path}' does not exist.[/red]")
            sys.exit(1)

        cfg, cfg_file = load_config(args.config)

        # Select account
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

        api_key = setup_auth_for_account(account, cfg)
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

            # Spec key: use dirname format if located in ~/projects, else path
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


if __name__ == "__main__":
    main()
