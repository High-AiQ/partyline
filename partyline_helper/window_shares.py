"""Independent window grants and snapshots, multiplexed over the existing helper socket."""
import asyncio
import contextlib
import uuid
from types import SimpleNamespace

from websockets.exceptions import ConnectionClosed

from .uia_access import WindowAccess, select_window
from .uia_task import WindowTask
from .uia_window_identity import unmark
from .window_target_picker import select_target

MESSAGES = ("share_targets", "window_grant_result", "revoke_window")


class WindowSession:
    """Each worker sees its own window state and the live parent session's shared services."""
    def __init__(self, parent, ident, changed):
        self.parent, self.window_grant_id = parent, ident
        self.status = SimpleNamespace(window_title=None, changed=changed)

    def __getattr__(self, name):
        return getattr(self.parent, name)


class WindowShares:
    def __init__(self, session, window_picker=select_window, target_picker=select_target):
        self.session, self.window_picker, self.target_picker = session, window_picker, target_picker
        self.grants, self.waiters, self.tasks = {}, {}, set()
        self.picking, self.generation = False, 0

    async def request(self, kind, **fields):
        ident = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = future
        try:
            async with asyncio.timeout(70):
                await self.session.send(kind, request_id=ident, **fields)
                return await future
        finally:
            self.waiters.pop(ident, None)

    async def receive(self, message):
        if message["type"] == "revoke_window":
            self.revoke(message.get("grant_id"), notify=False)
            return
        future = self.waiters.get(message.get("request_id"))
        if future and not future.done():
            future.set_result(message)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send_revoked(self, ident, reason="revoked by the person"):
        with contextlib.suppress(ConnectionClosed, OSError):
            await self.session.send("window_revoked", grant_id=ident, reason=reason)

    def changed(self):
        labels = {ident: f"{entry['title']} → @{entry['target']['name']} «{entry['target']['line_name']}»"
                  for ident, entry in self.grants.items()}
        self.session.status.window_grants = labels
        self.session.status.window_title = "; ".join(labels.values()) or None
        self.session.status.changed()

    async def choose(self):
        if self.picking:
            return
        self.picking = True
        generation, selected, registered = self.generation, None, None
        try:
            selected = await asyncio.to_thread(self.window_picker)
            if not selected or generation != self.generation:
                return
            targets = await self.request("list_share_targets")
            target = await asyncio.to_thread(self.target_picker, targets["lines"])
            if not target or generation != self.generation:
                return
            ident = uuid.uuid4().hex
            access_session = WindowSession(self.session, ident, self.changed)
            access = WindowAccess(access_session, on_revoke=lambda reason: self.revoke(ident, reason=reason))
            access_session.window = access
            if await access.check(selected) or generation != self.generation:
                return
            self.session.tools.audit.append("event", "window", "local", "window_read",
                f"granted: {selected['title']} ({selected['process']}) "
                f"to @{target['name']} on «{target['line_name']}»")
            registered = ident
            response = await self.request("window_grant", grant_id=ident,
                attachment_id=target["attachment_id"], targets_request_id=targets["request_id"],
                hwnd=selected["hwnd"], title=selected["title"], process=selected["process"])
            if not response.get("ok"):
                return
            registered = ident
            if generation != self.generation:
                return
            access.grant = selected
            access.generation += 1
            access.gate.grant()
            worker = WindowTask(access_session)
            self.grants[ident] = {"access": access, "worker": worker, "target": response["target"],
                                  "title": selected["title"]}
            selected, registered = None, None
            self.changed()
        except (OSError, ValueError, KeyError, TimeoutError, ConnectionClosed):
            pass  # both local consent steps and server validation must succeed
        finally:
            if registered:
                await self.send_revoked(registered)
            if selected:
                unmark(selected)
            self.picking = False

    def revoke(self, ident, notify=True, *, reason="revoked by the person"):
        entry = self.grants.pop(ident, None)
        if entry:
            entry["access"].revoke()
            self.spawn(entry["worker"].close())
            if notify:
                reason = {"window closed": "window closed", "replaced": "replaced by another grant"}.get(
                    reason, "revoked by the person")
                self.spawn(self.send_revoked(ident, reason))
            self.changed()

    def revoke_all(self, notify=True):
        self.generation += 1  # also cancels consent currently open in a native picker
        for ident in list(self.grants):
            self.revoke(ident, notify)

    async def dispatch(self, message):
        entry = self.grants.get(message.get("grant_id"))
        if not entry:
            kind = "window_elements" if message["type"] == "read_window_elements" else "window_element_result"
            await self.session.send(kind, request_id=message["request_id"],
                                    elements_unavailable="consent revoked",
                                    status="failed", error="consent revoked")
        elif message["type"] == "read_window_elements":
            await entry["worker"].submit(message["request_id"])
        else:
            await entry["worker"].submit_action(message)

    async def watch(self):
        async def sleep(delay):
            await self.session.sleep(delay)
        while True:
            await sleep(1)
            for entry in list(self.grants.values()):
                access = entry["access"]
                grant = access.grant
                if not grant:
                    continue
                reason = await access.check(grant)
                if access.grant is not grant:
                    continue
                if reason == "window closed":
                    access.revoke(reason)
                elif reason == "secure desktop active":
                    access.gate.invalidate()
                elif access.grant and access.gate.revoked.is_set():
                    access.gate.grant()

    async def close(self):
        self.revoke_all(notify=False)
        for future in list(self.waiters.values()):
            if not future.done():
                future.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
