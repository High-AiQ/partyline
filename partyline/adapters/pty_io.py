"""Complete writes to the nonblocking pty used by process adapters."""

import asyncio
import os

WRITE_TIMEOUT = 30.0


async def wait_writable(fd: int) -> None:
    """Wait until the event loop reports that a pty can accept more bytes."""
    loop = asyncio.get_running_loop()
    ready = loop.create_future()

    def writable() -> None:
        if not ready.done():
            ready.set_result(None)

    loop.add_writer(fd, writable)
    try:
        await ready
    finally:
        loop.remove_writer(fd)


async def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        try:
            written = os.write(fd, remaining)
        except BlockingIOError:
            await wait_writable(fd)
            continue
        if written <= 0:
            raise OSError("pty write made no progress")
        remaining = remaining[written:]


async def write_all(fd: int, data: bytes) -> None:
    """Write every byte, but never hold delivery indefinitely."""
    try:
        await asyncio.wait_for(_write_all(fd, data), WRITE_TIMEOUT)
    except TimeoutError as exc:
        raise OSError("pty write timed out") from exc


class PtyWriter:
    """Mixin exposing complete writes to adapters with a pty master fd."""

    master: int | None

    async def _write_all(self, data: bytes) -> None:
        assert self.master is not None
        await write_all(self.master, data)
