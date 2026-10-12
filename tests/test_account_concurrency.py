from myaristotle.config import ProjectConfig
from myaristotle.tui import ProjectState
from myaristotle.watcher import is_account_busy


def test_is_account_busy():
    cfg1 = ProjectConfig(id="11111111-1111-1111-1111-111111111111", account="lyubovkot")
    cfg2 = ProjectConfig(id="22222222-2222-2222-2222-222222222222", account="lyubovkot")
    cfg3 = ProjectConfig(id="33333333-3333-3333-3333-333333333333", account="sochor896")

    p1 = ProjectState(spec="proj1:main", repo_name="proj1", branch="main", cfg=cfg1, is_busy=True)
    p2 = ProjectState(spec="proj2:main", repo_name="proj2", branch="main", cfg=cfg2, is_busy=False)
    p3 = ProjectState(spec="proj3:main", repo_name="proj3", branch="main", cfg=cfg3, is_busy=False)

    projects = [p1, p2, p3]

    # p2 is under lyubovkot, and p1 is busy -> account is busy for p2
    assert is_account_busy("lyubovkot", projects, current_spec="proj2:main") is True

    # p1 is checking itself -> not blocked by itself
    assert is_account_busy("lyubovkot", projects, current_spec="proj1:main") is False

    # p3 is under sochor896 -> sochor896 is NOT busy
    assert is_account_busy("sochor896", projects, current_spec="proj3:main") is False

    # Once p1 finishes
    p1.is_busy = False
    assert is_account_busy("lyubovkot", projects, current_spec="proj2:main") is False
