"""Route snapshots to one window explicitly granted to the calling attachment."""
import asyncio
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth_guard import request_principal
from .machine_scope import deny_unless
from .screen_grants import require_window, resolve_window
from .screen_element_actions import ElementAction, element_action
from .screen_tree import MAX_NODES, MAX_TREE, OUT_BYTES, Snapshot
from .screen_tree_ids import IdSpace
from .screen_tree_answer import answer, elements_options
from .op_timing import pushed

ELEMENT_OPTIONS = Annotated[dict, Depends(elements_options)]
SNAPSHOT_TTL = 600  # seconds a captured tree answers queries before it must be taken again
MAX_SNAPSHOTS = 16
OLD_ID = 16  # helper ids are 16 hex digits; older helpers sent 64
MAX_STORED = 300_000  # nodes all stored trees together keep; the least recently used go first
SETTLE_SECONDS = 0.5  # after a click, before the new snapshot, so a page can start to change
CAPTURE_SECONDS = 20  # one call reads parts this long, then returns a partial tree to continue with `more`


class ElementsHub:
    def __init__(self, hub, clock=time.monotonic):
        self.hub = hub
        self.waiters = {}
        self.spaces = {}  # window grant id -> its ids, kept for as long as the grant lasts
        self.snapshots = OrderedDict()  # window grant id -> its latest captured tree
        self.locks = {}
        self.clock = clock

    async def exchange(self, principal, grant, device, kind, **fields):
        require_window(self.hub, principal, grant["id"])
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                await pushed("screen", device["socket"].send_json({"type": kind, "request_id": ident,
                                                 "grant_id": grant["id"], **fields}))
                response = await future
            try:
                require_window(self.hub, principal, grant["id"])
            except HTTPException:
                if kind == "read_window_elements":
                    raise
                status = response.get("status", "unknown")
                note = ("The action was performed; the grant has since ended." if status == "completed" else
                        "The grant has since ended; the action outcome is " + status +
                        ". Do not retry automatically.")
                return {"status": status, "grant_ended": True, "note": note}
            return response
        finally:
            self.waiters.pop(ident, None)
            if not future.done():
                future.cancel()

    @asynccontextmanager
    async def locked(self, grant_id):
        """One capture or query per window at a time; the lock is dropped when nobody holds or awaits it."""
        entry = self.locks.setdefault(grant_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if not entry[1]:
                self.locks.pop(grant_id, None)

    async def settle(self):
        await asyncio.sleep(SETTLE_SECONDS)

    def end(self, grant_id):
        """The grant is over: its tree and its ids go."""
        self.forget(grant_id)
        self.spaces.pop(grant_id, None)

    def forget(self, grant_id):
        self.snapshots.pop(grant_id, None)

    async def read(self, principal, device_name=None, window=None, options=None, budget=OUT_BYTES):
        options = options or {}
        grant, device = resolve_window(self.hub, principal, window, device_name)
        try:
            async with self.locked(grant["id"]):
                self.purge()
                tree = self.fresh(grant["id"])
                if options.get("refresh") or tree is None:
                    self.forget(grant["id"])  # the helper drops its ids as a new snapshot starts
                    previous = tree
                    space = self.spaces.setdefault(grant["id"], IdSpace())
                    space.renew()
                    tree = await self.capture(principal, grant, device, Snapshot(None, self.clock(), space))
                    if previous is not None and not isinstance(tree, dict):
                        tree.before = set(previous.nodes)
                elif options.get("more") and tree.cursor:
                    tree = await self.capture(principal, grant, device, tree)
                if isinstance(tree, dict):
                    return tree
                require_window(self.hub, principal, grant["id"])  # a revoke during the capture stores nothing
                self.remember(grant["id"], tree)
                return {"window": grant["id"], "snapshot_id": tree.snapshot_id,
                        **await asyncio.to_thread(answer, tree, grant, options, budget)}
        except (TimeoutError, OSError, RuntimeError):
            return {"elements_unavailable": "helper did not respond"}

    def fresh(self, grant_id):
        tree = self.snapshots.get(grant_id)
        if tree and self.clock() - tree.created > SNAPSHOT_TTL:
            del self.snapshots[grant_id]
            return None
        return tree

    def helper_id(self, grant_id, element_id):
        """The helper's id for a stable id of the stored tree: `(helper id, ok)`; no tree passes the id on."""
        tree = self.fresh(grant_id)
        if tree is None:
            return element_id, True
        node = tree.nodes.get(element_id) or tree.nodes.get(tree.by_helper.get(element_id))  # or helper's
        return (node.helper, True) if node else (element_id, False)

    def purge(self):
        """Forget every window's tree that has outlived its time."""
        now = self.clock()
        for grant_id in [key for key, tree in self.snapshots.items() if now - tree.created > SNAPSHOT_TTL]:
            del self.snapshots[grant_id]

    def remember(self, grant_id, tree):
        self.snapshots[grant_id] = tree
        self.snapshots.move_to_end(grant_id)
        while len(self.snapshots) > 1 and (len(self.snapshots) > MAX_SNAPSHOTS or self.stored() > MAX_STORED):
            self.snapshots.popitem(last=False)

    def stored(self):
        return sum(len(tree.order) for tree in self.snapshots.values())

    async def capture(self, principal, grant, device, tree):
        """Read the helper's window part by part into `tree`; stop at a cap and keep the cursor."""
        deadline = self.clock() + CAPTURE_SECONDS
        started = tree.snapshot_id is not None
        while True:
            fields = {"cursor": tree.cursor} if tree.cursor else {}
            try:
                response = await self.exchange(principal, grant, device, "read_window_elements", **fields)
            except TimeoutError:
                if not tree.order:
                    raise
                response = {"elements_unavailable": "helper did not respond"}
            if response.get("elements_unavailable"):
                if not started and not tree.order:
                    return {"elements_unavailable": str(response["elements_unavailable"])[:160],
                            **({"truncated": True} if response.get("truncated") else {})}
                tree.note = "capture stopped: " + str(response["elements_unavailable"])[:100]
                return tree
            tree.snapshot_id = tree.snapshot_id or response.get("snapshot_id")
            started = True
            await asyncio.to_thread(tree.add, response.get("elements", []))
            if any(len(str(item.get("id", ""))) > OLD_ID for item in response.get("elements", ())):
                tree.old_helper = True
            tree.cursor = response.get("next_cursor")
            tree.changed = tree.changed or bool(response.get("changed"))
            tree.note = ""
            if response.get("truncated") and not tree.cursor:
                tree.note = "the helper cannot continue reading; update it"
            if len(tree.order) >= MAX_TREE:
                tree.cursor = None
                tree.note = f"the window has more than the {MAX_TREE} elements one snapshot keeps"
            if not tree.cursor or len(tree.order) >= MAX_NODES or self.clock() >= deadline:
                return tree

    def receive(self, device, message):
        entry = self.waiters.get(message.get("request_id"))
        if entry and entry[0] == device["id"] and not entry[1].done():
            entry[1].set_result(message)


def elements_router(runtime, hub):
    router = APIRouter()

    @router.post("/api/conversations/{conv_id}/screen-elements")
    async def elements(conv_id: str, request: Request, options: ELEMENT_OPTIONS,
                       device: str | None = None, window: str | None = None):
        principal = request_principal(request)
        deny_unless(runtime.db, principal, conv_id, "read")
        return await hub.elements.read(principal, device, window, options)

    @router.post("/api/conversations/{conv_id}/screen-control/element-action")
    async def act(conv_id: str, body: ElementAction, request: Request):
        return await element_action(runtime, hub, conv_id, body, request)

    return router
