from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .client import status_badge
from .config import ProjectConfig
from .state import ProjectState, UIState, calculate_visible_window, format_short_text


def render_tui(state: UIState, term_height: int = 30) -> Layout:
    layout = Layout()
    total_projects = len(state.projects)

    # Height allocation
    # Header: 3, Footer: 1
    # Inspector: 5 in collapsed, ratio 2 in expanded
    # Logs: minimum 6 lines
    if state.is_expanded:
        table_height = min(max(5, total_projects + 3), max(6, term_height // 3))
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="table", size=table_height),
            Layout(name="inspector", ratio=2),
            Layout(name="logs", ratio=1),
            Layout(name="footer", size=1),
        )
    else:
        # Collapsed mode: give table reasonable room but ensure at least 8 lines for logs
        max_table_lines = max(5, term_height - 3 - 1 - 5 - 8)
        table_height = min(max(5, total_projects + 3), max_table_lines)
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="table", size=table_height),
            Layout(name="inspector", size=5),
            Layout(name="logs", ratio=1),
            Layout(name="footer", size=1),
        )

    # 1. Header
    cfg_name = state.config_file.name
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header_text = Text.from_markup(
        f" [bold magenta]🧠 Aristotle Multi-Repository Watcher[/bold magenta] "
        f"[dim]• Config: {cfg_name} • {now_str}[/dim]"
    )
    layout["header"].update(Panel(header_text, style="cyan", border_style="dim"))

    # 2. Table with scrolling and scrollbar
    visible_rows = max(2, table_height - 3)
    start_idx, end_idx = calculate_visible_window(state.selected_idx, total_projects, visible_rows)

    table = Table(box=None, expand=True, show_header=True, header_style="bold dim")
    table.add_column("", width=2, no_wrap=True)
    table.add_column("Repository : Branch", style="bold", no_wrap=True)
    table.add_column("Account", width=13, no_wrap=True)
    table.add_column("Task ID", width=10, no_wrap=True)
    table.add_column("Status", width=19, no_wrap=True)
    table.add_column("Queue", width=14, no_wrap=True)
    table.add_column("Policy", width=24, no_wrap=True)
    table.add_column("", width=2, justify="right", no_wrap=True)

    is_scrolling = total_projects > visible_rows

    for rel_idx, p_idx in enumerate(range(start_idx, end_idx)):
        p = state.projects[p_idx]
        is_sel = p_idx == state.selected_idx
        cursor = "[bold cyan]❯[/bold cyan]" if is_sel else " "
        row_style = "bold white" if is_sel else ""

        badge = status_badge(p.status, p.percent)
        task_str = p.current_task_id[:8] if p.current_task_id else "—"

        account_busy = any(
            other.is_busy and other.spec != p.spec
            for other in state.projects
            if other.cfg.account == p.cfg.account
        )

        if not p.cfg.watch_queue_and_send_messages:
            queue_str = f"⏸ PAUSED ({p.queue_count})"
            queue_style = "yellow"
        elif p.cfg.queue_loop_first_message:
            queue_str = f"🔁 LOOP ({p.queue_count})"
            queue_style = "cyan"
        elif account_busy and p.queue_count > 0:
            queue_str = f"⏳ WAITING ({p.queue_count})"
            queue_style = "yellow"
        else:
            queue_str = f"▶ ON ({p.queue_count})"
            queue_style = "green" if p.queue_count > 0 else "dim"

        # Scrollbar thumb
        if is_scrolling:
            thumb_start = int((start_idx / total_projects) * (end_idx - start_idx))
            thumb_len = max(1, int(((end_idx - start_idx) / total_projects) * (end_idx - start_idx)))
            thumb_end = thumb_start + thumb_len
            if thumb_start <= rel_idx < thumb_end:
                scroll_char = Text("█", style="bold cyan")
            else:
                scroll_char = Text("│", style="dim")
        else:
            scroll_char = Text("")

        table.add_row(
            cursor,
            Text(f"{p.repo_name}:{p.branch}", style=row_style),
            Text(p.cfg.account, style="dim"),
            Text(task_str, style="cyan" if p.current_task_id else "dim"),
            badge,
            Text(queue_str, style=queue_style),
            Text(p.cfg.pull.value, style="dim"),
            scroll_char,
        )

    if total_projects == 0:
        table.add_row("", Text("(No projects configured)", style="dim italic"), "", "", "", "", "", "")

    # Title & Subtitle with scroll info
    if is_scrolling:
        title = f"[bold]Projects Status[/bold] [cyan]({start_idx + 1}-{end_idx} of {total_projects})[/cyan]"
        more_above = start_idx > 0
        more_below = end_idx < total_projects
        if more_above and more_below:
            subtitle = f"[bold yellow]▲ {start_idx} above[/bold yellow]  •  [bold yellow]▼ {total_projects - end_idx} below[/bold yellow]"
        elif more_above:
            subtitle = f"[bold yellow]▲ {start_idx} more above[/bold yellow]"
        elif more_below:
            subtitle = f"[bold yellow]▼ {total_projects - end_idx} more below[/bold yellow]"
        else:
            subtitle = None
    else:
        title = f"[bold]Projects Status[/bold] [dim]({total_projects} total)[/dim]"
        subtitle = None

    layout["table"].update(Panel(table, title=title, subtitle=subtitle, border_style="cyan"))

    # 3. Selected Project Inspector
    cur = state.get_selected()
    if cur:
        if not state.is_expanded:
            prompt_preview = format_short_text(cur.prompt)
            end_preview = format_short_text(cur.end_msg)

            short_grid = Table.grid(padding=(0, 1))
            short_grid.add_column(style="bold cyan", width=11)
            short_grid.add_column(overflow="ellipsis")
            short_grid.add_row("📥 Prompt:", prompt_preview)
            short_grid.add_row("📤 Response:", end_preview)

            insp_panel = Panel(
                Group(
                    short_grid,
                    Text("\n[Enter/Space] Expand full prompt & response  •  [1-9 / ↑↓] Select project", style="dim italic"),
                ),
                title=f"[bold cyan]🔍 {cur.repo_name}:{cur.branch}[/bold cyan] (Collapsed)",
                border_style="magenta",
            )
        else:
            prompt_body = cur.prompt.strip() or "(No prompt recorded)"
            response_body = cur.end_msg.strip() if cur.end_msg else "(Task in progress or no response yet)"

            insp_panel = Panel(
                Group(
                    Text("📥 User Prompt (Full):", style="bold cyan"),
                    Panel(Text(prompt_body, style="white"), border_style="dim", expand=True),
                    Text("📤 Aristotle Response (Full):", style="bold green"),
                    Panel(Text(response_body, style="white"), border_style="dim", expand=True),
                    Text("[Enter/Space] Collapse view back to 1-line summary", style="dim italic"),
                ),
                title=f"[bold cyan]🔍 {cur.repo_name}:{cur.branch}[/bold cyan] (Expanded)",
                border_style="green",
            )
        layout["inspector"].update(insp_panel)

    # 4. Logs
    recent_logs = list(state.logs)[-max(5, term_height - 18):]
    log_group = []
    for line in recent_logs:
        try:
            log_group.append(Text.from_markup(line))
        except Exception:
            log_group.append(Text(line))

    layout["logs"].update(
        Panel(
            Group(*log_group) if log_group else Text("Waiting for events...", style="dim"),
            title="[bold]Live Events & Activity[/bold]",
            border_style="dim",
        )
    )

    # 5. Footer Help
    layout["footer"].update(
        Text(
            " [↑/k] Up  [↓/j] Down  [g/G] Top/Bottom  [u/d] PageUp/Dn  [Enter] Expand  [r] Refresh  [q] Quit",
            style="bold white on #1f2024",
        )
    )

    return layout
