"""Connect the shared transcript adapter lifecycle to a native Windows console."""

import asyncio
import time

from partyline import process_memory
from partyline.windows_console import WindowsConsole
from .task_logging import log_task_deaths


async def start(adapter, environment):
    adapter.spawned_at = time.time()
    console = await WindowsConsole.spawn(
        adapter.spawn_argv, adapter.att['cwd'], environment,
        process_memory.parse_size(adapter.memory_limit),
    )
    adapter.proc = console
    adapter._windows = runtime = WindowsRuntime(adapter, console)
    adapter._tasks = log_task_deaths([
        asyncio.create_task(task) for task in
        (runtime.drain(), runtime.watch_exit(), runtime.write_loop(), adapter._run())
    ], adapter.att)
    await adapter.on_status('running')


class WindowsRuntime:
    def __init__(self, adapter, console):
        self.adapter, self.console = adapter, console
        self.pending = asyncio.Queue(maxsize=64)
        self.closed = False

    def enqueue(self, data, receipt=None):
        if self.closed:
            raise OSError('terminal is closed')
        if len(data) > 1024 * 1024:
            raise OSError('terminal input exceeds 1 MiB')
        try:
            self.pending.put_nowait((data, receipt))
        except asyncio.QueueFull as exc:
            raise OSError('terminal input queue is full') from exc

    def write_nowait(self, data):
        self.enqueue(data)

    async def write(self, data):
        receipt = asyncio.get_running_loop().create_future()
        self.enqueue(data, receipt)
        await receipt

    async def write_loop(self):
        try:
            while True:
                data, receipt = await self.pending.get()
                try:
                    await self.console.write(data)
                except BaseException:
                    if receipt is not None and not receipt.done():
                        receipt.set_exception(OSError('terminal write failed'))
                    raise
                else:
                    if receipt is not None and not receipt.done():
                        receipt.set_result(None)
        finally:
            await self.close()

    async def drain(self):
        adapter = self.adapter
        try:
            while data := await self.console.read():
                try:
                    adapter._term_stream.feed(data)
                except Exception:
                    pass
                adapter._terminal_viewers.publish(data)
                # ConPTY answers native console queries; raw bytes remain peek-only.
                await adapter.on_output(data)
        finally:
            adapter._terminal_viewers.close()

    async def watch_exit(self):
        adapter = self.adapter
        code = await self.console.wait()
        await self.close()
        adapter.abort_startup_prompt()
        adapter._mark_not_ready()
        if not adapter._stopping:
            await adapter.on_status('exited')
            await adapter.post('system', 'system', f"{adapter.att['name']} exited (code {code})")

    async def close(self):
        self.closed = True
        while not self.pending.empty():
            _, receipt = self.pending.get_nowait()
            if receipt is not None and not receipt.done():
                receipt.set_exception(OSError('terminal closed before input was written'))
        await self.console.close()
