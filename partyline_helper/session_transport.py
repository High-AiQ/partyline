"""Serialized helper writes keep frame metadata and bytes together."""
import asyncio
import contextlib
import json

from websockets.exceptions import ConnectionClosed


class SessionTransport:
    async def send(self, kind, binary=None, **fields):
        async def write():
            await self.socket.send(json.dumps(dict(type=kind, **fields)))
            if binary is not None:
                await self.socket.send(binary)

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
