import os
from pathlib import Path
import re


def spec_to_queue_filename(spec: str) -> str:
    """Simplifies spec into clean filename, stripping ~/projects/ and replacing / with |."""
    s = spec.strip()
    s = re.sub(r"^(~[|/]projects[|/]|projects[|/])", "", s)
    safe_name = s.replace("/", "|")
    return f"{safe_name}.md"


def queue_filename_to_spec(filename: str) -> str:
    stem = filename.removesuffix(".md")
    return stem.replace("|", "/")


def get_canonical_queue_path(
    repo_dir: Path,
    branch: str | None,
    queue_dir: Path,
    spec: str | None = None,
) -> Path:
    # If spec is provided, prefer its cleaned filename
    if spec:
        filename = spec_to_queue_filename(spec)
    elif branch and branch != "main":
        filename = f"{repo_dir.name}:{branch}.md"
    else:
        filename = f"{repo_dir.name}.md"
    return queue_dir / filename


def find_or_create_queue_file(
    repo_dir: Path,
    branch: str | None,
    queue_dir: Path,
    spec: str | None = None,
) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)

    # 1. Check exact simplified filename from spec
    if spec:
        spec_file = queue_dir / spec_to_queue_filename(spec)
        if spec_file.exists():
            return spec_file

    # 2. Check repo.md
    simple_file = queue_dir / f"{repo_dir.name}.md"
    if simple_file.exists():
        return simple_file

    # 3. Check repo:branch.md
    if branch:
        branch_file = queue_dir / f"{repo_dir.name}:{branch}.md"
        if branch_file.exists():
            return branch_file

    # 4. Check legacy ~|projects| patterns
    legacy_patterns = [
        f"~|projects|{repo_dir.name}.md",
        f"~|projects|{repo_dir.name}:{branch}.md" if branch else None,
    ]
    for lp in legacy_patterns:
        if lp and (queue_dir / lp).exists():
            return queue_dir / lp

    # Fallback: create simplified file
    canonical = get_canonical_queue_path(repo_dir, branch, queue_dir, spec=spec)
    canonical.touch()
    return canonical


def get_queue_file_path(target: str | Path, queue_dir: Path) -> Path:
    if isinstance(target, Path):
        return target if target.is_absolute() else (queue_dir / target)
    target_str = str(target).strip()
    if target_str.endswith(".md"):
        return queue_dir / target_str
    return queue_dir / spec_to_queue_filename(target_str)


def parse_queue_messages(content: str) -> list[str]:
    if not content or not content.strip():
        return []
    parts = re.split(r"(?m)^\s*={3,}\s*$", content)
    messages = []
    for p in parts:
        trimmed = p.strip()
        if trimmed:
            messages.append(trimmed)
    return messages


def format_queue_messages(messages: list[str]) -> str:
    if not messages:
        return ""
    return "\n\n===============\n\n".join(messages).strip() + "\n"


def read_queue(target: str | Path, queue_dir: Path | None = None) -> list[str]:
    q_file = target if isinstance(target, Path) else get_queue_file_path(target, queue_dir)
    if not q_file.is_file():
        return []
    try:
        content = q_file.read_text(encoding="utf-8")
        return parse_queue_messages(content)
    except Exception:
        return []


def write_queue(target: str | Path, queue_dir: Path | None, messages: list[str]) -> None:
    if isinstance(target, Path):
        q_file = target
    else:
        assert queue_dir is not None
        queue_dir.mkdir(parents=True, exist_ok=True)
        q_file = get_queue_file_path(target, queue_dir)

    q_file.parent.mkdir(parents=True, exist_ok=True)
    content = format_queue_messages(messages)
    tmp_file = q_file.with_suffix(f".tmp.{os.getpid()}")
    tmp_file.write_text(content, encoding="utf-8")
    tmp_file.replace(q_file)


def get_backlog_file_path(target: str | Path, backlog_dir: Path) -> Path:
    backlog_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(target, Path):
        return backlog_dir / target.name
    target_str = str(target).strip()
    if target_str.endswith(".md"):
        return backlog_dir / target_str
    return backlog_dir / spec_to_queue_filename(target_str)


def archive_to_backlog(target: str | Path, message: str, backlog_dir: Path) -> None:
    b_file = get_backlog_file_path(target, backlog_dir)
    existing_backlog = read_queue(b_file)
    write_queue(b_file, None, [message] + existing_backlog)


def peek_next_message(target: str | Path, queue_dir: Path | None = None) -> str | None:
    messages = read_queue(target, queue_dir)
    return messages[0] if messages else None


def pop_top_message(target: str | Path, queue_dir: Path | None = None, backlog_dir: Path | None = None) -> str | None:
    messages = read_queue(target, queue_dir)
    if not messages:
        return None

    top_message = messages[0]
    remaining = messages[1:]
    write_queue(target, queue_dir, remaining)

    if backlog_dir:
        archive_to_backlog(target, top_message, backlog_dir)

    return top_message


def pop_next_message(
    target: str | Path,
    queue_dir: Path | None = None,
    loop_first: bool = False,
    backlog_dir: Path | None = None,
) -> str | None:
    if loop_first:
        return peek_next_message(target, queue_dir)
    return pop_top_message(target, queue_dir, backlog_dir=backlog_dir)
