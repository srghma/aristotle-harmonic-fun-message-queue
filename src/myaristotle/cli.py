import argparse
import asyncio
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aristotlelib import Project

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
    git_commit_changes,
)
from .queue_manager import (
    get_queue_file_path,
    pop_next_message,
    read_queue,
    write_queue,
)
from .watcher import run_watcher

console = Console()
err_console = Console(stderr=True)


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

    # 1. watch_and_pull (default watcher)
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

    # queue list
    q_list = q_subs.add_parser("list", aliases=["ls"])
    q_list.add_argument("--config", "-c", type=Path, default=None)

    # queue show
    q_show = q_subs.add_parser("show")
    q_show.add_argument("target")
    q_show.add_argument("--config", "-c", type=Path, default=None)

    # queue pop
    q_pop = q_subs.add_parser("pop")
    q_pop.add_argument("target")
    q_pop.add_argument("--config", "-c", type=Path, default=None)

    args = parser.parse_args()

    # Command Execution
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
            repo_root, curr_branch = get_current_git_repo_and_branch()
            for spec, p in cfg.projects.items():
                if repo_root and repo_root.name in spec and (not curr_branch or curr_branch in spec):
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
            if not args.target and repo_root and repo_root.name in spec:
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
        p_cfg = next(iter(cfg.projects.values())) if cfg.projects else None
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
        q_dir = cfg_file.parent / "queue"

        if args.queue_action in ("list", "ls"):
            table = Table(title="[bold magenta]Aristotle Queues[/bold magenta]")
            table.add_column("Project Spec")
            table.add_column("Queued Tasks")
            table.add_column("Queue File")
            for spec in cfg.projects:
                items = read_queue(spec, q_dir)
                f_path = get_queue_file_path(spec, q_dir)
                table.add_row(spec, f"[cyan]{len(items)}[/cyan]", f_path.name)
            console.print(table)

        elif args.queue_action == "show":
            items = read_queue(args.target, q_dir)
            if not items:
                console.print(f"[dim]Queue for '{args.target}' is empty.[/dim]")
            for idx, item in enumerate(items, 1):
                console.print(Panel(item, title=f"#{idx}", border_style="cyan"))

        elif args.queue_action == "pop":
            b_dir = cfg_file.parent / "queue_backlog"
            top = pop_next_message(args.target, q_dir, loop_first=False, backlog_dir=b_dir)
            if top:
                console.print(f"[green]Popped top message (archived to backlog):[/green]\n{top}")
            else:
                console.print(f"[yellow]Queue for '{args.target}' is already empty.[/yellow]")


if __name__ == "__main__":
    main()
