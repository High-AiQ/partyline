"""Connect the shared transcript adapter lifecycle to a native Windows console."""

import asyncio
import time

from partyline import features, fence, process_memory, windows_scope
from partyline.windows_console import WindowsConsole
from .task_logging import log_task_deaths


async def start(adapter, environment):
    adapter.spawned_at = time.time()
    scope = None
    if fence.backend() == 'restricted-token' and features.enabled('write_fence'):
        preparation = asyncio.create_task(asyncio.to_thread(windows_scope.prepare, adapter, environment))
        try:
            scope = await asyncio.shield(preparation)
        except BaseException:
            # Cancellation does not stop the ACL worker. Join it and undo its
            # changes before propagating cancellation to the attach request.
            prepared = await preparation
            await asyncio.to_thread(prepared.close)
            raise
    try:
        console = await WindowsConsole.spawn(
            adapter.spawn_argv, adapter.att['cwd'], environment,
            process_memory.parse_size(adapter.memory_limit), token=scope.token if scope else None,
        )
    except BaseException:
        if scope:
            await asyncio.to_thread(scope.close)
        raise
    adapter.proc = console
    adapter._windows = runtime = WindowsRuntime(adapter, console, scope)
    adapter._tasks = log_task_deaths([
        asyncio.create_task(task) for task in
        (runtime.drain(), runtime.watch_exit(), runtime.write_loop(), adapter._run())
    ], adapter.att)
    await adapter.on_status('running')


class WindowsRuntime:
    def __init__(self, adapter, console, scope=None):
        self.adapter, self.console = adapter, console
        self.scope = scope
        self.close_lock = asyncio.Lock()
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
                item = await self.pending.get()
                if item is None:
                    return
                data, receipt = item
                if receipt is not None and receipt.cancelled():
                    continue
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
        async with self.close_lock:
            if self.closed:
                return
            self.closed = True
            while not self.pending.empty():
                _, receipt = self.pending.get_nowait()
                if receipt is not None and not receipt.done():
                    receipt.set_exception(OSError('terminal closed before input was written'))
            self.pending.put_nowait(None)
            # Stop the entire job before releasing its filesystem permissions.
            await self.console.close()
            if self.scope:
                await asyncio.to_thread(self.scope.close)
