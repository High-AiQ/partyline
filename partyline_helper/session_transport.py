"""Serialized helper writes keep frame metadata and bytes together."""
import asyncio
import contextlib
import json

from websockets.exceptions import ConnectionClosed


class SessionTransport:
    async def send(self, kind, binary=None, before=None, **fields):
        """Send one message and its bytes (or a list of byte chunks); `before` runs under the lock, last."""
        async def write():
            if before:
                await before()  # the final gate, as the write's first step: only the check precedes the bytes
            await self.socket.send(json.dumps(dict(type=kind, **fields)))
            for chunk in ([] if binary is None else binary if isinstance(binary, list) else [binary]):
                await self.socket.send(chunk)

        async with self.lock:
            if binary is None:
                await write()
                return
            # Cancellation must not insert share_stopped between metadata and bytes.
            writing = asyncio.create_task(write())
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                try:
                    await asyncio.wait_for(asyncio.shield(writing), 5)
                except (TimeoutError, ConnectionClosed):
                    await self.socket.close()
                    writing.cancel()
                    with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                        await writing
                raise
