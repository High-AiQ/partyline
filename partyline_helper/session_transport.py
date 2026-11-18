"""Serialized helper writes keep frame metadata and bytes together."""
import asyncio
import contextlib
import json
import uuid

from websockets.exceptions import ConnectionClosed

from .timing import Timing


class SessionTransport:
    async def set_window_access(self, enabled):
        from .screen_access_toggle import set_window_access
        await set_window_access(self, enabled)

    async def pause_windows(self):
        from .screen_access_toggle import pause_windows
        await pause_windows(self)

    def request_window_access(self, enabled, loop):
        from .screen_access_toggle import request_window_access
        return request_window_access(self, enabled, loop)

    async def send(self, kind, binary=None, before=None, **fields):
        """Send one message and its bytes (or a list of byte chunks); `before` runs under the lock, last."""
        timing = Timing(fields.setdefault("timing", {})) if kind in (
            "window_elements", "window_element_result", "window_snapshot") else None

        async def write():
            if before:
                await before()  # the final gate, as the write's first step: only the check precedes the bytes
            if timing:
                # Preparation through the writer lock; a packet cannot report its own completed send.
                timing.values["reply_ms"] = timing.elapsed(timing.started)
                sentinel = uuid.uuid4().hex
                timing.values["serialize_ms"] = sentinel
                started = timing.clock()
                packet = json.dumps(dict(type=kind, **fields))
                measured = timing.elapsed(started)
                timing.values["serialize_ms"] = measured
                marker = f'"serialize_ms": "{sentinel}"'
                packet = packet.replace(marker, f'"serialize_ms":{measured}', 1)
            else:
                packet = json.dumps(dict(type=kind, **fields))
            await self.socket.send(packet)
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
