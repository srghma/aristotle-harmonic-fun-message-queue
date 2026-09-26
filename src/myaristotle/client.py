import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

import httpx
from rich.console import Console
from rich.text import Text

import aristotlelib
from aristotlelib import AgentTask, FollowUpMode, Project, set_api_key
import aristotlelib.api_request
import aristotlelib.aristotle_object

from .config import AppConfig
from .git_ops import collect_rsync_excludes_for_git
from contextvars import ContextVar
import aristotlelib.api_request

_current_api_key: ContextVar[str | None] = ContextVar("_current_api_key", default=None)

# Patch aristotlelib's get_api_key to be asyncio-task safe
if hasattr(aristotlelib.api_request, "get_api_key"):
    _orig_get_api_key = aristotlelib.api_request.get_api_key

    def _context_aware_get_api_key() -> str:
        ctx_key = _current_api_key.get()
        if ctx_key:
            return ctx_key
        return _orig_get_api_key()

    aristotlelib.api_request.get_api_key = _context_aware_get_api_key

console = Console()
err_console = Console(stderr=True)

CACHE_DIR = Path.home() / ".cache" / "aristotle"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = getattr(aristotlelib.api_request, "BASE_URL", "https://aristotle.harmonic.fun/api/v3")

TERMINAL_STATUSES = {
    "COMPLETE",
    "COMPLETED",
    "COMPLETE_WITH_ERRORS",
    "FAILED",
    "CANCELLED",
    "CANCELED",
    "ERROR",
    "SUCCESS",
    "OUT_OF_BUDGET",
}
NON_USER_EVENT_TYPES = {2, 3, 4, 5, 6, 7, 8, 9, 16}


@dataclass
class TaskInfo:
    task_id: str
    status: str
    raw_status: Any
    percent: int | None
    created_at: str
    prompt: str
    end_msg: str | None
    is_terminal: bool
    from_cache: bool = False
    task_obj: Any = None


def update_aristotle_client_auth(api_key: str):
    os.environ["ARISTOTLE_API_KEY"] = api_key
    try:
        set_api_key(api_key)
    except Exception:
        pass

    for mod in (aristotlelib, aristotlelib.api_request, aristotlelib.aristotle_object):
        for attr in ("api_key", "API_KEY", "_api_key"):
            if hasattr(mod, attr):
                setattr(mod, attr, api_key)


def setup_auth_for_account(account_name: str, config: AppConfig) -> str:
    key = config.get_api_key_for_account(account_name)
    if not key or key.startswith("${"):
        raise ValueError(f"Environment variable for account '{account_name}' is not set or empty!")
    _current_api_key.set(key)
    update_aristotle_client_auth(key)
    return key


def extract_status_str(status_raw: Any) -> str:
    return str(getattr(status_raw, "value", status_raw)).split(".")[-1].upper()


def status_badge(status_raw: Any, percent: int | None = None) -> Text:
    s = extract_status_str(status_raw)
    pct = f" ({percent}%)" if percent is not None and ("PROGRESS" in s or "RUNNING" in s) else ""
    if "PROGRESS" in s or "RUNNING" in s:
        return Text.from_markup(f"[yellow]🔄 {s}{pct}[/yellow]")
    if "ERROR" in s:
        return Text.from_markup(f"[red]⚠️  {s}[/red]")
    if "COMPLETE" in s or "SUCCESS" in s:
        return Text.from_markup(f"[green]✅ {s}[/green]")
    if "FAIL" in s:
        return Text.from_markup(f"[red]❌ {s}[/red]")
    if "OUT_OF_BUDGET" in s:
        return Text.from_markup(f"[yellow]⏳ {s}[/yellow]")
    if "QUEUE" in s:
        return Text.from_markup(f"[blue]⏳ {s}[/blue]")
    return Text.from_markup(f"[dim]ℹ️  {s}{pct}[/dim]")


def extract_task_id(task: Any) -> str | None:
    if isinstance(task, dict):
        return task.get("agent_task_id") or task.get("id") or task.get("object_id")
    for attr in ("agent_task_id", "id", "object_id"):
        val = getattr(task, attr, None)
        if val:
            return str(val)
    if hasattr(task, "model_dump"):
        try:
            d = task.model_dump()
            return d.get("agent_task_id") or d.get("id") or d.get("object_id")
        except Exception:
            pass
    return None


async def fetch_project_tasks(project: Project, limit: int = 10) -> list[Any]:
    res = project.get_tasks(limit=limit)
    if inspect.isawaitable(res):
        res = await res
    if isinstance(res, tuple):
        return res[0]
    if hasattr(res, "tasks"):
        return res.tasks
    return res if isinstance(res, list) else [res]


def get_synced_tasks(project_id: str) -> set[str]:
    f = CACHE_DIR / f"synced_{project_id}.json"
    if f.exists():
        try:
            return set(json.loads(f.read_text(encoding="utf-8")).get("synced_task_ids", []))
        except Exception:
            return set()
    return set()


def mark_task_synced(project_id: str, task_id: str):
    synced = get_synced_tasks(project_id)
    synced.add(task_id)
    f = CACHE_DIR / f"synced_{project_id}.json"
    try:
        f.write_text(json.dumps({"synced_task_ids": sorted(list(synced))}, indent=2), encoding="utf-8")
    except Exception:
        pass


async def extract_prompt_from_task(task: Any) -> str:
    if not task:
        return ""
    if hasattr(task, "get_events"):
        try:
            res = task.get_events(newest_first=False, limit=20)
            if inspect.isawaitable(res):
                res = await res
            events = res[0] if isinstance(res, tuple) else res
            if isinstance(events, list) and events:
                user_events = [
                    ev for ev in events
                    if getattr(ev, "event_type", None) == 1
                    or (
                        getattr(ev, "event_type", None) is not None
                        and getattr(ev, "event_type", None) not in NON_USER_EVENT_TYPES
                    )
                ]
                if user_events:
                    user_events.sort(key=lambda e: str(getattr(e, "created_at", "")))
                    content = getattr(user_events[0], "content", None)
                    if content and str(content).strip():
                        return str(content).strip()
        except Exception:
            pass

    for attr in ("prompt", "initial_prompt", "user_prompt", "input"):
        val = getattr(task, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()

    desc = getattr(task, "description", None)
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    return ""


async def get_task_info(task_obj: Any, task_id: str | None = None) -> TaskInfo | None:
    t_id = task_id or extract_task_id(task_obj)
    if not t_id:
        return None

    raw_status = getattr(task_obj, "status", "")
    status_str = extract_status_str(raw_status)
    pct = getattr(task_obj, "percent_complete", None)
    created_at = str(getattr(task_obj, "created_at", "N/A"))

    end_msg = getattr(task_obj, "output_summary", None)
    prompt = await extract_prompt_from_task(task_obj)

    if not prompt or (status_str in TERMINAL_STATUSES and not end_msg):
        try:
            full_task = await AgentTask.from_id(t_id)
            if not prompt:
                prompt = await extract_prompt_from_task(full_task)
            end_msg = end_msg or getattr(full_task, "output_summary", None)
        except Exception:
            pass

    return TaskInfo(
        task_id=t_id,
        status=status_str,
        raw_status=raw_status,
        percent=pct,
        created_at=created_at,
        prompt=prompt,
        end_msg=end_msg,
        is_terminal=(status_str in TERMINAL_STATUSES),
        task_obj=task_obj,
    )


async def fetch_tasks_info(raw_tasks: list, on_progress: Callable[[int, int], None] | None = None) -> list[TaskInfo]:
    sem = asyncio.Semaphore(5)
    total = len(raw_tasks)
    done = 0

    async def _load(t):
        nonlocal done
        async with sem:
            info = await get_task_info(t)
        done += 1
        if on_progress:
            on_progress(done, total)
        return info

    results = await asyncio.gather(*(_load(t) for t in raw_tasks))
    return [r for r in results if r is not None]


async def submit_prompt_to_project(project: Project, project_id: str, prompt: str) -> str | None:
    """Submits a prompt to an existing Aristotle project using project.ask."""
    try:
        task = await project.ask(prompt=prompt, mode=FollowUpMode.INSTRUCT)
        task_id = extract_task_id(task) or getattr(task, "object_id", "new")
        return str(task_id)
    except Exception as e:
        err_console.print(f"[red]❌ Failed to submit prompt to Aristotle project {project_id}: {e}[/red]")
        return None


async def stream_task_events(
    endpoint_prefix: str,
    task_id: str,
    api_key: str,
    max_retries: int = 5,
) -> AsyncIterator[dict[str, Any]]:
    """Connects to Aristotle's SSE stream using AristotleRequestClient."""
    from aristotlelib import api_request

    ep = endpoint_prefix.strip("/") or "task"
    path = f"/{ep}/{task_id}/events-stream"

    retry = 0
    while retry < max_retries:
        try:
            # AristotleRequestClient handles auth headers, timeout, and SSE line decoding
            async with api_request.AristotleRequestClient() as client:
                async for event_data in client.stream_sse(path):
                    if isinstance(event_data, dict):
                        yield event_data
                    elif isinstance(event_data, str):
                        try:
                            yield json.loads(event_data)
                        except Exception:
                            pass
                    retry = 0
            # If server closes cleanly, wait a moment and try reconnecting if still called
            await asyncio.sleep(2)
            retry += 1
        except asyncio.CancelledError:
            break
        except Exception:
            retry += 1
            await asyncio.sleep(min(2 ** retry, 10))


def execute_pull(project_id: str, api_key: str, paths: list[str] | None = None, cwd: Path | None = None) -> bool:
    sync_paths = paths or []
    target_cwd = (cwd or Path.cwd()).resolve()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "archive.tar.gz"
        extracted_path = tmp_path / "extracted"
        extracted_path.mkdir(parents=True, exist_ok=True)

        cmd = ["aristotle", "download", project_id, "--destination", str(archive_path)]
        if not shutil.which("aristotle"):
            cmd = ["uv", "run", "--with", "aristotlelib", "aristotle", "download", project_id, "--destination", str(archive_path)]

        env = dict(os.environ, ARISTOTLE_API_KEY=api_key)
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            err_console.print(f"[red]Download failed:\n{res.stderr or res.stdout}[/red]")
            return False

        subprocess.run(["tar", "-xzf", str(archive_path), "-C", str(extracted_path)], check=True)

        root_path = extracted_path
        all_entries = [p for p in extracted_path.iterdir() if not p.name.startswith(".")]
        if len(all_entries) == 1 and all_entries[0].is_dir():
            root_path = all_entries[0]

        subdirs = [d for d in root_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if sync_paths:
            first_clean = sync_paths[0].strip("/")
            if not (root_path / first_clean).exists():
                for s in subdirs:
                    if (s / first_clean).exists():
                        root_path = s
                        break

        excludes = collect_rsync_excludes_for_git(target_cwd)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as ef:
            ef.write("\n".join(excludes))
            exclude_file = Path(ef.name)

        try:
            if not sync_paths:
                rsync_cmd = ["rsync", "-av", "--delete", f"--exclude-from={exclude_file}", f"{root_path}/", f"{target_cwd}/"]
                subprocess.run(rsync_cmd, check=True)
            else:
                for p_str in sync_paths:
                    clean_p = p_str.strip("/")
                    src, dst = root_path / clean_p, target_cwd / clean_p
                    if not src.exists():
                        continue
                    if src.is_dir():
                        dst.mkdir(parents=True, exist_ok=True)
                        subprocess.run(["rsync", "-av", "--delete", f"--exclude-from={exclude_file}", f"{src}/", f"{dst}/"], check=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        subprocess.run(["rsync", "-av", str(src), str(dst)], check=True)
        finally:
            exclude_file.unlink(missing_ok=True)

    return True
