import asyncio
from datetime import datetime
import os
from pathlib import Path
from typing import Any
import fcntl
import sys

import readchar
from readchar import key as K
from rich.console import Console
from rich.live import Live
from rich.markup import escape

from aristotlelib import AgentTask, Project

from .client import (
    TERMINAL_STATUSES,
    execute_pull,
    extract_status_str,
    extract_task_id,
    fetch_project_tasks,
    get_synced_tasks,
    get_task_info,
    mark_task_synced,
    setup_auth_for_account,
    stream_task_events,
    submit_prompt_to_project,
)
from .config import AppConfig, ProjectConfig, PullPolicy, load_config, resolve_project_dir_and_branch
from .git_ops import (
    build_git_commit_message,
    format_continuation_prompt,
    get_git_branch,
    git_checkout,
    git_commit_changes,
    is_task_in_git,
)
from .queue_manager import (
    find_or_create_queue_file,
    peek_next_message,
    pop_top_message,
    read_queue,
)
from .tui import ProjectState, UIState, render_tui

console = Console()


def format_sse_summary(event_data: dict) -> str:
    content = event_data.get("content") or event_data.get("message") or event_data.get("explanation")
    if content:
        first_line = str(content).strip().splitlines()[0]
        return (first_line[:80] + "...") if len(first_line) > 80 else first_line
    ev_type = event_data.get("event_type")
    if ev_type:
        return f"Prover event ({ev_type})"
    return "Working..."


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

            summary = format_sse_summary(event)
            ui_state.add_log(f"{tag_label} {escape(summary)}")
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
) -> bool:
    tag_label = f"[bold cyan]\\[{tag}\\][/bold cyan]"
    term_id = extract_task_id(task_obj)
    if not term_id:
        return False

    should_commit = t_cfg.pull in (PullPolicy.PULL_AND_COMMIT, PullPolicy.PULL_AND_COMMIT_AND_PUSH)
    should_push = (t_cfg.pull == PullPolicy.PULL_AND_COMMIT_AND_PUSH)

    is_synced = (term_id in get_synced_tasks(project_id)) or (
        should_commit and is_task_in_git(term_id, branch, cwd=repo_dir)
    )
    if is_synced:
        return False

    task_info = await get_task_info(task_obj, term_id)
    if not task_info:
        return False

    ui_state.add_log(f"{tag_label} 📥 Downloading results for task {term_id[:8]}...")
    if repo_dir.is_dir() and t_cfg.configured_branch:
        git_checkout(t_cfg.configured_branch, cwd=repo_dir)

    if execute_pull(project_id, api_key, t_cfg.sync_only_paths, cwd=repo_dir):
        if should_commit and repo_dir.is_dir():
            msg = build_git_commit_message(
                task_info.task_id,
                task_info.status,
                task_info.prompt,
                task_info.end_msg,
            )
            git_commit_changes(msg, push=should_push, cwd=repo_dir)
            ui_state.add_log(f"{tag_label} 📝 Committed & pushed task {term_id[:8]}")
        else:
            ui_state.add_log(f"{tag_label} 📥 Download complete (commit=off)")
        mark_task_synced(project_id, term_id)
        return True
    return False


def is_account_busy(account: str, projects: list[ProjectState], current_spec: str) -> bool:
    """Checks if any other project under the same account is currently busy running a task."""
    return any(
        other.is_busy and other.spec != current_spec
        for other in projects
        if other.cfg.account == account
    )


async def project_worker(
    p_state: ProjectState,
    app_config: AppConfig,
    queue_dir: Path,
    backlog_dir: Path,
    ui_state: UIState,
    render_event: asyncio.Event,
    account_locks: dict[str, asyncio.Lock] | None = None,
):
    tag = f"{p_state.repo_name}:{p_state.branch}"
    tag_label = f"[bold cyan]\\[{tag}\\][/bold cyan] [dim]({p_state.cfg.account})[/dim]"
    repo_dir = p_state.repo_dir

    active_sse_task: asyncio.Task | None = None
    streamed_task_id: str | None = None

    while not ui_state.stop_requested:
        try:
            api_key = setup_auth_for_account(p_state.cfg.account, app_config)
            project = await Project.from_id(p_state.cfg.id)
            tasks = await fetch_project_tasks(project, limit=5)

            # Update current branch dynamically if no fixed branch configured
            if not p_state.configured_branch:
                p_state.branch = get_git_branch(repo_dir)
                tag = f"{p_state.repo_name}:{p_state.branch}"
                tag_label = f"[bold cyan]\\[{tag}\\][/bold cyan] [dim]({p_state.cfg.account})[/dim]"

            p_state.queue_count = len(read_queue(p_state.queue_file))
            latest_task = tasks[0] if tasks else None
            status_str = extract_status_str(getattr(latest_task, "status", "")) if latest_task else "IDLE"
            task_id = extract_task_id(latest_task)

            is_new_task = (task_id != p_state.current_task_id)
            p_state.status = status_str
            p_state.current_task_id = task_id
            p_state.is_busy = bool(latest_task and status_str not in TERMINAL_STATUSES)

            if latest_task and (is_new_task or not p_state.prompt or status_str in TERMINAL_STATUSES):
                info = await get_task_info(latest_task, task_id)
                if info:
                    p_state.prompt = info.prompt
                    p_state.end_msg = info.end_msg or ""
                    p_state.percent = info.percent

            render_event.set()

            # 1. Sync finished task
            if latest_task and status_str in TERMINAL_STATUSES:
                if active_sse_task and not active_sse_task.done():
                    active_sse_task.cancel()
                    active_sse_task = None
                    streamed_task_id = None

                effective_branch = p_state.configured_branch or get_git_branch(repo_dir)
                await sync_completed_task(
                    p_state.cfg.id,
                    latest_task,
                    p_state.cfg,
                    repo_dir,
                    effective_branch,
                    api_key,
                    tag,
                    ui_state,
                )
                render_event.set()

            # 2. AUTO-RECOVERY: Handle OUT_OF_BUDGET
            if (
                latest_task
                and "OUT_OF_BUDGET" in status_str
                and p_state.cfg.auto_continue_on_out_of_budget
                and not is_account_busy(p_state.cfg.account, ui_state.projects, p_state.spec)
            ):
                base_prompt = p_state.prompt or ""
                cont_prompt = format_continuation_prompt(base_prompt)

                ui_state.add_log(
                    f"{tag_label} ⏳ [yellow]OUT OF BUDGET detected![/yellow] "
                    f"Submitting continuation ({len(cont_prompt)} chars)..."
                )
                render_event.set()

                new_task_id = await submit_prompt_to_project(
                    project, p_state.cfg.id, cont_prompt
                )
                if new_task_id:
                    p_state.current_task_id = new_task_id
                    p_state.status = "RUNNING"
                    p_state.is_busy = True
                    p_state.prompt = cont_prompt
                    ui_state.add_log(f"{tag_label} 🚀 Continuation task {new_task_id[:8]} started!")
                    render_event.set()

            # 3. Dispatch next queued task (ensures no other project under same account is busy)
            elif (
                not p_state.is_busy
                and p_state.cfg.watch_queue_and_send_messages
                and not is_account_busy(p_state.cfg.account, ui_state.projects, p_state.spec)
            ):
                top_prompt = peek_next_message(p_state.queue_file)
                if top_prompt:
                    ui_state.add_log(
                        f"{tag_label} 🚀 Aristotle is idle. Submitting top prompt ({len(top_prompt)} chars)..."
                    )
                    render_event.set()
                    acc_lock = account_locks.setdefault(p_state.cfg.account, asyncio.Lock()) if account_locks is not None else None
                    if acc_lock:
                        async with acc_lock:
                            if is_account_busy(p_state.cfg.account, ui_state.projects, p_state.spec):
                                new_task_id = None
                            else:
                                new_task_id = await submit_prompt_to_project(project, p_state.cfg.id, top_prompt)
                    else:
                        new_task_id = await submit_prompt_to_project(project, p_state.cfg.id, top_prompt)
                    if new_task_id:
                        if not p_state.cfg.queue_loop_first_message:
                            pop_top_message(p_state.queue_file, backlog_dir=backlog_dir)

                        p_state.queue_count = len(read_queue(p_state.queue_file))
                        p_state.current_task_id = new_task_id
                        p_state.status = "RUNNING"
                        p_state.is_busy = True
                        p_state.prompt = top_prompt
                        ui_state.add_log(
                            f"{tag_label} ✅ Task {new_task_id[:8]} started! ({p_state.queue_count} remaining)"
                        )
                        render_event.set()

            # 4. SSE Streaming
            if p_state.is_busy and p_state.current_task_id:
                if streamed_task_id != p_state.current_task_id:
                    if active_sse_task and not active_sse_task.done():
                        active_sse_task.cancel()
                    ep_prefix = getattr(AgentTask, "endpoint_prefix", "task")
                    streamed_task_id = p_state.current_task_id
                    active_sse_task = asyncio.create_task(
                        monitor_task_sse(ep_prefix, p_state.current_task_id, api_key, tag, p_state, ui_state, render_event)
                    )

        except asyncio.CancelledError:
            if active_sse_task and not active_sse_task.done():
                active_sse_task.cancel()
            break
        except Exception as e:
            err_msg = str(e).strip() or repr(e)
            if "too many projects in progress" in err_msg.lower() or getattr(e, "status_code", None) == 429:
                ui_state.add_log(f"{tag_label} ⏳ [yellow]Account '{p_state.cfg.account}' at capacity on Aristotle. Waiting for active task to finish...[/yellow]")
                render_event.set()
                await asyncio.sleep(10)
                continue
            ui_state.add_log(f"{tag_label} [red]Error ({type(e).__name__}): {escape(err_msg)}[/red]")
            render_event.set()
            await asyncio.sleep(6)
            continue

        await asyncio.sleep(4)


async def key_listener(ui_state: UIState, render_event: asyncio.Event):
    loop = asyncio.get_running_loop()
    while not ui_state.stop_requested:
        k = await loop.run_in_executor(None, readchar.readkey)
        if k in (K.UP, "k", "K"):
            ui_state.select_prev()
        elif k in (K.DOWN, "j", "J"):
            ui_state.select_next()
        elif k in ("g", K.HOME):
            ui_state.jump_to_top()
        elif k in ("G", K.END):
            ui_state.jump_to_bottom()
        elif k in ("u", K.PAGE_UP):
            ui_state.select_prev(step=5)
        elif k in ("d", K.PAGE_DOWN):
            ui_state.select_next(step=5)
        elif k in (K.ENTER, K.CR, " ", "e", "E"):
            ui_state.toggle_expanded()
        elif k in ("r", "R"):
            ui_state.add_log("[dim]Manual refresh requested.[/dim]")
        elif k in ("q", "Q", K.CTRL_C, K.CTRL_D):
            ui_state.stop_requested = True
            render_event.set()
            break
        elif k.isdigit() and 1 <= int(k) <= len(ui_state.projects):
            ui_state.selected_idx = int(k) - 1

        render_event.set()


class WatcherLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._file = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.lock_path, "a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._file.seek(0)
            self._file.truncate()
            self._file.write(f"{os.getpid()}\n")
            self._file.flush()
            return True
        except (BlockingIOError, OSError):
            return False

    def get_holder_pid(self) -> str | None:
        try:
            if self.lock_path.exists():
                return self.lock_path.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
        return None

    def release(self):
        if self._file:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
            except Exception:
                pass
            self._file = None


async def run_watcher(
    config_path: Path | None = None,
    queue_dir: Path | None = None,
    backlog_dir: Path | None = None,
    interval_override: int | None = None,
    filter_branch: str | None = None,
):
    app_config, resolved_cfg_path = load_config(config_path)
    lock = WatcherLock(resolved_cfg_path.parent / "watcher.lock")
    if not lock.acquire():
        holder_pid = lock.get_holder_pid()
        pid_info = f" (PID: {holder_pid})" if holder_pid else ""
        console.print(f"[bold red]❌ Error: Another watch_branches daemon is already running{pid_info}.[/bold red]")
        sys.exit(1)
    resolved_queue_dir = (queue_dir or (resolved_cfg_path.parent / "queue")).resolve()
    resolved_backlog_dir = (backlog_dir or (resolved_cfg_path.parent / "queue_backlog")).resolve()

    def create_project_state(spec: str, p_cfg: ProjectConfig) -> ProjectState:
        repo_dir = p_cfg.resolved_dir or resolve_project_dir_and_branch(spec)[0]
        configured_branch = p_cfg.configured_branch
        curr_branch = configured_branch or get_git_branch(repo_dir)
        queue_file = find_or_create_queue_file(repo_dir, curr_branch, resolved_queue_dir, spec=spec)
        return ProjectState(
            spec=spec,
            repo_name=repo_dir.name,
            branch=curr_branch,
            cfg=p_cfg,
            repo_dir=repo_dir,
            queue_file=queue_file,
            configured_branch=configured_branch,
        )

    projects_state: list[ProjectState] = []
    for spec, p_cfg in app_config.projects.items():
        if filter_branch and not (spec.endswith(f":{filter_branch}") or spec == filter_branch):
            continue
        projects_state.append(create_project_state(spec, p_cfg))

    ui_state = UIState(projects_state, resolved_cfg_path, resolved_queue_dir)
    ui_state.add_log(f"[bold green]System initialized ({len(projects_state)} projects active). Starting workers...[/bold green]")

    render_event = asyncio.Event()

    account_locks: dict[str, asyncio.Lock] = {}
    worker_tasks: dict[str, asyncio.Task] = {
        p.spec: asyncio.create_task(
            project_worker(p, app_config, resolved_queue_dir, resolved_backlog_dir, ui_state, render_event, account_locks=account_locks)
        )
        for p in projects_state
    }
    key_task = asyncio.create_task(key_listener(ui_state, render_event))

    with Live(console=console, screen=True, auto_refresh=False) as live:
        try:
            while not ui_state.stop_requested:
                now = datetime.now()
                if (now - ui_state.last_reload).total_seconds() >= 2:
                    ui_state.last_reload = now
                    try:
                        cur_mtime = resolved_cfg_path.stat().st_mtime
                        if cur_mtime != ui_state.last_cfg_mtime:
                            ui_state.last_cfg_mtime = cur_mtime
                            reloaded_cfg, _ = load_config(resolved_cfg_path)
                            app_config = reloaded_cfg

                            new_specs = set(reloaded_cfg.projects.keys())
                            old_specs = {p.spec for p in projects_state}

                            removed_specs = old_specs - new_specs
                            for r_spec in removed_specs:
                                if r_spec in worker_tasks:
                                    worker_tasks[r_spec].cancel()
                                    del worker_tasks[r_spec]
                            projects_state[:] = [p for p in projects_state if p.spec in new_specs]

                            for p in projects_state:
                                p.cfg = reloaded_cfg.projects[p.spec]

                            added_specs = new_specs - old_specs
                            for a_spec in added_specs:
                                if filter_branch and not (a_spec.endswith(f":{filter_branch}") or a_spec == filter_branch):
                                    continue
                                new_p = create_project_state(a_spec, reloaded_cfg.projects[a_spec])
                                projects_state.append(new_p)
                                worker_tasks[a_spec] = asyncio.create_task(
                                    project_worker(new_p, app_config, resolved_queue_dir, resolved_backlog_dir, ui_state, render_event, account_locks=account_locks)
                                )

                            if projects_state:
                                ui_state.selected_idx = min(ui_state.selected_idx, len(projects_state) - 1)
                            else:
                                ui_state.selected_idx = 0

                            change_desc = []
                            if removed_specs:
                                change_desc.append(f"-{len(removed_specs)} removed")
                            if added_specs:
                                change_desc.append(f"+{len(added_specs)} added")
                            detail = f" ({', '.join(change_desc)})" if change_desc else ""

                            ui_state.add_log(f"[bold yellow]🔄 Config hot-reloaded: {len(projects_state)} active projects{detail}[/bold yellow]")
                            render_event.set()
                    except Exception as e:
                        ui_state.add_log(f"[red]Config reload error: {escape(str(e))}[/red]")

                live.update(render_tui(ui_state, console.size.height), refresh=True)
                try:
                    await asyncio.wait_for(render_event.wait(), timeout=0.2)
                    render_event.clear()
                except asyncio.TimeoutError:
                    pass
        finally:
            ui_state.stop_requested = True
            for task in worker_tasks.values():
                task.cancel()
            key_task.cancel()
            lock.release()
