"""Event-reset quiet deadlines; timers never fetch or poll page state."""
import asyncio
import time


class Quiet:
    def __init__(self, clock=time.monotonic, scheduler=None):
        self.clock, self.scheduler = clock, scheduler
        self.waiters = set()
        self.last = clock()

    def changed(self):
        self.last = self.clock()
        for wake in list(self.waiters):
            wake()

    async def wait(self, quiet=0.1, deadline=2):
        loop = self.scheduler or asyncio.get_running_loop()
        future = asyncio.get_running_loop().create_future()
        timers = []
        def finish(value):
            if not future.done():
                future.set_result(value)
        def reset():
            if timers:
                timers.pop().cancel()
            timers.append(loop.call_later(quiet, finish, "quiet"))
        stop = loop.call_later(deadline, finish, "deadline")
        self.waiters.add(reset)
        reset()
        try:
            return await future
        finally:
            self.waiters.discard(reset)
            stop.cancel()
            for timer in timers:
                timer.cancel()
