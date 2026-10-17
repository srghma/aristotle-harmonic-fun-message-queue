"""Backlog archive and deduplication management."""

import os
from pathlib import Path
import re


def deduplicate_messages(messages: list[str], consecutive_only: bool = True) -> list[str]:
    """Deduplicates a list of messages.

    - consecutive_only=True: removes consecutive duplicate messages (preserves non-consecutive history).
    - consecutive_only=False: keeps only first appearance of each unique message.
    """
    if not messages:
        return []

    if consecutive_only:
        result = []
        for msg in messages:
            clean = msg.strip()
            if not result or result[-1].strip() != clean:
                result.append(msg)
        return result

    seen = set()
    result = []
    for msg in messages:
        clean = msg.strip()
        if clean not in seen:
            seen.add(clean)
            result.append(msg)
    return result


def get_backlog_file_path(target: str | Path, backlog_dir: Path) -> Path:
    from .queue_manager import spec_to_queue_filename

    backlog_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(target, Path):
        return backlog_dir / target.name
    target_str = str(target).strip()
    if target_str.endswith(".md"):
        return backlog_dir / target_str
    return backlog_dir / spec_to_queue_filename(target_str)


def archive_to_backlog(
    target: str | Path,
    message: str,
    backlog_dir: Path,
    consecutive_only: bool = True,
) -> bool:
    """Archives message to the top of backlog if it differs from the previous (top) message.

    Also cleans any existing consecutive duplicates in the backlog file.
    Returns True if the message was added, False if skipped as duplicate.
    """
    from .queue_manager import read_queue, write_queue

    clean_msg = message.strip()
    if not clean_msg:
        return False

    b_file = get_backlog_file_path(target, backlog_dir)
    existing_backlog = read_queue(b_file)

    # Unduplicate existing backlog items first
    cleaned_existing = deduplicate_messages(existing_backlog, consecutive_only=consecutive_only)

    # If the new message is identical to the latest backlog entry (index 0), do not add
    if cleaned_existing and cleaned_existing[0].strip() == clean_msg:
        # Save cleaned existing if duplicates were removed from the file
        if len(cleaned_existing) != len(existing_backlog):
            write_queue(b_file, None, cleaned_existing)
        return False

    write_queue(b_file, None, [message] + cleaned_existing)
    return True


def deduplicate_backlog_file(b_file: Path, consecutive_only: bool = True) -> int:
    """Cleans duplicate messages from a backlog file. Returns number of removed duplicates."""
    from .queue_manager import read_queue, write_queue

    if not b_file.is_file():
        return 0

    msgs = read_queue(b_file)
    deduped = deduplicate_messages(msgs, consecutive_only=consecutive_only)
    removed = len(msgs) - len(deduped)
    if removed > 0:
        write_queue(b_file, None, deduped)
    return removed


def deduplicate_all_backlogs(backlog_dir: Path, consecutive_only: bool = True) -> dict[str, int]:
    """Scans backlog_dir and strips duplicates from all .md backlog files."""
    stats = {}
    if not backlog_dir.is_dir():
        return stats

    for b_file in backlog_dir.glob("*.md"):
        removed = deduplicate_backlog_file(b_file, consecutive_only=consecutive_only)
        if removed > 0:
            stats[b_file.name] = removed

    return stats
