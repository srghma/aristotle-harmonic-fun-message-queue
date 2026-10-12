import os
from myaristotle.watcher import WatcherLock


def test_watcher_lock(tmp_path):
    lock_file = tmp_path / "watcher.lock"
    lock1 = WatcherLock(lock_file)
    lock2 = WatcherLock(lock_file)

    assert lock1.acquire() is True
    assert lock1.get_holder_pid() == str(os.getpid())

    # Second acquisition on the same file while lock1 is held must fail
    assert lock2.acquire() is False
    assert lock2.get_holder_pid() == str(os.getpid())

    # After lock1 releases, lock2 can acquire
    lock1.release()
    assert lock2.acquire() is True
    lock2.release()
