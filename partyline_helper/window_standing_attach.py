"""No-prompt attach flow for a window already approved by the standing helper toggle."""
import uuid

from .uia_access import WindowAccess
from .uia_event_state import EventState
from .uia_task import WindowTask
from .window_shares import WindowSession


async def attach(shares, message, generation=None):
    ident, hwnd = message.get("request_id"), message.get("window")
    generation = shares.generation if generation is None else generation
    line, agent = message.get("line", ""), message.get("agent", "")
    rows = getattr(shares.session, "standing_window_rows", {})
    if generation != shares.generation or not shares.session.window_access_enabled:
        shares.session.window_access_audit.append(line, agent, "attach", "", "",
                                                  "denied: access paused")
        return await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                         error="window access is paused")
    selected = rows.pop(str(hwnd), None)
    if selected is None:
        shares.session.window_access_audit.append(message.get("line", ""), message.get("agent", ""),
                                                  "attach", "", "", "denied: unavailable or protected")
        return await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                         error="window unavailable or protected")
    grant_id, access = uuid.uuid4().hex, None
    granted = attached = False
    try:
        shares.session.window_access_audit.append(line, agent, "attach", selected["process"],
                                                  selected["title"], "requested")
        targets = await shares.request("list_share_targets")
        target = next((row for row in targets.get("lines", ())
                       if row.get("line_id") == message.get("line_id")), None)
        if not target or not target.get("standing_access"):
            shares.session.window_access_audit.append(line, agent, "attach", selected["process"],
                                                      selected["title"], "denied: line unavailable")
            return await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                             error="the calling line is not owned by this person")
        session = WindowSession(shares.session, grant_id, shares.changed)
        session.chrome = shares.chrome
        access = WindowAccess(session, on_revoke=lambda reason: shares.revoke(grant_id, reason=reason))
        session.window = access
        access.grant = selected
        invalid = (not selected.get("marker") or generation != shares.generation
                   or await access.check(selected) or not shares.session.window_access_enabled)
        if invalid:
            access.grant = None
            shares.session.window_access_audit.append(line, agent, "attach", selected["process"],
                                                      selected["title"], "denied: window unavailable")
            return await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                             error="window unavailable or access paused")
        response = await shares.request("window_grant", grant_id=grant_id, line_id=target["line_id"],
            targets_request_id=targets["request_id"], hwnd=selected["hwnd"], title=selected["title"],
            process=selected["process"], standing_access=True)
        if not response.get("ok"):
            raise ValueError("grant refused")
        granted = True
        if (generation != shares.generation or not shares.session.window_access_enabled
                or await access.check(selected)):
            raise ValueError("window access changed while attaching")
        access.generation += 1
        access.gate.grant()
        entry = {"access": access, "worker": WindowTask(session), "target": response["target"],
                 "title": selected["title"], "process": selected["process"],
                 "standing_access": True}
        shares.grants[grant_id] = entry
        outline = shares.outline_factory(selected["hwnd"], pid=selected["pid"])
        entry["outline"] = outline
        entry["outline_task"] = shares.spawn(outline.start())
        state = EventState()
        entry["event_state"], access.event_status = state, state.status
        shares.chrome.start(access, retry=True)
        shares.spawn(shares.start_events(grant_id, selected["hwnd"]))
        shares.session.window_access_audit.append(line, agent, "attach", selected["process"],
                                                  selected["title"], "granted")
        if not shares.standing_toast:
            shares.session.status.attention(
                f"Window attached for {message.get('line_name', message.get('line_id'))} "
                f"— @{agent or 'agent'}")
            shares.standing_toast = True
        shares.changed()
        attached = True
        await shares.session.send("attach_window_result", request_id=ident, ok=True,
                                  window=grant_id, title=selected["title"])
    except Exception:
        if grant_id in shares.grants:
            shares.revoke(grant_id, notify=False)
        if granted:
            await shares.send_revoked(grant_id)
        shares.session.window_access_audit.append(line, agent, "attach", selected["process"],
                                                  selected["title"], "failed")
        await shares.session.send("attach_window_result", request_id=ident, ok=False,
                                  error="window could not be attached")
    finally:
        if not attached and selected.get("marker"):
            from .uia_window_identity import unmark
            unmark(selected)
            if access:
                access.grant = None
