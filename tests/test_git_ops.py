from myaristotle.git_ops import build_git_commit_message, extract_first_line_prompt


def test_extract_first_line_prompt():
    prompt = """
# Task: Refactor loop

Please fix the while loop issue.
"""
    assert extract_first_line_prompt(prompt) == "Task: Refactor loop"


def test_build_git_commit_message():
    msg = build_git_commit_message(
        task_id="6ad53d96-a66b-4f9b-9787-563ecc92c6fa",
        status="COMPLETE",
        prompt="Fix sorry proofs in Mathlib",
        end_msg="All sorries were discharged successfully.",
    )
    assert "Aristotle: 6ad53d96 (COMPLETE) - Fix sorry proofs in Mathlib" in msg
    assert "Task ID: 6ad53d96-a66b-4f9b-9787-563ecc92c6fa" in msg
    assert "=== My Prompt ===" in msg
    assert "=== Aristotle End Message ===" in msg
