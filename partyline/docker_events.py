"""React to Docker Engine events; never poll the daemon for changes."""

import asyncio
import json
import logging
import os

from . import docker_relay
from .docker_bridge_client import open_upstream
from .file_events import FileEvents

logger = logging.getLogger(__name__)
MAX_EVENT = 1024 * 1024
WATCHED = frozenset(("oom", "die", "start", "stop"))


async def _chunks(reader, chunked):
    if not chunked:
        while data := await reader.read(65536):
            yield data
        return
    while True:
        line = await reader.readline()
        if not line:
            return
        size = int(line.split(b";", 1)[0], 16)
        if size == 0:
            return
        if size > MAX_EVENT:
            raise ValueError("Docker event chunk too large")
        yield await reader.readexactly(size)
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("invalid Docker event chunk")


async def consume(runtime, inventory):
    """Arm the stream before the startup snapshot, then refresh on each event."""
    from .browser_snapshots import push_resources
    reader, writer = await open_upstream(docker_relay.host_socket())
    try:
        writer.write(b"GET /events HTTP/1.1\r\nHost: docker\r\n\r\n")
        await writer.drain()
        headers = await reader.readuntil(b"\r\n\r\n")
        if headers.split(b"\r\n", 1)[0].split()[1:2] != [b"200"]:
            raise OSError("Docker event stream rejected")
        await inventory.sample(runtime, force=True)
        pending = b""
        async for chunk in _chunks(reader, b"transfer-encoding: chunked" in headers.lower()):
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if len(line) > MAX_EVENT:
                    raise ValueError("Docker event too large")
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("Type") == "container" \
                        and event.get("Action") in WATCHED:
                    await inventory.sample(runtime, force=True)
                    if any(runtime.sockets.values()):
                        await push_resources(runtime)
            if len(pending) > MAX_EVENT:
                raise ValueError("Docker event too large")
    finally:
        writer.close()


async def run(runtime, inventory=None):
    """Re-arm a lost stream on grant or socket changes, never on a timer."""
    if inventory is None:
        from .docker_workloads import inventory
    socket = docker_relay.host_socket()
    async with FileEvents(socket, os.path.realpath(socket)) as files:
        with runtime.db.events.subscribe("conversation_write_grants", "conversations") as db_events:
            stream = None
            failed = False
            db_wait = asyncio.create_task(db_events.wait())
            file_wait = asyncio.create_task(files.wait())
            try:
                while True:
                    if stream is None and not failed and (inventory.watching or await asyncio.to_thread(
                            docker_relay.any_grant, runtime.db)):
                        stream = asyncio.create_task(consume(runtime, inventory))
                    watched = {db_wait, file_wait}
                    if stream is not None:
                        watched.add(stream)
                    done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
                    if stream in done:
                        try:
                            stream.result()
                        except Exception:
                            logger.exception("Docker event stream ended")
                        stream = None
                        failed = True
                    if db_wait in done:
                        db_wait.result()
                        db_wait = asyncio.create_task(db_events.wait())
                        if stream is not None and not inventory.watching and not await asyncio.to_thread(
                                docker_relay.any_grant, runtime.db):
                            stream.cancel()
                            await asyncio.gather(stream, return_exceptions=True)
                            stream = None
                        failed = False
                    if file_wait in done:
                        file_wait.result()
                        file_wait = asyncio.create_task(files.wait())
                        if stream is not None:
                            stream.cancel()
                            await asyncio.gather(stream, return_exceptions=True)
                            stream = None
                        failed = False
            finally:
                for task in (stream, db_wait, file_wait):
                    if task is not None:
                        task.cancel()
                await asyncio.gather(*(task for task in (stream, db_wait, file_wait)
                                       if task is not None), return_exceptions=True)


def close():
    from .docker_workloads import inventory
    inventory.deadlines.close()
