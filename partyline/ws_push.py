"""Fan one event out to a line's open sockets, timing each push."""

from . import op_timing


async def push_event(runtime, conv_id: str, payload: dict) -> None:
    """Send to every socket; a failed send drops that socket.

    Each push is timed from the moment the event was handed over, so a slow
    socket earlier in the fan-out shows up as delay on the ones behind it.
    """
    name = f"push {payload.get('type', 'event')}"  # the event's type literal, never its body
    enqueued = op_timing.clock()
    for ws in list(runtime.sockets.get(conv_id, ())):
        try:
            await ws.send_json(payload)
        except Exception:
            runtime.sockets.get(conv_id, set()).discard(ws)
            runtime.human_handles.get(conv_id, {}).pop(ws, None)
            if not runtime.human_handles.get(conv_id):
                runtime.human_handles.pop(conv_id, None)
        finally:  # a slow send that then fails was still slow
            op_timing.record(name, op_timing.clock() - enqueued)
