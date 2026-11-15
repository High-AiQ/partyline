"""Route snapshots to a window a person granted to the calling process's line."""
import asyncio
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from fastapi import HTTPException

from .auth_guard import request_principal  # noqa: F401 - kept as the screen route patch surface
from .machine_scope import deny_unless  # noqa: F401
from .screen_audit import record_standing_window_access  # noqa: F401
from .screen_element_actions import ElementAction, element_action  # noqa: F401
from .screen_eval import ScreenEval, audit_call, screen_eval  # noqa: F401
from .screen_grants import require_window, resolve_window
from .screen_tree import OUT_BYTES, Snapshot
from .screen_element_state import ElementState, compare
from .screen_tree_ids import IdSpace
from .screen_tree_answer import answer
from .op_timing import pushed
from .screen_timing import timed, phase, helper

SNAPSHOT_TTL = 3  # seconds a captured tree answers queries before it must be taken again
MAX_SNAPSHOTS = 16
MAX_STORED = 300_000  # nodes all stored trees together keep; the least recently used go first


class ElementsHub(ElementState):
    def __init__(self, hub, clock=time.monotonic):
        self.hub = hub
        self.waiters = {}
        self.spaces = {}  # window grant id -> its ids, kept for as long as the grant lasts
        self.snapshots = OrderedDict()  # window grant id -> its latest captured tree
        self.locks = {}
        self.clock = clock
        self.change_versions = {}
        self.after_action = set()

    async def exchange(self, principal, grant, device, kind, **fields):
        require_window(self.hub, principal, grant["id"])
        ident = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.waiters[ident] = (device["id"], future)
        try:
            async with asyncio.timeout(35):
                line_id = getattr(principal, "conv_id", None) or grant.get("conv_id", "")
                line = self.hub.runtime.db.get_conversation(line_id) if line_id else None
                with phase("send_ms"):
                    await pushed("screen", device["socket"].send_json({"type": kind, "request_id": ident,
                        "grant_id": grant["id"],
                        "line": line_id,
                        "line_id": line_id,
                        "line_name": line["name"] if line else line_id,
                        "agent": getattr(principal, "name", ""),
                        "title": grant.get("title", ""), "process": grant.get("process", ""), **fields}))
                with phase("helper_roundtrip_ms"):
                    response = await future
                helper(response.get("timing", {}))
            try:
                require_window(self.hub, principal, grant["id"])
            except HTTPException:
                if kind in ("read_window_elements", "snapshot_window"):
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
            with phase("window_lock_ms"):
                await entry[0].acquire()
            try:
                yield
            finally:
                entry[0].release()
        finally:
            entry[1] -= 1
            if not entry[1]:
                self.locks.pop(grant_id, None)

    def end(self, grant_id):
        """The grant is over: its tree and its ids go."""
        self.forget(grant_id)
        self.spaces.pop(grant_id, None)
        self.change_versions.pop(grant_id, None)
        self.after_action.discard(grant_id)

    def forget(self, grant_id):
        self.snapshots.pop(grant_id, None)

    @timed
    async def read(self, principal, device_name=None, window=None, options=None, budget=OUT_BYTES):
        options = options or {}
        grant, device = resolve_window(self.hub, principal, window, device_name)
        try:
            async with self.locked(grant["id"]):
                if options.get("inspect"):
                    return await self.inspect(principal, grant, device, options["inspect"])
                previous = self.snapshots.get(grant["id"])
                preserve = grant["id"]
                self.purge(preserve=preserve)
                tree = self.fresh(grant["id"], more=bool(options.get("more")))
                restarting = bool(options.get("more") and previous and previous.cursor and tree is None)
                if (tree is not None and not options.get("refresh") and
                        not await self.barrier(principal, grant, device, tree)):
                    restarting = bool(options.get("more") and tree.cursor)
                    tree = None
                query = {key: options[key] for key in ("query", "control_type") if options.get(key)}
                scoped = bool(query and not any(options.get(key) for key in
                                               ("text", "root", "id", "value", "more")))
                if tree is not None and tree.scope and tree.scope != (query if scoped else None):
                    tree = None
                continuation = options.get("more") and tree and tree.cursor
                forced = grant["id"] in self.after_action and not continuation
                captured = bool(options.get("refresh") or tree is None or forced or continuation)
                if options.get("refresh") or tree is None or forced:
                    if not scoped:
                        self.forget(grant["id"])  # only a full capture resets helper IDs
                    space = self.spaces.setdefault(grant["id"], IdSpace())
                    space.renew()
                    tree = Snapshot(None, self.clock(), space)
                    tree.scope = query if scoped else None
                    if scoped:
                        tree.retain_actions(previous)
                    tree.event_version = self.change_versions.get(grant["id"], 0)
                    tree = await self.capture(principal, grant, device, tree)

                elif options.get("more") and tree.cursor:
                    tree = await self.capture(principal, grant, device, tree)
                if isinstance(tree, dict):
                    return tree
                restarting = restarting or bool(options.get("more") and previous and
                                                 tree.snapshot_id != previous.snapshot_id)
                if previous is not None and previous is not tree and not tree.scope and not previous.scope:
                    with phase("diff_ms"):
                        await asyncio.to_thread(compare, tree, previous)
                require_window(self.hub, principal, grant["id"])  # a revoke during the capture stores nothing
                self.remember(grant["id"], tree)
                if not (grant["id"] in self.after_action and options.get("more")):
                    self.after_action.discard(grant["id"])
                options = dict(options)
                for key in ("id", "root"):
                    if options.get(key) not in tree.nodes and options.get(key) in tree.by_helper:
                        options[key] = tree.by_helper[options[key]]
                with phase("answer_ms"):
                    result = await asyncio.to_thread(answer, tree, grant, options, max(256, budget - 600))
                remote_changed = captured and await self.capture_status(principal, grant, device, tree)
                if restarting:
                    result["continuation_restarted"] = "capture restarted from the root"
                capture_raced = getattr(tree, "capture_raced", False)
                tree.capture_raced = False  # report the observed capture race once, not on later cache hits
                result.update(snapshot_event_counter=getattr(tree, "event_counter", None),
                              snapshot_age_seconds=max(0, round(self.clock() - tree.created, 3)),
                              change_event_since_snapshot=(remote_changed or tree.changed or
                                                           capture_raced or
                                                           tree.event_version !=
                                                           self.change_versions.get(grant["id"], 0)))
                return {"window": grant["id"], "snapshot_id": tree.snapshot_id, **result}
        except (TimeoutError, OSError, RuntimeError):
            return {"elements_unavailable": "helper did not respond"}

    def fresh(self, grant_id, more=False):
        tree = self.snapshots.get(grant_id)
        if tree and getattr(tree, "event_version", self.change_versions.get(grant_id, 0)) != \
                self.change_versions.get(grant_id, 0):
            return None
        if tree and self.clock() - tree.created > SNAPSHOT_TTL and not (more and tree.cursor):
            return None
        return tree

    def changed(self, grant_id):
        """A helper UIA event invalidates this grant's tree without resetting its stable ids."""
        self.change_versions[grant_id] = self.change_versions.get(grant_id, 0) + 1

    def action_completed(self, grant_id, retain_snapshot=False):
        """The next read must be fresh, including after a `then` snapshot taken too soon."""
        if not retain_snapshot:
            self.forget(grant_id)
        self.after_action.add(grant_id)

    def helper_id(self, grant_id, element_id):
        """The helper's id for a stable id of the stored tree: `(helper id, ok)`; no tree passes the id on."""
        tree = self.fresh(grant_id)
        return self._helper_id(tree, element_id)

    def locked_target(self, grant_id, element_id):
        """Translate under the window lock against the newest stored tree, which action_target refreshed.

        Another process on the line may have recaptured meanwhile; its tree is the current id space.
        `(None, False)`: an id space exists but no tree survived, so the caller must read again.
        """
        tree = self.snapshots.get(grant_id)
        if tree is None and grant_id in self.spaces:
            return None, False
        return self._helper_id(tree, element_id)

    @staticmethod
    def _helper_id(tree, element_id):
        """Translate against the tree already checked fresh by the caller."""
        if tree is None:
            return element_id, True
        node = tree.nodes.get(element_id) or tree.nodes.get(tree.by_helper.get(element_id))  # or helper's
        if node:
            return node.helper, True
        if tree.scoped:
            if element_id in tree.action_ids:
                return tree.action_ids[element_id], True
            if element_id in tree.prior_helpers:
                return element_id, True
        return element_id, False

    async def action_target(self, principal, grant, element_id):
        """Recapture expired trees before translating stable ids to the helper's current ids."""
        tree = self.fresh(grant["id"])
        if tree is None:
            previous = self.snapshots.get(grant["id"])
            if (previous is not None and getattr(previous, "event_counter", None) is not None and
                    await self.barrier(principal, grant, resolve_window(self.hub, principal, grant["id"])[1],
                                       previous)):
                return self._helper_id(previous, element_id)  # live counter proof supersedes the TTL
            if grant["id"] not in self.spaces:
                return element_id, True  # no server snapshot has established a stable id space yet
            result = await self.read(principal, window=grant["id"], options={"refresh": True})
            if result.get("elements_unavailable"):
                return None, False
            tree = self.snapshots.get(grant["id"])
            if tree is None or tree.event_version != self.change_versions.get(grant["id"], 0):
                return None, False
        return self._helper_id(tree, element_id)

    def purge(self, preserve=None):
        """Forget every window's tree that has outlived its time."""
        now = self.clock()
        for grant_id in [key for key, tree in self.snapshots.items()
                         if now - tree.created > SNAPSHOT_TTL and
                         key != preserve]:
            del self.snapshots[grant_id]

    def remember(self, grant_id, tree):
        self.snapshots[grant_id] = tree
        self.snapshots.move_to_end(grant_id)
        while len(self.snapshots) > 1 and (len(self.snapshots) > MAX_SNAPSHOTS or self.stored() > MAX_STORED):
            self.snapshots.popitem(last=False)

    def stored(self):
        return sum(len(tree.order) + len(tree.action_ids) for tree in self.snapshots.values())

    def receive(self, device, message):
        entry = self.waiters.get(message.get("request_id"))
        if entry and entry[0] == device["id"] and not entry[1].done():
            entry[1].set_result(message)


def elements_router(runtime, hub):
    from .screen_element_routes import elements_router as build_router
    return build_router(runtime, hub)
