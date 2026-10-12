from pathlib import Path
import re
import subprocess

from rich.console import Console

console = Console()
err_console = Console(stderr=True)


def get_git_branch(cwd: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        b = res.stdout.strip()
        if not b:
            res_ref = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=cwd,
            )
            b = res_ref.stdout.strip()
        return b or "main"
    except Exception:
        return "main"


def get_current_git_repo_and_branch(cwd: Path | None = None) -> tuple[Path | None, str | None]:
    target_cwd = (cwd or Path.cwd()).resolve()
    try:
        res_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=target_cwd,
        )
        if res_root.returncode != 0:
            return None, None
        repo_root = Path(res_root.stdout.strip()).resolve()
        branch = get_git_branch(repo_root)
        return repo_root, branch
    except Exception:
        return None, None


def git_checkout(branch: str, cwd: Path) -> bool:
    curr = get_git_branch(cwd)
    if curr == branch:
        return True

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=cwd,
    ).stdout.strip()
    if status:
        err_console.print(
            f"[red]⚠️ Cannot switch to '{branch}' in {cwd}: uncommitted changes.[/red]\n"
            f"[dim]{status}[/dim]"
        )
        return False

    res = subprocess.run(["git", "checkout", branch], capture_output=True, text=True, cwd=cwd)
    return res.returncode == 0


def git_commit_changes(commit_msg: str, push: bool = True, cwd: Path | None = None) -> bool:
    target_cwd = (cwd or Path.cwd()).resolve()
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=target_cwd).stdout.strip()
    if not status:
        console.print(f"[dim][{target_cwd.name}] No git working tree changes detected.[/dim]")
        return False

    console.print(f"[bold green]📝 [{target_cwd.name}] Changes detected. Committing...[/bold green]")
    subprocess.run(["git", "add", "."], check=True, cwd=target_cwd)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True, cwd=target_cwd)

    if push:
        console.print(f"[bold blue]🚀 [{target_cwd.name}] Pushing to remote...[/bold blue]")
        try:
            subprocess.run(["git", "push"], check=True, cwd=target_cwd)
        except subprocess.CalledProcessError as e:
            err_console.print(f"[red]⚠️ Git push failed in {target_cwd}: {e}[/red]")
            return False
    return True


def is_task_in_git(task_id: str, branch: str | None = None, cwd: Path | None = None) -> bool:
    target_cwd = (cwd or Path.cwd()).resolve()
    try:
        cmd = ["git", "log"]
        if branch:
            cmd.append(branch)
        cmd.extend(["-n", "50", f"--grep=Task ID: {task_id}"])
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=target_cwd)
        return res.returncode == 0 and bool(res.stdout.strip())
    except Exception:
        return False


def collect_rsync_excludes_for_git(cwd: Path) -> list[str]:
    excludes = ["/.git/", "/.git", "/.gitignore", "/.gitattributes", "/.gitmodules"]
    root_gi = cwd / ".gitignore"
    if root_gi.is_file():
        try:
            for line in root_gi.read_text(encoding="utf-8", errors="replace").splitlines():
                clean = line.strip()
                if clean and not clean.startswith(("#", "!")) and clean not in excludes:
                    excludes.append(clean)
        except Exception:
            pass
    return excludes


def extract_first_line_prompt(prompt: str | None, max_chars: int = 60) -> str:
    if not prompt or not prompt.strip():
        return ""
    for raw_line in prompt.strip().splitlines():
        line = re.sub(r"^([#\-*> ]+)", "", raw_line.strip())
        if re.match(r"^You wrote\b", line, re.IGNORECASE):
            continue
        if line:
            return (line[: max_chars - 3].rsplit(" ", 1)[0] + "...") if len(line) > max_chars else line
    return ""


def build_git_commit_message(task_id: str, status: str, prompt: str, end_msg: str | None = None) -> str:
    pr_clean = prompt.strip() if prompt else ""
    first_line = extract_first_line_prompt(pr_clean, max_chars=60)
    commit_title = f"Aristotle: {task_id[:8]} ({status})"
    if first_line:
        commit_title += f" - {first_line}"

    lines = [
        commit_title,
        "",
        f"Task ID: {task_id}",
        f"Status:  {status}",
        "",
        "=== My Prompt ===",
        pr_clean or "(No prompt recorded)",
    ]

    if end_msg:
        lines.extend([
            "",
            "=== Aristotle End Message ===",
            end_msg.strip(),
        ])

    return "\n".join(lines)


def format_continuation_prompt(prev_prompt: str) -> str:
    clean = prev_prompt.strip() if prev_prompt else ""
    clean = re.sub(
        r"^(continue\s+(with\s+)?previous\s+task\s*:\s*)+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    if clean:
        return f"continue previous task:\n{clean}"
    return "continue previous task:"
