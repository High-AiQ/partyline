"""Snapshot event barriers, bounded capture and live diagnostics."""
import asyncio

from .screen_event_scope import UNPLACED, EventScope, related
from .screen_timing import phase
from .screen_tree import MAX_NODES, MAX_TREE, STATE_FIELDS, Snapshot

CAPTURE_SECONDS = 20  # bounds work; never establishes that a page finished changing
OLD_ID = 16


def comparable(node):
    return tuple(node.cached.get(key) for key in STATE_FIELDS)


def compare(tree, previous):
    tree.before = set(previous.nodes)
    tree.updated = {key for key in tree.nodes.keys() & previous.nodes.keys()
                    if comparable(tree.nodes[key]) != comparable(previous.nodes[key])}


def verdict(live, cached, ancestors):
    if live.get("enabled") is True and cached.get("enabled") is False:
        return "live enabled, snapshot disabled: stale"
    if live.get("enabled") is False and cached.get("enabled") is True:
        return "live disabled, snapshot enabled: stale"
    disabled = next((item for item in ancestors if item.get("enabled") is False), None)
    if live.get("enabled") is False and disabled:
        return "ancestor " + str(disabled.get("name") or "(unnamed)") + " disabled"
    if live.get("enabled") is False and cached.get("enabled") is False:
        return "live and snapshot agree: Chrome reports disabled (IsEnabled=false; aria=" + str(
            live.get("aria_properties")) + "; STATE_SYSTEM_UNAVAILABLE=" + str(
            live.get("legacy_unavailable")) + ")"
    return "live and snapshot agree: enabled" if live.get("enabled") is True else "live state unavailable"


class ElementState(EventScope):
    async def barrier(self, principal, grant, device, tree):
        if getattr(tree, "event_counter", None) is None:
            return True  # older helpers retain their TTL and pushed-event behavior
        with phase("barrier_ms"):
            status = await self.exchange(principal, grant, device, "read_window_elements", event_status=True)
        return (status.get("events_supported") is True and status.get("subscription_live") is True
                and status.get("event_counter") == tree.event_counter)

    async def capture_status(self, principal, grant, device, tree, top=None):
        """Whether events since the capture began touch what is answered (`top`, else the whole tree)."""
        if getattr(tree, "event_counter", None) is None:
            return False
        if getattr(tree, "sources", False):
            moved, roots = await self.judge(principal, grant, device, tree)
            return moved and (roots is None or any(top is None or related(tree, root, top) for root in roots))
        with phase("barrier_ms"):
            status = await self.exchange(principal, grant, device, "read_window_elements", event_status=True)
        return status.get("event_counter") != tree.event_counter

    async def inspect(self, principal, grant, device, ident):
        tree = self.snapshots.get(grant["id"])
        node = tree.nodes.get(ident) if tree else None
        if node is None:
            return {"error": "unknown element id; read the window first"}
        if getattr(tree, "event_counter", None) is None:
            return {"error": "inspect unavailable; update the helper"}
        result = await self.exchange(principal, grant, device, "read_window_elements", inspect=node.helper)
        if "live" not in result:
            return {"error": result.get("error", "inspect unavailable; update the helper")}
        cached = {key: node.cached.get(key) for key in
                  ("enabled", "name", "value", "toggle", "selected", "expand_state")}
        cached["bounds"] = list(node.bounds) if node.bounds else None
        result.update(cached=cached, snapshot_event_counter=getattr(tree, "event_counter", None),
                      server_change_version=self.change_versions.get(grant["id"], 0),
                      snapshot_change_version=tree.event_version)
        result["event_counter_advanced_since_snapshot"] = (
            result.get("event_counter", tree.event_counter) > tree.event_counter)
        result["verdict"] = verdict(result["live"], cached, result.get("ancestors", []))
        if result.get("source") == "cdp":
            evidence = ",".join(result["live"].get("disabled_provenance", []))
            result["verdict"] = ("CDP live disabled: " + evidence
                                 if result["live"].get("enabled") is False else "CDP live enabled")
        return result

    async def capture(self, principal, grant, device, tree):
        """Recapture only in response to an observed event; deadlines bound churn, not truth.

        Events from placed elements leave the rest of the tree consistent: a second capture that still
        sees them ends the read, naming the busy subtrees instead of failing the whole window.
        """
        deadline = self.clock() + CAPTURE_SECONDS
        raced = confined = False
        for attempt in range(8):  # also bounds providers whose clock or event stream misbehaves
            result = await self.capture_parts(principal, grant, device, tree, deadline)
            if isinstance(result, dict):
                return result
            if getattr(tree, "event_counter", None) is None:
                return tree  # old helpers retain their explicit changed/partial response
            if tree.action_identity:
                tree.capture_raced = tree.changed  # report churn; actions use a live node proof
                return tree
            roots = None
            if tree.sources and not tree.changed:
                moved, roots = await self.judge(principal, grant, device, tree)
                tree.moved = tree.moved or moved
                if not moved or (roots is not None and not roots):
                    tree.capture_raced = raced
                    return tree
            elif not tree.changed and not await self.capture_status(principal, grant, device, tree):
                tree.capture_raced = raced
                return tree
            raced = True
            if roots and (confined or self.clock() >= deadline or attempt == 7):
                tree.busy, tree.capture_raced = frozenset(roots), True
                return tree
            confined = confined or bool(roots)
            if self.clock() >= deadline or attempt == 7:
                tree.note = UNPLACED if tree.sources and roots is None else \
                    "tree inconsistent: events during capture; refresh"
                return tree
            tree.space.renew()
            scope, prior_helpers, action_ids = tree.scope, tree.prior_helpers, tree.action_ids
            tree = Snapshot(None, self.clock(), tree.space)
            tree.scope, tree.prior_helpers, tree.action_ids = scope, prior_helpers, action_ids
            tree.event_version = self.change_versions.get(grant["id"], 0)
        return tree

    async def capture_parts(self, principal, grant, device, tree, deadline):
        """Read the helper's window part by part into `tree`; stop at a cap and keep the cursor."""
        started = tree.snapshot_id is not None
        while True:
            fields = {"cursor": tree.cursor} if tree.cursor else {}
            if tree.scope:
                fields["query_scope"] = tree.scope
            if tree.cursor and tree.sources:
                fields["tolerate_events"] = True  # events are judged by where they came from, at the end
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
            tree.source = response.get("source", "uia")
            tree.action_identity = tree.source == "cdp" and response.get("action_identity_supported") is True
            tree.transport = response.get("transport")
            tree.source_reason = response.get("source_reason")
            tree.page_state = response.get("page_state")
            tree.recovery_hint = response.get("recovery_hint")
            counter = response.get("captured_event_counter")
            if not started:
                tree.event_counter = counter
            tree.sources = response.get("event_sources_supported") is True
            if counter is not None and (counter != getattr(tree, "event_counter", None) or
                                        response.get("event_counter") != counter):
                tree.moved = True
                tree.changed = tree.changed or not tree.sources
            tree.snapshot_id = tree.snapshot_id or response.get("snapshot_id")
            started = True
            tree.scoped = response.get("scoped", False)
            if tree.scope and not tree.scoped:
                tree.scope = None  # legacy helper returns a complete snapshot
                tree.action_ids.clear()
                tree.prior_helpers.clear()
            with phase("snapshot_store_ms"):
                await asyncio.to_thread(tree.add, response.get("elements", []))
            if any(len(str(item.get("id", ""))) > OLD_ID for item in response.get("elements", ())):
                tree.old_helper = True
            tree.cursor = response.get("next_cursor")
            tree.changed = tree.changed or bool(response.get("changed"))
            tree.note = ""
            if response.get("truncated") and not tree.cursor:
                tree.note = ("query result limit; narrow the name/type query" if tree.scoped else
                             "the helper cannot continue reading; update it")
            if len(tree.order) >= MAX_TREE:
                tree.cursor = None
                tree.note = f"the window has more than the {MAX_TREE} elements one snapshot keeps"
            if not tree.cursor or len(tree.order) >= MAX_NODES or self.clock() >= deadline:
                if not tree.cursor:
                    tree.created = self.clock()
                return tree

