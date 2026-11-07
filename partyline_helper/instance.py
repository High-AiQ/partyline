"""Single running helper per user: an OS file lock under the config dir (released if we die)."""
import contextlib
import os
import subprocess

from .config import config_path


def lock_dir():
    return config_path().parent


def _lock_posix(handle):
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _lock_windows(handle):  # pragma: no cover - Windows only
    import msvcrt
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)


def _unlock(handle):
    if os.name == "nt":  # pragma: no cover
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    # POSIX flock is released when the handle closes.


class InstanceLock:
    """Non-blocking exclusive lock. The holder's pid goes in a separate `.pid` file: on Windows the
    locked byte range cannot be read by anyone else, so the pid must not live in the lock file."""

    def __init__(self, name, directory=None, lock=None):
        self.path = (directory or lock_dir()) / f"{name}.lock"
        self.pid_path = self.path.with_suffix(".pid")
        self.lock = lock or (_lock_windows if os.name == "nt" else _lock_posix)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")  # noqa: SIM115 - held for the lifetime of the process
        try:
            self.lock(handle)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        self.pid_path.write_text(str(os.getpid()))
        return True

    def release(self):
        if self.handle:
            # Drop the pid while we still own the lock; afterwards a new owner may be writing its own.
            self.pid_path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                _unlock(self.handle)
            self.handle.close()
            self.handle = None

    def holder(self):
        """The pid of a live holder, or None when nobody holds the lock (or it is still starting)."""
        probe = InstanceLock(self.path.stem, self.path.parent, self.lock)
        if probe.acquire():
            probe.release()
            return None
        with contextlib.suppress(OSError, ValueError):
            return int(self.pid_path.read_text().strip())
        return None

    def __enter__(self):
        return self if self.acquire() else None

    def __exit__(self, *exc):
        self.release()


def spawn_detached(command, popen=subprocess.Popen):
    """Start `command` (an argv list, never a shell string) so it survives this process."""
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":  # pragma: no cover - Windows flags
        options["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED|NEW_GROUP|NO_WINDOW
    else:
        options["start_new_session"] = True
    return popen(command, **options)
