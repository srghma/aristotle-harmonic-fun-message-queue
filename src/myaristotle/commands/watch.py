import asyncio
from pathlib import Path

from ..watcher import run_watcher
from .common import RichHelpFormatter


def register(subparsers):
    p = subparsers.add_parser(
        "watch_branches",
        aliases=["watch_and_pull"],
        help="Watch projects and sync tasks",
        formatter_class=RichHelpFormatter,
    )
    p.add_argument("--config", "-c", type=Path, default=None, help="Path to config.yaml")
    p.add_argument("--queue-dir", "-q", type=Path, default=None, help="Path to queue directory")
    p.add_argument("--interval", "-i", type=int, default=None, help="Polling interval in seconds")
    p.add_argument("--branch", "-b", type=str, default=None, help="Filter specific branch or target spec")
    p.add_argument("--backlog-dir", "-k", type=Path, default=None, help="Path to queue backlog directory")
    p.set_defaults(func=handle)


def handle(args):
    asyncio.run(run_watcher(
        config_path=args.config,
        queue_dir=args.queue_dir,
        backlog_dir=args.backlog_dir,
        interval_override=args.interval,
        filter_branch=args.branch,
    ))
