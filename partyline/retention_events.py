"""Wake pending temporary-directory reaps on manifest changes or retained-job exit."""

import asyncio
from contextlib import asynccontextmanager
import json

from .attachment_tmp import base_dir
from .file_events import FileEvents
from .process_events import process_exited
from .tmp_retention import process_identity


def retained_jobs():
    registry = base_dir() / '.pending-reaps'
    if registry.is_symlink() or not registry.is_dir():
        return set()
    jobs = set()
    for path in registry.glob('*.json'):
        try:
            payload = json.loads(path.read_text())
            for pid, identity in payload.get('processes', {}).items():
                pid = int(pid)
                if identity is not None and process_identity(pid) == identity:
                    jobs.add(pid)
        except (OSError, ValueError, TypeError):
            continue  # unreadable retention intent stays pending, never deleted
    return jobs


async def _watch(changes):
    watching = {}
    files_task = None
    async with FileEvents(base_dir() / '.pending-reaps') as files:
        try:
            while True:
                jobs = await asyncio.to_thread(retained_jobs)
                for pid in jobs - watching.keys():
                    watching[pid] = asyncio.create_task(process_exited(pid))
                for pid in watching.keys() - jobs:
                    watching.pop(pid).cancel()
                files_task = asyncio.create_task(files.wait(asyncio.current_task()))
                done, _ = await asyncio.wait([files_task, *watching.values()],
                                              return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
                changes.notify()
                files_task.cancel()
                await asyncio.gather(files_task, return_exceptions=True)
                for pid, task in list(watching.items()):
                    if task.done():
                        del watching[pid]
        finally:
            tasks = [*watching.values(), *([files_task] if files_task else [])]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def retention_notifications(changes):
    task = asyncio.create_task(_watch(changes))

    def failed(done):
        if not done.cancelled() and done.exception() is not None:
            changes.notify(done.exception())

    task.add_done_callback(failed)
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
