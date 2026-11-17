"""Recheck helper-side window authority before routing a server call."""


def label(message):
    """The audit name of a window call."""
    return {"snapshot_window": "screenshot", "look_window": "screenshot", "read_window_elements": "uia_read",
            "window_click": "point_click", "window_point": "point_input"}.get(message["type"], "uia_action")


async def dispatch(shares, message):
    entry = shares.grants.get(message.get("grant_id"))
    if entry and entry.get("standing_access") and not shares.session.window_access_enabled:
        call = label(message)
        shares.session.window_access_audit.append(message.get("line", ""), message.get("agent", ""),
            call, entry.get("process", ""), entry.get("title", ""), "denied: toggle off")
        if message["type"] in ("snapshot_window", "look_window"):
            await shares.session.send("window_snapshot", request_id=message["request_id"], ok=False,
                                      error="window access is off in the helper")
        elif message["type"] == "read_window_elements":
            await shares.session.send("window_elements", request_id=message["request_id"],
                                      elements_unavailable="window access is off", status="failed")
        else:
            await shares.session.send("window_element_result", request_id=message["request_id"],
                                      error="window access is off", status="failed")
        return
    if message["type"] in ("snapshot_window", "look_window"):
        shares.spawn(shares.snapshots.handle(entry, message))
    elif not entry:
        gone = shares.ended.get(message.get("grant_id"), "consent revoked")
        shares.session.window_access_audit.append(message.get("line", ""), message.get("agent", ""),
            label(message), message.get("process", ""), message.get("title", ""), "denied: grant unavailable")
        if message["type"] in ("snapshot_window", "look_window"):
            await shares.session.send("window_snapshot", request_id=message["request_id"],
                                      ok=False, error=gone)
        else:
            kind = ("window_elements" if message["type"] == "read_window_elements"
                    else "window_element_result")
            error = (f"{gone}; use the Open dialog path instead"
                     if message.get("action") == "set_files" and gone == "consent revoked" else gone)
            await shares.session.send(kind, request_id=message["request_id"],
                                      elements_unavailable=error, status="failed", error=error)
    elif message["type"] in ("window_click", "window_point"):
        shares.spawn(shares.clicks.handle(entry, message))
    elif message.get("event_status"):
        await _event_status(shares, entry, message)
    elif message["type"] == "read_window_elements":
        from .uia_task import read_options
        await entry["worker"].submit(message["request_id"], read_options(message), message)
    else:
        await entry["worker"].submit_action(message)


async def _event_status(shares, entry, message):
    access = entry["access"]
    grant = getattr(access, "grant", None)
    reason = (await access.check(grant) if grant and hasattr(access, "check") else
              "consent revoked" if grant else None)
    if reason:
        if reason == "secure desktop active":
            access.gate.invalidate()
        elif reason == "window closed":
            access.revoke(reason)
        shares.session.window_access_audit.append(
            message.get("line", ""), message.get("agent", ""), "uia_read",
            entry.get("process", ""), entry.get("title", ""), f"denied: {reason}")
        await shares.session.send("window_elements", request_id=message["request_id"],
                                  elements_unavailable=reason)
        return
    if grant and grant.get("process", "").lower() == "chrome.exe":
        await shares.chrome.page(access)
        status = shares.chrome.status(access)
    else:
        state = entry.get("event_state")
        status = state.status() if state else {}
        since = message.get("events_since")
        if state and isinstance(since, int) and not isinstance(since, bool):
            status["event_sources"] = access.event_sources(since)
    await shares.session.send("window_elements", request_id=message["request_id"], **status)
