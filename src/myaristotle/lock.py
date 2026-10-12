import fcntl
import os
from pathlib import Path


class WatcherLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._file = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.lock_path, "a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._file.seek(0)
            self._file.truncate()
            self._file.write(f"{os.getpid()}\n")
            self._file.flush()
            return True
        except (BlockingIOError, OSError):
            return False

    def get_holder_pid(self) -> str | None:
        try:
            if self.lock_path.exists():
                return self.lock_path.read_text(encoding="utf-8").strip() or None
        except Exception:
            pass
        return None

    def release(self):
        if self._file:
            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
            except Exception:
                pass
            self._file = None
