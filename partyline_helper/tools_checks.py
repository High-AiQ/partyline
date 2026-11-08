"""The render-check scope on this computer: the tray item that withdraws it and the flags the tray reads.

The scope belongs to the local grant. Withdrawing it needs no server: the grant is changed here first, so the
next image the helper returns is no longer marked `checkable`, and then the server is told (it only ever
accepts "off" from this message; getting the scope back needs a new dialog).
"""
import asyncio
import contextlib


def sync(tools):
    """Show the tray item only while the live session holds the scope."""
    status, grant = tools.session.status, tools.grant
    on = bool(grant and grant["checker"])
    loop = asyncio.get_running_loop()
    status.checks_active = on
    status.stop_checks = (lambda: loop.call_soon_threadsafe(lambda: tools.spawn(withdraw(tools, "tray")))) \
        if on else None
    status.changed()


async def withdraw(tools, source):
    grant = tools.grant
    if not grant or not grant["checker"]:
        return False
    grant["checker"] = False
    tools.log("event", "session", f"render checks withdrawn ({source})")
    sync(tools)
    with contextlib.suppress(Exception):
        print("RENDER CHECKS STOPPED: images from this session are no longer sent to OpenAI.", flush=True)
    await tools.send("tools_granted", session_id=grant["id"], checker=False)
    return True
