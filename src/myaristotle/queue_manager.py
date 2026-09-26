import os
from pathlib import Path
import re


def spec_to_queue_filename(spec: str) -> str:
    """Encodes '~/projects/leanscript:main' into '~|projects|leanscript:main.md'."""
    safe_name = spec.strip().replace("/", "|")
    return f"{safe_name}.md"


def queue_filename_to_spec(filename: str) -> str:
    """Decodes '~|projects|leanscript:main.md' into '~/projects/leanscript:main'."""
    stem = filename.removesuffix(".md")
    return stem.replace("|", "/")


def get_queue_file_path(spec: str, queue_dir: Path) -> Path:
    return queue_dir / spec_to_queue_filename(spec)


def parse_queue_messages(content: str) -> list[str]:
    """Splits markdown queue content on lines containing three or more '='."""
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


def read_queue(spec: str, queue_dir: Path) -> list[str]:
    q_file = get_queue_file_path(spec, queue_dir)
    if not q_file.is_file():
        return []
    try:
        content = q_file.read_text(encoding="utf-8")
        return parse_queue_messages(content)
    except Exception:
        return []


def write_queue(spec: str, queue_dir: Path, messages: list[str]) -> None:
    queue_dir.mkdir(parents=True, exist_ok=True)
    q_file = get_queue_file_path(spec, queue_dir)
    content = format_queue_messages(messages)
    tmp_file = q_file.with_suffix(f".tmp.{os.getpid()}")
    tmp_file.write_text(content, encoding="utf-8")
    tmp_file.replace(q_file)


def archive_to_backlog(spec: str, message: str, backlog_dir: Path) -> None:
    """Prepends a popped message to the top of the corresponding backlog queue file."""
    existing_backlog = read_queue(spec, backlog_dir)
    # Prepend to the top of the file
    write_queue(spec, backlog_dir, [message] + existing_backlog)


def peek_next_message(spec: str, queue_dir: Path) -> str | None:
    """Reads the top message from the queue WITHOUT removing it from disk."""
    messages = read_queue(spec, queue_dir)
    return messages[0] if messages else None


def pop_top_message(spec: str, queue_dir: Path, backlog_dir: Path | None = None) -> str | None:
    """Removes the top message from disk and prepends it to backlog_dir if provided."""
    messages = read_queue(spec, queue_dir)
    if not messages:
        return None

    top_message = messages[0]
    remaining = messages[1:]
    write_queue(spec, queue_dir, remaining)

    if backlog_dir:
        archive_to_backlog(spec, top_message, backlog_dir)

    return top_message


def pop_next_message(
    spec: str,
    queue_dir: Path,
    loop_first: bool = False,
    backlog_dir: Path | None = None,
) -> str | None:
    """Backward-compatible helper."""
    if loop_first:
        return peek_next_message(spec, queue_dir)
    return pop_top_message(spec, queue_dir, backlog_dir=backlog_dir)
