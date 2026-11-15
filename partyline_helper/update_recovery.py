"""Revalidate persisted local window consent against live identities and server-authorized grants."""
import asyncio

from .config import config_path, save_config
from .update_preferences import read
from .uia_access import WindowAccess
from .uia_event_state import EventState
from .uia_task import WindowTask
from .update_timing import QUIESCE
from .uia_window_list import HARD_FLOOR
from .window_shares import WindowSession


def path():
    return config_path().parent / "update-recovery.json"


def snapshot(session, version):
    from .update_prompts import PENDING
    rows = []
    for ident, entry in session.windows.grants.items():
        if selected := entry["access"].grant:
            rows.append({"id": ident, "selected": selected, "target": entry["target"],
                         "standing_access": entry.get("standing_access", False),
                         "mouse_approved": entry.get("mouse_approved") is True})
    data = {"version": version, "grants": rows, "prompts": list(PENDING.values()),
            "transport": session.windows.chrome.browser.transport,
            "auto_transport": session.windows.chrome.auto_transport,
            "choose_window": session.windows.picking or session.window.picking}
    save_config(data, path())
    return data


async def restore(session, allowed, data=None, access_type=WindowAccess):
    data = read(path()) if data is None else data
    shares, restored = session.windows, []
    if data.get("auto_transport") is False:
        from .cdp_transport import BrowserConnection
        from .extension_transport import ExtensionTransport
        await shares.chrome.browser.close()
        factory = ExtensionTransport if data.get("transport") == "extension" else BrowserConnection
        shares.chrome.browser = factory(shares.chrome.report)
        shares.chrome.auto_transport = False
    for row in data.get("grants", []):
        selected, ident = row["selected"], row["id"]
        server = next((item for item in allowed if item["id"] == ident), None)
        reason = "server authorization ended"
        if (server and selected.get("marker") and selected.get("process", "").casefold() not in HARD_FLOOR
                and server["hwnd"] == selected.get("hwnd")
                and server["process"] == selected.get("process")
                and server["conv_id"] == row["target"]["line_id"]
                and (not row["standing_access"] or session.window_access_enabled)):
            worker_session = WindowSession(session, ident, shares.changed)
            worker_session.chrome = shares.chrome
            access = access_type(worker_session, on_revoke=lambda why, key=ident:
                                 shares.revoke(key, reason=why))
            worker_session.window = access
            reason = await access.check(selected)
            if reason is None:
                access.grant = selected
                access.generation += 1
                access.gate.grant()
                entry = {"access": access, "worker": WindowTask(worker_session),
                         "target": row["target"], "title": selected["title"],
                         "process": selected["process"], "standing_access": row["standing_access"],
                         "mouse_approved": row.get("mouse_approved") is True}
                shares.grants[ident] = entry
                state = EventState()
                entry["event_state"], access.event_status = state, state.status
                outline = shares.outline_factory(selected["hwnd"], pid=selected["pid"])
                entry["outline"] = outline
                entry["outline_task"] = shares.spawn(outline.start())
                shares.spawn(shares.start_events(ident, selected["hwnd"]))
                shares.chrome.start(access, retry=True)
                restored.append(ident)
        session.window_access_audit.append("", "local", "update_restore", selected.get("process", ""),
                                           selected.get("title", ""), reason or "restored")
    shares.changed()
    return restored


async def quiesce(session, timeout=QUIESCE):
    """Invalidate dispatch barriers first, then cancel work with a single bounded event wait."""
    workers = [session.window_task, *(entry["worker"] for entry in session.windows.grants.values())]
    accesses = [session.window, *(entry["access"] for entry in session.windows.grants.values())]
    for access in accesses:
        access.gate.invalidate()
    session.control.end("helper updating")
    from .prompt_processes import cancel_all
    cancel_all()
    tasks = {task for worker in workers for task in
             (worker.task, worker.read_task, worker.actions.task) if task and not task.done()}
    tasks.update(task for task in session.windows.tasks | session.windows.standing_calls
                 if not task.done())
    tasks.update(task for task in (session.worker, session.control.prompt, session.tools.prompt)
                 if task and not task.done())
    for task in tasks:
        # A UIA action future represents a real thread: keep it live until completion or the deadline.
        if task not in {worker.actions.task for worker in workers}:
            task.cancel()
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=timeout)
        for task in pending:
            task.cancel()
    # A cancelled UIA call can still hold its dispatch lock; the installer stops this process before copy.
