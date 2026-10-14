import asyncio
from pathlib import Path
from typing import Any

from rich.markup import escape

from .client import (
    execute_pull,
    extract_task_id,
    get_synced_tasks,
    get_task_info,
    mark_task_synced,
    stream_task_events,
)
from .config import ProjectConfig, PullPolicy
from .git_ops import (
    build_git_commit_message,
    git_checkout,
    git_commit_changes,
    is_task_in_git,
)
from .state import ProjectState, UIState


def format_sse_summary(event_data: dict) -> str:
    content = event_data.get("content") or event_data.get("message") or event_data.get("explanation")
    if content:
        first_line = str(content).strip().splitlines()[0]
        return (first_line[:80] + "...") if len(first_line) > 80 else first_line
    ev_type = event_data.get("event_type")
    return f"Prover event ({ev_type})" if ev_type else "Working..."


async def monitor_task_sse(
    endpoint_prefix: str,
    task_id: str,
    api_key: str,
    tag: str,
    p_state: ProjectState,
    ui_state: UIState,
    render_event: asyncio.Event,
):
    tag_label = f"[bold cyan]\\[{tag}\\][/bold cyan]"
    ui_state.add_log(f"{tag_label} 📡 Connected to live event stream for task {task_id[:8]}")
    render_event.set()

    try:
        async for event in stream_task_events(endpoint_prefix, task_id, api_key):
            pct = event.get("percent_complete")
            if pct is not None:
                p_state.percent = pct
            ui_state.add_log(f"{tag_label} {escape(format_sse_summary(event))}")
            render_event.set()
    except asyncio.CancelledError:
        return
    except Exception:
        pass
    finally:
        ui_state.add_log(f"{tag_label} 🏁 SSE stream closed for task {task_id[:8]}")
        render_event.set()


async def sync_completed_task(
    project_id: str,
    task_obj: Any,
    t_cfg: ProjectConfig,
    repo_dir: Path,
    branch: str,
    api_key: str,
    tag: str,
    ui_state: UIState,
    render_event: asyncio.Event | None = None,
) -> bool:
    tag_label = f"[bold cyan]\\[{tag}\\][/bold cyan]"
    term_id = extract_task_id(task_obj)
    if not term_id:
        return False

    should_commit = t_cfg.pull in (PullPolicy.PULL_AND_COMMIT, PullPolicy.PULL_AND_COMMIT_AND_PUSH)
    should_push = t_cfg.pull == PullPolicy.PULL_AND_COMMIT_AND_PUSH

    if (term_id in get_synced_tasks(project_id)) or (should_commit and is_task_in_git(term_id, branch, cwd=repo_dir)):
        return False

    task_info = await get_task_info(task_obj, term_id)
    if not task_info:
        return False

    ui_state.add_log(f"{tag_label} 📥 Downloading results for task {term_id[:8]}...")
    if repo_dir.is_dir() and t_cfg.configured_branch:
        git_checkout(t_cfg.configured_branch, cwd=repo_dir)

    def _on_rsync_prog(line: str):
        ui_state.add_log(f"{tag_label} 📥 {line}")
        if render_event:
            render_event.set()

    pull_ok = await asyncio.to_thread(
        execute_pull,
        project_id,
        api_key,
        t_cfg.sync_only_paths,
        cwd=repo_dir,
        excludes=t_cfg.files_to_ignore,
        on_progress=_on_rsync_prog,
    )
    if pull_ok:
        if should_commit and repo_dir.is_dir():
            msg = build_git_commit_message(task_info.task_id, task_info.status, task_info.prompt, task_info.end_msg)
            git_commit_changes(msg, push=should_push, cwd=repo_dir)
            ui_state.add_log(f"{tag_label} 📝 Committed & pushed task {term_id[:8]}")
        else:
            ui_state.add_log(f"{tag_label} 📥 Download complete (commit=off)")
        mark_task_synced(project_id, term_id)
        return True
    return False
