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


@dataclass
class ProjectState:
    spec: str
    repo_name: str
    branch: str
    cfg: ProjectConfig
    status: str = "INITIALIZING"
    percent: int | None = None
    current_task_id: str | None = None
    prompt: str = ""
    end_msg: str = ""
    queue_count: int = 0
    is_busy: bool = False


class UIState:
    def __init__(self, projects: list[ProjectState], config_file: Path, queue_dir: Path):
        self.projects = projects
        self.selected_idx = 0
        self.is_expanded = False
        self.logs: deque[str] = deque(maxlen=250)
        self.stop_requested = False
        self.config_file = config_file
        self.queue_dir = queue_dir
        self.last_reload = datetime.now()
        self.last_cfg_mtime = config_file.stat().st_mtime if config_file.exists() else 0.0

    def select_next(self):
        if self.projects:
            self.selected_idx = (self.selected_idx + 1) % len(self.projects)

    def select_prev(self):
        if self.projects:
            self.selected_idx = (self.selected_idx - 1) % len(self.projects)

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded

    def add_log(self, msg: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[dim]{now_str}[/dim] {msg}")

    def get_selected(self) -> ProjectState | None:
        if self.projects and 0 <= self.selected_idx < len(self.projects):
            return self.projects[self.selected_idx]
        return None


def format_short_text(text: str, max_chars: int = 90) -> str:
    clean = " ".join(text.strip().splitlines())
    if len(clean) > max_chars:
        return clean[:max_chars] + "..."
    return clean or "(none)"


def render_tui(state: UIState, term_height: int = 30) -> Layout:
    layout = Layout()

    # Dynamic layout sizing
    table_size = max(5, len(state.projects) + 4)
    if state.is_expanded:
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="table", size=table_size),
            Layout(name="inspector", ratio=2),
            Layout(name="logs", ratio=1),
            Layout(name="footer", size=1),
        )
    else:
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="table", size=table_size),
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

    # 2. Sticky Top Table
    table = Table(box=None, expand=True, show_header=True, header_style="bold dim")
    table.add_column("", width=3)
    table.add_column("Repository : Branch", width=26)
    table.add_column("Account", width=14)
    table.add_column("Task ID", width=12)
    table.add_column("Status", width=22)
    table.add_column("Queue", width=14)
    table.add_column("Policy", width=24)

    for idx, p in enumerate(state.projects):
        is_sel = idx == state.selected_idx
        cursor = "[bold cyan]❯[/bold cyan]" if is_sel else " "
        row_style = "bold white" if is_sel else ""

        badge = status_badge(p.status, p.percent)
        task_str = p.current_task_id[:8] if p.current_task_id else "—"

        # Clear visual indicator of Queue state: ON vs PAUSED vs LOOP
        if not p.cfg.watch_queue_and_send_messages:
            queue_str = f"⏸ PAUSED ({p.queue_count})"
            queue_style = "yellow"
        elif p.cfg.queue_loop_first_message:
            queue_str = f"🔁 LOOP ({p.queue_count})"
            queue_style = "cyan"
        else:
            queue_str = f"▶ ON ({p.queue_count})"
            queue_style = "green" if p.queue_count > 0 else "dim"

        table.add_row(
            cursor,
            Text(f"{p.repo_name}:{p.branch}", style=row_style),
            Text(p.cfg.account, style="dim"),
            Text(task_str, style="cyan" if p.current_task_id else "dim"),
            badge,
            Text(queue_str, style=queue_style),
            Text(p.cfg.pull.value, style="dim"),
        )

    layout["table"].update(Panel(table, title="[bold]Projects Status[/bold]", border_style="cyan"))

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

    # 4. Logs (displays newest lines at the bottom, protected against markup errors)
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
            " [↑/k] Up  [↓/j] Down  [Enter/Space] Expand  [r] Refresh  [q/Ctrl+C] Quit",
            style="bold white on #1f2024",
        )
    )

    return layout
