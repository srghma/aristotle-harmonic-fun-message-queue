from collections.abc import Callable
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from rich.console import Console

from .git_ops import collect_rsync_excludes_for_git

err_console = Console(stderr=True)


def run_rsync_with_progress(cmd: list[str], on_progress: Callable[[str], None] | None = None) -> subprocess.CompletedProcess:
    """Runs rsync command and streams progress updates if on_progress callback is provided."""
    if not on_progress:
        return subprocess.run(cmd, check=True)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    buf = b""
    last_update_time = 0.0

    while True:
        chunk = proc.stdout.read(128) if proc.stdout else b""
        if not chunk:
            break
        buf += chunk
        while b"\r" in buf or b"\n" in buf:
            delim_idx = min([i for i in [buf.find(b"\r"), buf.find(b"\n")] if i != -1])
            raw_line = buf[:delim_idx].decode(errors="replace").strip()
            buf = buf[delim_idx + 1:]
            if not raw_line:
                continue

            # Detect rsync progress2 pattern: e.g. "1,234,567 45% 12.34MB/s 0:00:02 (xfr#3, to-chk=12/45)"
            now = time.monotonic()
            if re.search(r"(\d+%|to-chk=\d+/\d+)", raw_line):
                if now - last_update_time >= 0.15:
                    last_update_time = now
                    on_progress(raw_line)

    proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd)
    return subprocess.CompletedProcess(cmd, proc.returncode)


def execute_pull(
    project_id: str,
    api_key: str,
    paths: list[str] | None = None,
    cwd: Path | None = None,
    excludes: list[str] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> bool:
    sync_paths = paths or []
    target_cwd = (cwd or Path.cwd()).resolve()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "archive.tar.gz"
        extracted_path = tmp_path / "extracted"
        extracted_path.mkdir(parents=True, exist_ok=True)

        cmd = (
            ["aristotle", "download", project_id, "--destination", str(archive_path)]
            if shutil.which("aristotle")
            else ["uv", "run", "--with", "aristotlelib", "aristotle", "download", project_id, "--destination", str(archive_path)]
        )

        env = dict(os.environ, ARISTOTLE_API_KEY=api_key)
        res = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if res.returncode != 0:
            err_console.print(f"[red]Download failed:\n{res.stderr or res.stdout}[/red]")
            return False

        subprocess.run(["tar", "-xzf", str(archive_path), "-C", str(extracted_path)], check=True)

        root_path = (lambda entries: entries[0] if (len(entries) == 1 and entries[0].is_dir()) else extracted_path)(
            [p for p in extracted_path.iterdir() if not p.name.startswith(".")]
        )

        subdirs = [d for d in root_path.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if sync_paths:
            first_clean = sync_paths[0].strip("/")
            if not (root_path / first_clean).exists():
                for s in subdirs:
                    if (s / first_clean).exists():
                        root_path = s
                        break

        all_excludes = collect_rsync_excludes_for_git(target_cwd, extra_excludes=excludes)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as ef:
            ef.write("\n".join(all_excludes))
            exclude_file = Path(ef.name)

        try:
            if not sync_paths:
                run_rsync_with_progress(
                    ["rsync", "-av", "--delete", "--info=progress2", f"--exclude-from={exclude_file}", f"{root_path}/", f"{target_cwd}/"],
                    on_progress=on_progress,
                )
            else:
                for p_str in sync_paths:
                    clean_p = p_str.strip("/")
                    src, dst = root_path / clean_p, target_cwd / clean_p
                    if not src.exists():
                        continue
                    if src.is_dir():
                        dst.mkdir(parents=True, exist_ok=True)
                        run_rsync_with_progress(
                            ["rsync", "-av", "--delete", "--info=progress2", f"--exclude-from={exclude_file}", f"{src}/", f"{dst}/"],
                            on_progress=on_progress,
                        )
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        run_rsync_with_progress(
                            ["rsync", "-av", f"--exclude-from={exclude_file}", str(src), str(dst)],
                            on_progress=on_progress,
                        )
        except Exception as e:
            err_console.print(f"[red]Rsync failed: {e}[/red]")
            return False
        finally:
            exclude_file.unlink(missing_ok=True)

    return True
