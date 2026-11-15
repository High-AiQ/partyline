"""Authenticated local IPC, with synchronous writes for the revoke gate."""
import asyncio
import json

from .native_codec import Decoder, frame, length, packets


class NativeSocket:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.decoder = Decoder()

    def send_nowait(self, message):
        for packet in packets(message):
            self.writer.write(frame(packet))

    async def send(self, raw):
        self.send_nowait(json.loads(raw))
        await self.writer.drain()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            while True:
                size = length(await self.reader.readexactly(4))
                message = self.decoder.accept(json.loads(await self.reader.readexactly(size)))
                if message is not None:
                    return json.dumps(message)
        except asyncio.IncompleteReadError:
            raise StopAsyncIteration from None

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()
