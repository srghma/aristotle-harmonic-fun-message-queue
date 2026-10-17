from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from ..config import load_config
from ..git_ops import get_git_branch
from ..queue_backlog import deduplicate_all_backlogs
from ..queue_manager import (
    find_or_create_queue_file,
    get_queue_file_path,
    pop_next_message,
    read_queue,
)
from .common import RichHelpFormatter, console


def register(subparsers):
    p_q = subparsers.add_parser("queue", help="Manage project queues and backlogs", formatter_class=RichHelpFormatter)
    q_subs = p_q.add_subparsers(dest="queue_action", required=True)

    def sub(name, **kw):
        kw.setdefault("formatter_class", RichHelpFormatter)
        return q_subs.add_parser(name, **kw)

    q_list = sub("list", aliases=["ls"], help="List all project queues")
    q_list.add_argument("--config", "-c", type=Path, default=None)

    q_show = sub("show", help="Show queued messages for project")
    q_show.add_argument("target")
    q_show.add_argument("--config", "-c", type=Path, default=None)

    q_pop = sub("pop", help="Pop and archive next message")
    q_pop.add_argument("target")
    q_pop.add_argument("--config", "-c", type=Path, default=None)

    q_clean = sub("clean-backlog", aliases=["dedup-backlog"], help="Deduplicate existing backlog files")
    q_clean.add_argument("--config", "-c", type=Path, default=None)
    q_clean.add_argument("--all", "-a", action="store_true", help="Remove all duplicates, not only consecutive")

    p_q.set_defaults(func=handle)


def handle(args):
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

    elif args.queue_action in ("clean-backlog", "dedup-backlog"):
        b_dir = (args.config.parent / "queue_backlog") if args.config else (cfg_file.parent / "queue_backlog")
        stats = deduplicate_all_backlogs(b_dir, consecutive_only=(not getattr(args, "all", False)))
        if not stats:
            console.print(f"[dim]No duplicates found in {b_dir}.[/dim]")
        else:
            total_removed = sum(stats.values())
            console.print(f"[bold green]🧹 Removed {total_removed} duplicate messages across {len(stats)} backlog files:[/bold green]")
            for name, count in stats.items():
                console.print(f"  • [cyan]{name}[/cyan]: [yellow]-{count} duplicates[/yellow]")
