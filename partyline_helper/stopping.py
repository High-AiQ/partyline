"""`partyline-helper stop`: ask the running helper to exit, and end it if it does not listen.

The helper polls for a stop file and shuts down through its normal path (the share is ended, the border
removed, the tray icon taken away). An older helper that predates this does not poll, so after a short wait
the stop falls back to terminating the pid it recorded under the run lock.
"""
import asyncio
import os
import signal
import time

from .instance import InstanceLock, lock_dir

POLL = 0.2
WAITS = 25  # polls of POLL seconds per phase: about five seconds politely, then five more after a kill


def stop_path():
    return lock_dir() / "run.stop"


def clear_stop(path=None):
    (path or stop_path()).unlink(missing_ok=True)


async def watch_stop(cancel, path=None, sleep=asyncio.sleep, interval=0.5):
    """Call `cancel` once a stop file appears (and remove it)."""
    path = path or stop_path()
    while True:
        if path.exists():
            clear_stop(path)
            cancel()
            return
        await sleep(interval)


def stop_helper(lock=InstanceLock, kill=os.kill, sleep=time.sleep, path=None):
    """Returns (stopped, message). Safe to call when nothing runs."""
    path = path or stop_path()
    holder = lock("run").holder()
    if holder is None:
        clear_stop(path)
        return True, "The helper is not running."

    def gone():
        for _ in range(WAITS):
            if lock("run").holder() is None:
                return True
            sleep(POLL)
        return lock("run").holder() is None

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
