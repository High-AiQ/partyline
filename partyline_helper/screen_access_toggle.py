"""Persist tray permission changes before mirroring them to the server."""
import asyncio

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
    session.control.end("access paused")
    session.accepted = False
    session.last_uia_frame = None
    session.window.revoke("access paused")
    session.windows.revoke_all()
    session.window_task.cancel()
    if session.worker:
        session.worker.cancel()
    # Disconnect does not queue behind capture cancellation, a writer lock, or CDP teardown.
    await asyncio.gather(
        session.stop("access paused"), session.window_task.close(), session.windows.close(),
        session.tools.end("access paused"), session.send("window_access_changed", enabled=False),
        session.socket.close(code=1000, reason="window access paused"), return_exceptions=True)


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
