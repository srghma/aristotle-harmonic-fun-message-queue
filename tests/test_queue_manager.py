from myaristotle.queue_manager import (
    archive_to_backlog,
    deduplicate_all_backlogs,
    deduplicate_messages,
    format_queue_messages,
    parse_queue_messages,
    pop_next_message,
    pop_top_message,
    read_queue,
    spec_to_queue_filename,
    write_queue,
)


def test_spec_to_filename():
    assert spec_to_queue_filename("leanscript:main") == "leanscript:main.md"
    assert spec_to_queue_filename("~/projects/leanscript:main") == "leanscript:main.md"
    assert spec_to_queue_filename("clean") == "clean.md"
    assert spec_to_queue_filename("SciLean:main") == "SciLean:main.md"


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
    spec = "test:main"
    msgs = ["Prompt 1", "Prompt 2", "Prompt 3"]
    write_queue(spec, tmp_path, msgs)

    popped = pop_next_message(spec, tmp_path, loop_first=False)
    assert popped == "Prompt 1"

    remaining = read_queue(spec, tmp_path)
    assert remaining == ["Prompt 2", "Prompt 3"]


def test_loop_first_message(tmp_path):
    spec = "scilean:main"
    msgs = ["Persistent prompt", "Next prompt"]
    write_queue(spec, tmp_path, msgs)

    popped = pop_next_message(spec, tmp_path, loop_first=True)
    assert popped == "Persistent prompt"

    remaining = read_queue(spec, tmp_path)
    assert remaining == ["Persistent prompt", "Next prompt"]


def test_pop_and_archive_to_backlog(tmp_path):
    queue_dir = tmp_path / "queue"
    backlog_dir = tmp_path / "queue_backlog"
    spec = "leanscript:main"

    write_queue(spec, queue_dir, ["Task A", "Task B", "Task C"])

    popped1 = pop_top_message(spec, queue_dir, backlog_dir=backlog_dir)
    assert popped1 == "Task A"
    assert read_queue(spec, queue_dir) == ["Task B", "Task C"]
    assert read_queue(spec, backlog_dir) == ["Task A"]

    popped2 = pop_top_message(spec, queue_dir, backlog_dir=backlog_dir)
    assert popped2 == "Task B"
    assert read_queue(spec, queue_dir) == ["Task C"]
    assert read_queue(spec, backlog_dir) == ["Task B", "Task A"]


def test_archive_skips_when_same_as_prev(tmp_path):
    backlog_dir = tmp_path / "queue_backlog"
    spec = "leanscript:main"

    # 1. Add Task 1
    added1 = archive_to_backlog(spec, "Task 1", backlog_dir)
    assert added1 is True
    assert read_queue(spec, backlog_dir) == ["Task 1"]

    # 2. Add Task 1 again -> should NOT be added
    added2 = archive_to_backlog(spec, "Task 1", backlog_dir)
    assert added2 is False
    assert read_queue(spec, backlog_dir) == ["Task 1"]

    # 3. Add Task 2 -> added to top
    added3 = archive_to_backlog(spec, "Task 2", backlog_dir)
    assert added3 is True
    assert read_queue(spec, backlog_dir) == ["Task 2", "Task 1"]

    # 4. Add Task 2 again -> skipped
    added4 = archive_to_backlog(spec, "Task 2", backlog_dir)
    assert added4 is False
    assert read_queue(spec, backlog_dir) == ["Task 2", "Task 1"]


def test_archive_cleans_existing_duplicates(tmp_path):
    backlog_dir = tmp_path / "queue_backlog"
    spec = "repo:main"

    # Pre-populate backlog file with existing consecutive duplicates
    b_file = backlog_dir / "repo:main.md"
    write_queue(b_file, None, ["Old Task", "Old Task", "Older Task", "Older Task"])

    # Archiving a new task cleans existing duplicates and prepends new task
    archive_to_backlog(spec, "New Task", backlog_dir)
    assert read_queue(spec, backlog_dir) == ["New Task", "Old Task", "Older Task"]


def test_deduplicate_all_backlogs(tmp_path):
    backlog_dir = tmp_path / "queue_backlog"
    backlog_dir.mkdir(parents=True)

    f1 = backlog_dir / "repo1.md"
    f2 = backlog_dir / "repo2.md"
    write_queue(f1, None, ["A", "A", "B", "B"])
    write_queue(f2, None, ["X", "Y", "Z"])

    stats = deduplicate_all_backlogs(backlog_dir)
    assert stats == {"repo1.md": 2}
    assert read_queue(f1) == ["A", "B"]
    assert read_queue(f2) == ["X", "Y", "Z"]
