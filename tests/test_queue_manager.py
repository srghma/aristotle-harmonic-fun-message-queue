from myaristotle.queue_manager import (
    format_queue_messages,
    parse_queue_messages,
    pop_next_message,
    pop_top_message,
    read_queue,
    spec_to_queue_filename,
    write_queue,
)


def test_spec_to_filename():
    assert spec_to_queue_filename("~/projects/leanscript:main") == "~|projects|leanscript:main.md"
    assert spec_to_queue_filename("~/projects/SciLean:main") == "~|projects|SciLean:main.md"


def test_parse_and_format_queue_messages():
    raw = """
First prompt here

===============

Second prompt with code:
```lean
def x := 1
```

===============

Third prompt
"""
    msgs = parse_queue_messages(raw)
    assert len(msgs) == 3
    assert msgs[0] == "First prompt here"
    assert "def x := 1" in msgs[1]
    assert msgs[2] == "Third prompt"

    formatted = format_queue_messages(msgs)
    assert "===============" in formatted
    assert parse_queue_messages(formatted) == msgs


def test_pop_top_message(tmp_path):
    spec = "~/projects/test:main"
    msgs = ["Prompt 1", "Prompt 2", "Prompt 3"]
    write_queue(spec, tmp_path, msgs)

    # Pop first
    popped = pop_next_message(spec, tmp_path, loop_first=False)
    assert popped == "Prompt 1"

    remaining = read_queue(spec, tmp_path)
    assert remaining == ["Prompt 2", "Prompt 3"]


def test_loop_first_message(tmp_path):
    spec = "~/projects/scilean:main"
    msgs = ["Persistent prompt", "Next prompt"]
    write_queue(spec, tmp_path, msgs)

    popped = pop_next_message(spec, tmp_path, loop_first=True)
    assert popped == "Persistent prompt"

    remaining = read_queue(spec, tmp_path)
    # File remains untouched
    assert remaining == ["Persistent prompt", "Next prompt"]


def test_pop_and_archive_to_backlog(tmp_path):
    queue_dir = tmp_path / "queue"
    backlog_dir = tmp_path / "queue_backlog"
    spec = "~/projects/leanscript:main"

    write_queue(spec, queue_dir, ["Task A", "Task B", "Task C"])

    # 1. Pop Task A -> goes to backlog
    popped1 = pop_top_message(spec, queue_dir, backlog_dir=backlog_dir)
    assert popped1 == "Task A"
    assert read_queue(spec, queue_dir) == ["Task B", "Task C"]
    assert read_queue(spec, backlog_dir) == ["Task A"]

    # 2. Pop Task B -> prepended to top of backlog (Task B before Task A)
    popped2 = pop_top_message(spec, queue_dir, backlog_dir=backlog_dir)
    assert popped2 == "Task B"
    assert read_queue(spec, queue_dir) == ["Task C"]
    assert read_queue(spec, backlog_dir) == ["Task B", "Task A"]
