import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from rich.console import Console

from .git_ops import collect_rsync_excludes_for_git

err_console = Console(stderr=True)


def execute_pull(project_id: str, api_key: str, paths: list[str] | None = None, cwd: Path | None = None) -> bool:
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

        excludes = collect_rsync_excludes_for_git(target_cwd)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as ef:
            ef.write("\n".join(excludes))
            exclude_file = Path(ef.name)

        try:
            if not sync_paths:
                subprocess.run(["rsync", "-av", "--delete", f"--exclude-from={exclude_file}", f"{root_path}/", f"{target_cwd}/"], check=True)
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
