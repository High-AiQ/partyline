"""Handle window discovery and no-prompt attach requests from the server."""
import asyncio
import contextlib

from websockets.exceptions import ConnectionClosed


async def standing_call(shares, message):
    status = shares.session.status
    call = status.begin_window_call(message.get("line_name", message.get("line", "line")),
                                   message.get("agent", "agent"))
    try:
        return await _call(shares, message)
    except asyncio.CancelledError:
        line, agent, ident = (message.get("line", ""), message.get("agent", ""),
                              message.get("request_id"))
        kind = message.get("type")
        with contextlib.suppress(OSError):
            shares.session.window_access_audit.append(line, agent, kind, "", "",
                                                       "cancelled: access paused")
        with contextlib.suppress(ConnectionClosed, OSError):
            if kind == "screen_windows":
                await shares.session.send("screen_windows_result", request_id=ident, windows=[],
                                          error="window access was paused")
            else:
                await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                          error="window access was paused")
    except Exception:
        line, agent, ident = (message.get("line", ""), message.get("agent", ""),
                              message.get("request_id"))
        kind = message.get("type")
        with contextlib.suppress(OSError):
            shares.session.window_access_audit.append(line, agent, kind, "", "", "failed")
        with contextlib.suppress(ConnectionClosed, OSError):
            if kind == "screen_windows":
                await shares.session.send("screen_windows_result", request_id=ident, windows=[],
                                          error="window access request failed")
            else:
                await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                          error="window could not be attached")
    finally:
        status.end_window_call(call)


async def _call(shares, message):
    ident, kind = message.get("request_id"), message.get("type")
    session = shares.session
    audit = session.window_access_audit
    line, agent = message.get("line", ""), message.get("agent", "")
    generation = shares.generation
    if not session.window_access_enabled:
        audit.append(line, agent, kind, "", "", "denied: toggle off")
        if kind == "screen_windows":
            return await session.send("screen_windows_result", request_id=ident, windows=[],
                                      error="window access is off in the helper")
        return await session.send("attach_window_result", request_id=ident, ok=False,
                                  error="window access is off in the helper")
    try:
        targets = await shares.request("list_share_targets")
        owner_line = next((row for row in targets.get("lines", ())
                           if row.get("line_id") == message.get("line")), None)
    except Exception:
        owner_line = None
    if not owner_line or not owner_line.get("standing_access"):
        audit.append(line, agent, kind, "", "", "denied: line is not owned by the paired person")
        if kind == "screen_windows":
            return await session.send("screen_windows_result", request_id=ident, windows=[],
                                      error="the caller's line is not owned by the paired person")
        return await session.send("attach_window_result", request_id=ident, ok=False,
                                  error="the caller's line is not owned by the paired person")
    if kind != "screen_windows":
        from .window_standing_attach import attach
        await attach(shares, message, generation)
        return
    from .uia_window_list import discover_windows
    try:
        rows = await discover_windows(session)
        if generation != shares.generation or not session.window_access_enabled or rows is None:
            rows = None
    except Exception:
        rows = None
    paused = rows is None
    result = "paused: secure desktop" if paused else f"listed {len(rows)}"
    audit.append(line, agent, "list", "multiple", "window list", result)
    rows = [{key: row[key] for key in ("id", "hwnd", "process", "title", "state", "url") if key in row}
            for row in rows or ()]
    await session.send("screen_windows_result", request_id=ident, windows=rows,
                       error="screen access is paused while the screen is locked" if paused else None)
