from myaristotle.config import ProjectConfig
from myaristotle.state import ProjectState, UIState
from myaristotle.watcher import check_hibernate_condition, project_matches_hibernate_target
from pathlib import Path


def create_state(spec: str, repo_name: str, branch: str, **kwargs):
    cfg = ProjectConfig(id="11111111-1111-1111-1111-111111111111", account="acc")
    p = ProjectState(
        spec=spec,
        repo_name=repo_name,
        branch=branch,
        cfg=cfg,
        status=kwargs.get("status", "COMPLETE"),
        queue_count=kwargs.get("queue_count", 0),
        is_busy=kwargs.get("is_busy", False),
        is_syncing=kwargs.get("is_syncing", False),
        has_initialized=kwargs.get("has_initialized", True),
    )
    return p


def test_project_matches_target():
    p = create_state("myrepo:feat", "myrepo", "feat")
    assert project_matches_hibernate_target(p, "myrepo:feat") is True
    assert project_matches_hibernate_target(p, "myrepo") is True
    assert project_matches_hibernate_target(p, "other") is False


def test_hibernate_condition_empty_targets():
    p = create_state("repo1", "repo1", "main")
    assert check_hibernate_condition([], [p]) is False


def test_hibernate_condition_all_exhausted():
    p1 = create_state("repo1", "repo1", "main")
    p2 = create_state("repo2", "repo2", "main")
    assert check_hibernate_condition(["repo1", "repo2"], [p1, p2]) is True


def test_hibernate_condition_only_target_exhausted():
    # p1 is target and exhausted, p2 is not target and is busy
    p1 = create_state("repo1", "repo1", "main", queue_count=0, is_busy=False)
    p2 = create_state("repo2", "repo2", "main", queue_count=5, is_busy=True)
    assert check_hibernate_condition(["repo1"], [p1, p2]) is True


def test_hibernate_condition_target_busy_or_queue_pending():
    p1 = create_state("repo1", "repo1", "main", queue_count=1)
    assert check_hibernate_condition(["repo1"], [p1]) is False

    p2 = create_state("repo1", "repo1", "main", queue_count=0, is_busy=True)
    assert check_hibernate_condition(["repo1"], [p2]) is False

    p3 = create_state("repo1", "repo1", "main", queue_count=0, is_syncing=True)
    assert check_hibernate_condition(["repo1"], [p3]) is False

    p4 = create_state("repo1", "repo1", "main", queue_count=0, has_initialized=False)
    assert check_hibernate_condition(["repo1"], [p4]) is False


def test_hibernate_condition_out_of_budget_auto_continue():
    p = create_state("repo1", "repo1", "main", status="OUT_OF_BUDGET", queue_count=0, is_busy=False)
    p.cfg.auto_continue_on_out_of_budget = True
    assert check_hibernate_condition(["repo1"], [p]) is False

    p.cfg.auto_continue_on_out_of_budget = False
    assert check_hibernate_condition(["repo1"], [p]) is True
