from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import ProjectConfig


@dataclass
class ProjectState:
    spec: str
    repo_name: str
    branch: str
    cfg: ProjectConfig
    repo_dir: Path = Path(".")
    queue_file: Path = Path(".")
    configured_branch: str | None = None
    status: str = "INITIALIZING"
    percent: int | None = None
    current_task_id: str | None = None
    prompt: str = ""
    end_msg: str = ""
    queue_count: int = 0
    is_busy: bool = False
    is_syncing: bool = False
    has_initialized: bool = False


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
        self.hibernate_targets: list[str] = []
        self.hibernate_triggered: bool = False
        self.hibernate_cancelled: bool = False
        self.hibernate_countdown_start: datetime | None = None
        self.hibernate_countdown_seconds: int = 15

    def get_hibernate_countdown_remaining(self) -> int | None:
        if self.hibernate_countdown_start is None:
            return None
        elapsed = (datetime.now() - self.hibernate_countdown_start).total_seconds()
        return max(0, int(self.hibernate_countdown_seconds - elapsed))

    def select_next(self, step: int = 1):
        if self.projects:
            self.selected_idx = (self.selected_idx + step) % len(self.projects)

    def select_prev(self, step: int = 1):
        if self.projects:
            self.selected_idx = (self.selected_idx - step) % len(self.projects)

    def jump_to_top(self):
        self.selected_idx = 0

    def jump_to_bottom(self):
        if self.projects:
            self.selected_idx = len(self.projects) - 1

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded

    def add_log(self, msg: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[dim]{now_str}[/dim] {msg}")

    def get_selected(self) -> ProjectState | None:
        return self.projects[self.selected_idx] if (self.projects and 0 <= self.selected_idx < len(self.projects)) else None


def format_short_text(text: str, max_chars: int = 90) -> str:
    clean = " ".join(text.strip().splitlines())
    return (clean[:max_chars] + "...") if len(clean) > max_chars else (clean or "(none)")


def calculate_visible_window(
    selected_idx: int,
    total_items: int,
    max_visible: int,
) -> tuple[int, int]:
    """Calculates [start_idx, end_idx) window that keeps selected_idx centered."""
    if total_items <= max_visible:
        return 0, total_items
    half = max_visible // 2
    start = max(0, min(selected_idx - half, total_items - max_visible))
    return start, min(total_items, start + max_visible)
