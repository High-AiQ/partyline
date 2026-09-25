"""Bounded TERM-to-KILL cleanup for one adapter process group."""

import asyncio
import os
import signal
import subprocess

STOP_TERM_GRACE = 0.5
STOP_KILL_GRACE = 1.0


async def stop_process_group(proc: subprocess.Popen) -> None:
    """Stop the full session, reaping its leader while checking its children."""
    pgid = proc.pid

    def group_alive() -> bool:
        # poll() reaps an exited group leader, so killpg(..., 0) does not
        # mistake its zombie for a surviving CLI child.
        proc.poll()
        return process_group_alive(pgid)

    _signal_group(pgid, signal.SIGTERM, "cannot signal attachment process group")
    if await _wait_for_group_exit(proc, pgid, STOP_TERM_GRACE):
        return
    _signal_group(pgid, signal.SIGKILL, "cannot kill attachment process group")
    if not await _wait_for_group_exit(proc, pgid, STOP_KILL_GRACE):
        raise TimeoutError("attachment process group survived SIGKILL")


async def _wait_for_group_exit(proc: subprocess.Popen, pgid: int, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        proc.poll()
        if not process_group_alive(pgid):
            return True
        await asyncio.sleep(0.05)
    proc.poll()
    return not process_group_alive(pgid)


def _signal_group(pgid: int, sig: signal.Signals, error: str) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise RuntimeError(error) from exc


def process_group_alive(pgid: int) -> bool:
    """Whether a process group still exists, including permission-hidden groups."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
