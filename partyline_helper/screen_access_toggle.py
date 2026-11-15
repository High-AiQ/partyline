"""Persist tray permission changes before mirroring them to the server."""
import asyncio
import contextlib

from .screen_access import set_enabled


async def set_window_access(session, enabled):
    session.window_access_enabled = set_enabled(enabled)
    session.status.window_access_enabled = session.window_access_enabled
    if not session.window_access_enabled:
        session.windows.revoke_standing()
    session.status.changed()
    await session.send("window_access_changed", enabled=session.window_access_enabled)


async def pause_windows(session):
    session.window_access_enabled = set_enabled(False)
    session.status.window_access_enabled = False
    session.status.changed()
    session.disconnect_requested = True
    with contextlib.suppress(Exception):
        await session.stop("access paused")
    session.window.revoke("access paused")
    session.windows.revoke_all()
    for close in (session.window_task.close(), session.windows.close(), session.tools.end("access paused")):
        with contextlib.suppress(Exception):
            await close
    with contextlib.suppress(Exception):
        await session.send("window_access_changed", enabled=False)
    with contextlib.suppress(Exception):
        await session.socket.close(code=1000, reason="window access paused")


def request_window_access(session, enabled, loop):
    session.window_access_enabled = set_enabled(enabled)
    session.status.window_access_enabled = session.window_access_enabled
    session.status.changed()
    return asyncio.run_coroutine_threadsafe(session.set_window_access(enabled), loop)


def request_pause_windows(session, loop):
    session.window_access_enabled = set_enabled(False)
    session.status.window_access_enabled = False
    session.status.changed()
    return asyncio.run_coroutine_threadsafe(session.pause_windows(), loop)
