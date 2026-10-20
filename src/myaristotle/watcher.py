import shutil
import subprocess
import asyncio
from datetime import datetime
from pathlib import Path
import sys

import readchar
from readchar import key as K
from rich.console import Console
from rich.live import Live
from rich.markup import escape

from aristotlelib import AgentTask, Project

from .client import (
    TERMINAL_STATUSES,
    extract_status_str,
    extract_task_id,
    fetch_project_tasks,
    get_task_info,
    setup_auth_for_account,
    submit_prompt_to_project,
)
from .config import AppConfig, ProjectConfig, load_config, resolve_project_dir_and_branch
from .git_ops import format_continuation_prompt, get_git_branch
from .lock import WatcherLock
from .queue_manager import (
    find_or_create_queue_file,
    peek_next_message,
    pop_top_message,
    read_queue,
)
from .state import ProjectState, UIState
from .sync import format_sse_summary, monitor_task_sse, sync_completed_task
from .tui import render_tui

console = Console()



def project_matches_hibernate_target(p: ProjectState, target: str) -> bool:
    clean = target.strip()
    return clean in (p.spec, p.repo_name, f"{p.repo_name}:{p.branch}")


def check_hibernate_condition(targets: list[str], projects: list[ProjectState]) -> bool:
    if not targets or not projects:
        return False

    return all(
        (matched := [p for p in projects if project_matches_hibernate_target(p, target)])
        and all(
            p.has_initialized
            and not p.is_busy
            and not p.is_syncing
            and p.queue_count == 0
            and ("OUT_OF_BUDGET" not in p.status or not p.cfg.auto_continue_on_out_of_budget)
            and (p.status in TERMINAL_STATUSES or p.status == "IDLE")
            for p in matched
        )
        for target in targets
    )

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
    tag_label = fr"[bold cyan]\[{tag}\] [/bold cyan][dim]({p_state.cfg.account})[/dim]"
    repo_dir = p_state.repo_dir

    active_sse_task: asyncio.Task | None = None
    streamed_task_id: str | None = None

    while not ui_state.stop_requested:
        try:
            api_key = setup_auth_for_account(p_state.cfg.account, app_config)
            project = await Project.from_id(p_state.cfg.id)
            tasks = await fetch_project_tasks(project, limit=5)

            if not p_state.configured_branch:
                p_state.branch = get_git_branch(repo_dir)
                tag = f"{p_state.repo_name}:{p_state.branch}"
                tag_label = fr"[bold cyan]\[{tag}\] [/bold cyan][dim]({p_state.cfg.account})[/dim]"

            p_state.queue_count = len(read_queue(p_state.queue_file))

            # Task resolution guarding against eventual consistency polling lags:
            # If current task is running, don't fall back to older completed tasks if tasks[0] hasn't updated yet.
            matching_task = next((t for t in tasks if extract_task_id(t) == p_state.current_task_id), None) if (p_state.is_busy and p_state.current_task_id) else None

            if matching_task:
                latest_task = matching_task
            elif p_state.is_busy and p_state.current_task_id:
                try:
                    latest_task = await AgentTask.from_id(p_state.current_task_id)
                except Exception:
                    latest_task = None
            else:
                latest_task = tasks[0] if tasks else None

            if latest_task:
                status_str = extract_status_str(getattr(latest_task, "status", ""))
                task_id = extract_task_id(latest_task)
                is_new_task = (task_id != p_state.current_task_id)

                p_state.status = status_str
                p_state.current_task_id = task_id
                p_state.is_busy = status_str not in TERMINAL_STATUSES

                if is_new_task or not p_state.prompt or status_str in TERMINAL_STATUSES:
                    info = await get_task_info(latest_task, task_id)
                    if info:
                        p_state.prompt = info.prompt
                        p_state.end_msg = info.end_msg or ""
                        p_state.percent = info.percent
            elif not p_state.is_busy:
                status_str = "IDLE"
                p_state.status = status_str

            p_state.has_initialized = True
            render_event.set()

            # 1. Sync finished task
            if latest_task and status_str in TERMINAL_STATUSES:
                if active_sse_task and not active_sse_task.done():
                    active_sse_task.cancel()
                    active_sse_task = None
                    streamed_task_id = None

                effective_branch = p_state.configured_branch or get_git_branch(repo_dir)
                p_state.is_syncing = True
                try:
                    await sync_completed_task(
                        p_state.cfg.id,
                        latest_task,
                        p_state.cfg,
                        repo_dir,
                        effective_branch,
                        api_key,
                        tag,
                        ui_state,
                        render_event=render_event,
                    )
                finally:
                    p_state.is_syncing = False
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
                    f"{tag_label} ⏳ [yellow]OUT OF BUDGET detected![/yellow] Submitting continuation ({len(cont_prompt)} chars)..."
                )
                render_event.set()

                acc_lock = account_locks.setdefault(p_state.cfg.account, asyncio.Lock()) if account_locks is not None else None
                if acc_lock:
                    async with acc_lock:
                        if is_account_busy(p_state.cfg.account, ui_state.projects, p_state.spec):
                            new_task_id = None
                        else:
                            p_state.is_busy = True
                            new_task_id = await submit_prompt_to_project(project, p_state.cfg.id, cont_prompt)
                            if not new_task_id:
                                p_state.is_busy = False
                else:
                    new_task_id = await submit_prompt_to_project(project, p_state.cfg.id, cont_prompt)

                if new_task_id:
                    p_state.current_task_id = new_task_id
                    p_state.status = "RUNNING"
                    p_state.is_busy = True
                    p_state.prompt = cont_prompt
                    ui_state.add_log(f"{tag_label} 🚀 Continuation task {new_task_id[:8]} started!")
                    render_event.set()

            # 3. Dispatch next queued task
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
                                p_state.is_busy = True
                                new_task_id = await submit_prompt_to_project(project, p_state.cfg.id, top_prompt)
                                if not new_task_id:
                                    p_state.is_busy = False
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
        elif k in ("c", "C"):
            if ui_state.hibernate_targets and not ui_state.hibernate_cancelled:
                ui_state.hibernate_cancelled = True
                ui_state.hibernate_countdown_start = None
                ui_state.add_log("[bold yellow]🛑 Auto-hibernate CANCELLED by user (press 'r' to re-arm).[/bold yellow]")
        elif k in ("r", "R"):
            if ui_state.hibernate_cancelled:
                ui_state.hibernate_cancelled = False
                ui_state.hibernate_triggered = False
                ui_state.add_log("[dim]Auto-hibernate re-armed.[/dim]")
            else:
                ui_state.add_log("[dim]Manual refresh requested.[/dim]")
        elif k in ("q", "Q", K.CTRL_C, K.CTRL_D):
            ui_state.stop_requested = True
            render_event.set()
            break
        elif k.isdigit() and 1 <= int(k) <= len(ui_state.projects):
            ui_state.selected_idx = int(k) - 1

        render_event.set()


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

    projects_state: list[ProjectState] = [
        create_project_state(spec, p_cfg)
        for spec, p_cfg in app_config.projects.items()
        if not filter_branch or (spec.endswith(f":{filter_branch}") or spec == filter_branch)
    ]

    ui_state = UIState(projects_state, resolved_cfg_path, resolved_queue_dir)
    ui_state.hibernate_targets = list(app_config.hibernate_after_queues_of_all_exhausted)
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
                            if ui_state.hibernate_targets != reloaded_cfg.hibernate_after_queues_of_all_exhausted:
                                ui_state.hibernate_targets = list(reloaded_cfg.hibernate_after_queues_of_all_exhausted)
                                ui_state.hibernate_cancelled = False
                                ui_state.hibernate_triggered = False

                            added_specs = new_specs - old_specs
                            for a_spec in added_specs:
                                if filter_branch and not (a_spec.endswith(f":{filter_branch}") or a_spec == filter_branch):
                                    continue
                                new_p = create_project_state(a_spec, reloaded_cfg.projects[a_spec])
                                projects_state.append(new_p)
                                worker_tasks[a_spec] = asyncio.create_task(
                                    project_worker(new_p, app_config, resolved_queue_dir, resolved_backlog_dir, ui_state, render_event, account_locks=account_locks)
                                )

                            ui_state.selected_idx = min(ui_state.selected_idx, max(0, len(projects_state) - 1))
                            change_desc = (([f"-{len(removed_specs)} removed"] if removed_specs else []) + ([f"+{len(added_specs)} added"] if added_specs else []))
                            detail = f" ({', '.join(change_desc)})" if change_desc else ""
                            ui_state.add_log(f"[bold yellow]🔄 Config hot-reloaded: {len(projects_state)} active projects{detail}[/bold yellow]")
                            render_event.set()
                    except Exception as e:
                        ui_state.add_log(f"[red]Config reload error: {escape(str(e))}[/red]")

                # Hibernate check
                if (
                    ui_state.hibernate_targets
                    and not ui_state.hibernate_triggered
                    and not ui_state.hibernate_cancelled
                ):
                    all_exhausted = check_hibernate_condition(ui_state.hibernate_targets, ui_state.projects)
                    if all_exhausted:
                        if ui_state.hibernate_countdown_start is None:
                            ui_state.hibernate_countdown_start = datetime.now()
                            targets_str = ", ".join(ui_state.hibernate_targets)
                            ui_state.add_log(
                                f"[bold yellow]💤 Queues exhausted for: {targets_str}. "
                                f"Hibernating in {ui_state.hibernate_countdown_seconds}s (press 'c' to cancel)...[/bold yellow]"
                            )
                            render_event.set()
                        else:
                            rem = ui_state.get_hibernate_countdown_remaining()
                            if rem is not None and rem <= 0:
                                ui_state.hibernate_triggered = True
                                ui_state.hibernate_countdown_start = None
                                ui_state.add_log("[bold magenta]💤 System hibernating now via systemctl hibernate...[/bold magenta]")
                                render_event.set()
                                live.update(render_tui(ui_state, console.size.height), refresh=True)
                                systemctl_bin = shutil.which("systemctl") or "/run/current-system/sw/bin/systemctl"
                                try:
                                    res = subprocess.run([systemctl_bin, "hibernate"], capture_output=True, text=True)
                                    if res.returncode != 0:
                                        ui_state.add_log(f"[bold red]❌ systemctl hibernate failed (code {res.returncode}): {escape(res.stderr.strip())}[/bold red]")
                                    else:
                                        ui_state.add_log("[bold green]💤 System resumed from hibernate.[/bold green]")
                                except Exception as e:
                                    ui_state.add_log(f"[bold red]❌ systemctl hibernate execution error: {escape(str(e))}[/bold red]")
                                render_event.set()
                    else:
                        if ui_state.hibernate_countdown_start is not None:
                            ui_state.hibernate_countdown_start = None
                            ui_state.add_log("[yellow]Hibernate countdown aborted: active task or non-empty queue detected.[/yellow]")
                            render_event.set()

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
