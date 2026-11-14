"""Monitor previews: every get_preview is answered with a preview or an error."""
import asyncio
import math

from websockets.exceptions import ConnectionClosed

from .bounds import bounded
from .images import encode

RATE_SECONDS = 3
# Below the server's preview deadline, so a stuck capture is reported rather than timed out.
GRAB_SECONDS = 6


class Refused(Exception):
    """A request the helper declines without trying a capture."""


async def get_preview(session, message):
    request_id, monitor_id = message.get("request_id"), message.get("monitor_id")
    try:
        await _send_preview(session, message)
        return
    except Refused as exc:
        reason = str(exc)
    except ConnectionClosed:
        raise  # no socket to answer on
    except Exception as exc:  # capture backends raise their own types; the server must not time out
        session.preview_times.pop(monitor_id, None)  # a failed grab must not lock the retry out
        reason = f"could not capture monitor {monitor_id}: {exc or type(exc).__name__}"
    print(f"Preview failed: {reason}", flush=True)
    await session.send("error", request_id=request_id, message=reason)


async def _send_preview(session, message):
    monitor = next((m for m in session.desktop.monitors() if m["id"] == message.get("monitor_id")), None)
    if monitor is None:
        raise Refused(f"monitor {message.get('monitor_id')} is not connected to this computer")
    pending = session.grab_task
    if pending is not None and not pending.done():
        raise Refused("the previous capture on this computer has not finished; try again shortly")
    now = session.clock()
    if now - session.preview_times.get(monitor["id"], -math.inf) < RATE_SECONDS:
        raise Refused("Preview rate limit: one per monitor every 3 seconds")
    session.preview_times[monitor["id"]] = now
    print(f"Taking preview of monitor {monitor['id']}", flush=True)
    edge = min(480, int(bounded(message.get("long_edge"), 480, 1, 32768)))
    image = await _grab(session, monitor)
    # A 4K image takes long enough to convert and resize that the event loop must not wait on it.
    binary, width, height, mime = await asyncio.to_thread(encode, image, edge)
    await session.send("preview", binary, request_id=message["request_id"], monitor_id=monitor["id"],
                       out_width=width, out_height=height, mime=mime)


async def _grab(session, monitor):
    """Bound the capture; a thread that never returns is left behind, and no second one starts."""
    task = session.grab_task = asyncio.ensure_future(asyncio.to_thread(session.desktop.grab, monitor))
    task.add_done_callback(lambda done: done.cancelled() or done.exception())  # a late failure is not news
    try:
        return await asyncio.wait_for(asyncio.shield(task), GRAB_SECONDS)
    except TimeoutError:
        raise RuntimeError(f"the capture did not finish within {GRAB_SECONDS} s") from None
