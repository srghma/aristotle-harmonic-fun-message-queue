from pathlib import Path
import sys

import readchar
from readchar import key as K
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .client import status_badge
from .git_ops import extract_first_line_prompt

console = Console()


def select_account_interactive(accounts: list[str], cfg, default_acc: str | None = None) -> str | None:
    if not sys.stdin.isatty():
        return default_acc if (default_acc and default_acc in accounts) else (accounts[0] if accounts else None)
    if len(accounts) == 1:
        return accounts[0]

    selected_idx = accounts.index(default_acc) if (default_acc and default_acc in accounts) else 0
    proj_counts = {acc: sum(1 for p in cfg.projects.values() if p.account == acc) for acc in accounts}

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
            Group(table, Text("\n[↑/k] Up  [↓/j] Down  [1-9] Jump  [Enter] Select  [q/Esc] Cancel", style="dim italic")),
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
            table.add_row(prefix, status_badge(item.raw_status, item.percent), Text(item.task_id[:8], style=style), Text(created_short, style="dim"), Text(first_line, style=style))

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
        preview_group.append(Text("\n[↑/k] Up  [↓/j] Down  [1-9] Jump  [Enter] Select & Commit  [q/Esc] Cancel", style="dim italic"))

        return Panel(table, title=f"[bold magenta]🧠 Aristotle Task Selector[/bold magenta] [dim]• {project_id}[/dim]", border_style="cyan")

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
