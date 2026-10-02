"""Wait for a child without occupying asyncio's shared worker pool."""

import asyncio
import subprocess
import threading


async def wait_for_process(proc: subprocess.Popen) -> int:
    """Reap ``proc`` on one daemon thread and deliver its result to the loop."""
    loop = asyncio.get_running_loop()
    result = loop.create_future()

    def complete(value: int | BaseException, failed: bool = False) -> None:
        if result.done():
            return
        if failed:
            result.set_exception(value)
        else:
            result.set_result(value)

    def wait() -> None:
        try:
            code = proc.wait()
        except BaseException as exc:
            value, failed = exc, True
        else:
            value, failed = code, False
        try:
            loop.call_soon_threadsafe(complete, value, failed)
        except RuntimeError:  # The loop may close while a child is still exiting.
            pass

    threading.Thread(target=wait, name=f"partyline-wait-{proc.pid}", daemon=True).start()
    return await result
