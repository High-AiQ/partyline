"""`partyline-helper stop`: ask the running helper to exit, and end it if it does not listen.

The helper watches native filesystem notifications for a stop file and shuts down normally
(the share is ended, the border removed, the tray icon taken away). An older helper may not watch;
after a short wait
the stop falls back to terminating the pid it recorded under the run lock.
"""
import os
import signal

from .instance import InstanceLock, lock_dir
from partyline.file_events import FileEvents
from partyline.process_events import wait_pid

def stop_path():
    return lock_dir() / "run.stop"


def clear_stop(path=None):
    (path or stop_path()).unlink(missing_ok=True)


async def watch_stop(cancel, path=None):
    """Call `cancel` once a stop file appears (and remove it)."""
    path = path or stop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with FileEvents(path) as events:
        while not path.exists():
            await events.wait()
        clear_stop(path)
        cancel()


def stop_helper(lock=InstanceLock, kill=os.kill, path=None):
    """Returns (stopped, message). Safe to call when nothing runs."""
    path = path or stop_path()
    holder = lock("run").holder()
    if holder is None:
        clear_stop(path)
        return True, "The helper is not running."

    def gone():
        return wait_pid(holder, timeout=5)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop")
    if gone():
        return True, f"Stopped the helper (pid {holder})."
    try:
        kill(holder, signal.SIGTERM)
    except OSError:
        pass
    clear_stop(path)
    if gone():
        return True, f"Stopped the helper (pid {holder}) by ending the process."
    return False, f"The helper (pid {holder}) did not stop; end Partyline Helper in Task Manager."
