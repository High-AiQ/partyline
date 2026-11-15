"""Installer-only shutdown: release the host executable before replacing Windows files."""
import asyncio

from partyline.process_events import wait_pid
from .native_host import discover, running_pid
from .native_socket import NativeSocket


async def suspend(endpoint, opener=asyncio.open_connection):
    reader, writer = await opener("127.0.0.1", endpoint["port"])
    socket = NativeSocket(reader, writer)
    try:
        socket.send_nowait({"token": endpoint["token"]})
        # `release`: the installer needs this host's files, so Chrome's port must close.
        await socket.send('{"method":"Partyline.suspend","release":true}')
        # EOF confirms Chrome closed the native port; the PID wait confirms file handles are gone.
        async with asyncio.timeout(5):
            async for _ in socket:
                pass
    finally:
        await socket.close()


def pause_for_install(host=running_pid, wait=wait_pid, run=asyncio.run):
    holder = host()
    if holder is None:
        return "Chrome native host is not running."
    endpoint = discover()
    try:
        if endpoint:
            run(suspend(endpoint))
    except (OSError, ValueError, TimeoutError):
        pass
    try:
        stopped = wait(holder, timeout=5)
    except OSError:
        stopped = False
    if not stopped:
        raise RuntimeError("Disable Partyline Chrome at chrome://extensions before updating or uninstalling.")
    return "Chrome native host paused; click its toolbar button after updating to reconnect."
