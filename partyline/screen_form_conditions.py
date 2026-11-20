"""Resolve anticipated form dependencies from current controls before one checked action."""
import asyncio
from time import monotonic

from fastapi import HTTPException

from .machine_scope import deny_unless
from .screen_element_actions import action_token
from .screen_eval import audit_call

IMMEDIATE_CHECK_SECONDS = 35  # timeout_ms=0 still permits one ordinary bounded read/probe, but no event wait


def failed(reason, error, condition):
    return {"status": "failed", "reason": reason, "error": error, "condition": condition}


def timeout(condition, error="dependency condition exceeded its deadline"):
    return None, failed("condition_timeout", error, condition), None


async def probe(runtime, hub, conv_id, item, node_id, principal, grant, device):
    """Prove and read one target without spending an action or risking a UIA fallback write."""
    elements = hub.elements
    deny_unless(runtime.db, principal, conv_id, "read")
    audit_call(hub, principal, grant, "screen_element_condition", len(item.value))
    target, busy = await elements.action_target(principal, grant, node_id)
    if target is None:
        return {"status": "failed", "reason": "target_changed" if busy else "unavailable"}
    token = action_token(elements, grant["id"], node_id)
    async with elements.locked(grant["id"]):
        helper, known = elements.locked_target(grant["id"], node_id)
        if not known or helper != target or token != action_token(elements, grant["id"], node_id):
            return {"status": "failed", "reason": "target_changed"}
        message = {"element_id": helper, "action": item.action, "value": item.value}
        if token:
            message["action_token"] = token
        try:
            return await elements.exchange(principal, grant, device, "window_element_condition", **message)
        except (TimeoutError, OSError, RuntimeError):
            return {"status": "failed", "error": "condition probe did not respond"}


def incomplete(tree, reply):
    """Only a complete, quiet CDP subtree can establish scoped uniqueness."""
    if reply.get("elements_unavailable"):
        return reply["elements_unavailable"]
    if tree is None or tree.source != "cdp" or not tree.dependency_complete:
        return "current dependency scope is unavailable"
    if (tree.partial or tree.capture_raced or tree.moved or tree.busy
            or reply.get("change_event_since_snapshot")):
        return "current dependency scope is incomplete or changing"
    return None


def evidence(tree):
    """Existing helper dispatch fields fence this exact scoped observation through input."""
    return {"workflow_source": "cdp", "workflow_document": tree.document,
            "workflow_counter": tree.event_counter, "workflow_dependency": True}


async def resolve(runtime, hub, conv_id, item, principal, grant, device):
    """Return a current unambiguous element id and dispatch evidence, or a pre-input failure."""
    condition = {"name": item.when.name}
    deadline = monotonic() + item.when.timeout_ms / 1000
    io_deadline = deadline + (IMMEDIATE_CHECK_SECONDS if item.when.timeout_ms == 0 else 0)
    scope = {"root": item.when.root, "name": item.when.name, "action": item.action}
    if item.when.control_type:
        scope["control_type"] = item.when.control_type
    try:
        for _ in range(9):  # immediate check plus at most eight change-triggered rechecks
            version = hub.elements.change_versions.get(grant["id"], 0)
            deny_unless(runtime.db, principal, conv_id, "read")
            remaining = io_deadline - monotonic()
            if remaining <= 0:
                return timeout(condition)
            async with asyncio.timeout(remaining):
                reply = await hub.elements.read(principal, None, grant["id"], {
                    "root": item.when.root, "depth": 3, "refresh": True, "include_root": True,
                    "dependency_scope": scope})
            if monotonic() >= io_deadline:
                return timeout(condition)
            tree = hub.elements.snapshots.get(grant["id"])
            if error := incomplete(tree, reply):
                return None, failed("condition_unavailable", error, condition), None
            root = tree.by_helper.get(item.when.root, item.when.root)
            ids = tree.subtree(root) or []
            wanted_type = (item.when.control_type or "").lower()
            matches = []
            for key in ids:
                node = tree.nodes[key]
                if (node.name == item.when.name and (not wanted_type or node.type.lower() == wanted_type)
                        and item.action in node.actions and "hidden" not in node.flags
                        and "off" not in node.flags):
                    matches.append(node)
            if len(matches) > 1:
                failure = failed("condition_ambiguous", "more than one current control matches", condition)
                return None, failure, None
            if matches:
                node = matches[0]
                condition["element_id"] = node.id
                if "disabled" in node.flags or node.cached.get("enabled") is False:
                    condition["error"] = "control is disabled"
                else:
                    remaining = io_deadline - monotonic()
                    if remaining <= 0:
                        return timeout(condition)
                    async with asyncio.timeout(remaining):
                        observed = await probe(runtime, hub, conv_id, item, node.id, principal, grant, device)
                    if monotonic() >= io_deadline:
                        return timeout(condition)
                    current = observed.get("condition", {})
                    if current.get("ready"):
                        return node.id, None, evidence(tree)
                    if current.get("ambiguous"):
                        failure = failed("condition_ambiguous", "requested option is ambiguous", condition)
                        return None, failure, None
                    if observed.get("status") != "completed":
                        if observed.get("reason") != "target_changed":
                            error = observed.get("error", "condition could not be verified")
                            return None, failed("condition_unavailable", error, condition), None
                    condition["error"] = current.get("error", observed.get("error", "target changed"))
            else:
                condition["error"] = "no current actionable control matches"
            remaining = deadline - monotonic()
            if remaining <= 0 or not await hub.elements.wait_changed(grant["id"], version, remaining):
                return timeout(condition, condition.get("error", "condition did not arrive"))
    except TimeoutError:
        return timeout(condition)
    except HTTPException as exc:
        return None, failed("condition_unavailable", str(exc.detail), condition), None
    except (OSError, RuntimeError):
        return None, failed("condition_unavailable", "condition could not be verified", condition), None
    return timeout(condition, "condition kept changing; recheck limit reached")
