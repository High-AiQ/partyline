"""Screen sampling is separate from event-driven local stop-input ownership."""

import asyncio


async def _stop_input(session, request, stopped):
    changes = session.control.input_changes
    while session.share is request:
        observed = changes.version
        if session.control.prompting:
            await changes.wait_after(observed)
            continue
        reading = asyncio.create_task(session.terminal.read(None))
        session.stop_read = reading
        changed = asyncio.create_task(changes.wait_after(observed))
        try:
            done, _ = await asyncio.wait((reading, changed), return_when=asyncio.FIRST_COMPLETED)
            if reading not in done or reading.cancelled():
                changed.result()
                continue  # a consent prompt now owns terminal input
            if reading.result() == 's':
                session.share = None
                session.accepted = False
                session.pending_id = None
                session.control.end('sharing stopped locally')
                await session.send('share_stopped', share_id=request['share_id'], reason='local')
                print('Sharing stopped: local', flush=True)
                stopped.set()
                return
        finally:
            reading.cancel()
            changed.cancel()
            await asyncio.gather(reading, changed, return_exceptions=True)
            if getattr(session, "stop_read", None) is reading:
                session.stop_read = None


async def capture(session, request):
    sleep = getattr(session, "capture_sleep", session.sleep)
    stopped = asyncio.Event()
    input_task = asyncio.create_task(_stop_input(session, request, stopped))
    deadline = stopped_task = None
    try:
        while session.share is request:
            await session.frame()
            # Audit exception (a): MSS has no frame-change notification API.
            deadline = asyncio.create_task(sleep(1 / request['max_fps']))
            stopped_task = asyncio.create_task(stopped.wait())
            done, _ = await asyncio.wait((deadline, stopped_task, input_task),
                                         return_when=asyncio.FIRST_COMPLETED)
            if input_task in done:
                input_task.result()
                return
            deadline.cancel()
            stopped_task.cancel()
            await asyncio.gather(deadline, stopped_task, return_exceptions=True)
    finally:
        tasks = [input_task, *([deadline, stopped_task] if deadline is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
