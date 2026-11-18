"""Interpret complete screen evidence, preserving helper identity through dispatch."""

from dataclasses import dataclass

from fastapi import HTTPException

from .screen_element_actions import ElementAction, perform_element_action
from .screen_event_scope import above
from .screen_eval import audit_call
from .screen_grants import require_window
from .screen_tree import Snapshot

ROLE_ALIASES = {
    "edit": "textbox",
    "hyperlink": "link",
    "listitem": "option",
    "datagrid": "grid",
    "statictext": "text",
    "alertdialog": "dialog",
    "fileinput": "file_input",
}
CHECK_ROLES = {"file_count_equals": "file_count", "value_equals": "value"}


class StopWorkflow(Exception):
    def __init__(self, reason, state="failed"):
        super().__init__(reason)
        self.state = state


def capability_error(step_id, requirement, source):
    return StopWorkflow(f"{step_id} requires {requirement}, observed source {source or 'unknown'}")


def role(node):
    observed = node.cached.get("semantic_role") or node.type.lower()
    if observed == "window":
        return "dialog" if node.parent else "window"
    return ROLE_ALIASES.get(observed, observed)


def matches(node, target):
    return role(node) == target.role and node.cached.get("name") == target.name and "hidden" not in node.flags


def matching(tree, target):
    scope = None
    if target.within:
        scopes = [node for node in tree.nodes.values() if matches(node, target.within)]
        if len(scopes) > 1:
            return None
        if not scopes:
            return []
        scope = scopes[0].id
    candidates = [
        tree.nodes[key]
        for key in tree.order
        if matches(tree.nodes[key], target) and (scope is None or scope in above(tree, key)[1:])
    ]
    if target.ordinal is not None:
        return [candidates[target.ordinal - 1]] if len(candidates) == target.match_count else None
    return candidates if len(candidates) <= 1 else None


def verdict(tree, check, step_target):
    nodes = matching(tree, step_target if check.target == "step_target" else check.target)
    if nodes is None:
        return None
    if check.check == "absent":
        return not nodes
    if check.check == "present" or not nodes:
        return bool(nodes)
    node = nodes[0]
    if check.check == "notice_text":
        if check.expected == node.cached.get("name"):
            return True
        # Some providers expose an unnamed live region whose text is in its descendants.
        text = [
            tree.nodes[key].cached.get("name")
            for key in tree.subtree(node.id)[1:]
            if (
                role(tree.nodes[key]) == "text"
                and "hidden" not in tree.nodes[key].flags
                and not any(
                    role(tree.nodes[parent]) == "text" for parent in above(tree, key)[1:] if parent != node.id
                )
            )
        ]
        return " ".join(item for item in text if item) == check.expected
    key = CHECK_ROLES[check.check]
    return node.cached[key] == check.expected if key in node.cached else None


def identity(tree):
    if tree.source == "cdp":
        return tree.document
    if tree.source == "uia":
        # The grant proves the HWND. A single web/document root, when exposed,
        # also distinguishes a document replacement from an update to its fields.
        documents = [
            node.helper
            for node in tree.nodes.values()
            if role(node) == "document" and "off" not in node.flags
        ]
        if len(documents) > 1:
            return None
        if tree.document is None:
            return None
        return tree.document, documents[0] if documents else tree.nodes[tree.order[0]].helper
    return None


def require_capabilities(step_id, step, source, device):
    for capability in sorted(step.capabilities, key=lambda item: ("." not in item, item)):
        if capability.split(".")[0] != source or (
            capability == "cdp.set_files" and device.get("chrome_dom", 0) < 2
        ):
            raise capability_error(step_id, capability, source)
    if not device.get("workflow_actions"):
        raise capability_error(step_id, "cancellable workflow actions", source)


@dataclass
class Dispatch:
    run: object
    tree: Snapshot
    node: object

    def fields(self):
        return {
            "workflow_source": self.tree.source,
            "workflow_counter": self.tree.event_counter,
            "workflow_document": self.tree.document,
        }

    def check(self, elements):
        self.run.authorize()
        gid = self.run.grant_id
        if (
            elements.snapshots.get(gid) is not self.tree
            or elements.change_versions.get(gid, 0) != self.tree.event_version
        ):
            raise StopWorkflow("action evidence changed before dispatch")

    def dispatch(self, request_id):
        self.run.require_current()
        self.check(self.run.service.hub.elements)
        self.run.record_dispatch(request_id)


class WindowScreen:
    def __init__(self, hub):
        self.hub = hub

    async def observe(self, run):
        elements = self.hub.elements
        grant, device = run.authorize()
        audit_call(self.hub, run.principal, grant, "screen_workflow_read")
        async with elements.locked(grant["id"]):
            run.authorize()
            previous = elements.fresh(grant["id"])
            if (
                previous
                and getattr(previous, "workflow_run", None) is run.observation_key
                and not previous.partial
                and previous.live_events
                and previous.event_counter is not None
                and await elements.barrier(run.principal, grant, device, previous)
            ):
                run.authorize()
                if previous is elements.fresh(grant["id"]):
                    return previous
            elements.purge(preserve=grant["id"])
            elements.forget(grant["id"])  # a failed capture has no reusable proof
            from .screen_tree_ids import IdSpace

            space = elements.spaces.setdefault(grant["id"], IdSpace())
            space.renew()
            tree = Snapshot(None, elements.clock(), space)
            tree.workflow_read = True
            tree.workflow_run = run.observation_key
            tree.event_version = elements.change_versions.get(grant["id"], 0)
            deadline = elements.clock() + 20
            capture = await elements.capture_parts(run.principal, grant, device, tree, deadline)
            run.authorize()
            if isinstance(capture, dict):
                if capture.get("page_dialog"):
                    raise StopWorkflow("interrupted by a dialog", "stopped")
                raise StopWorkflow("screen observation unknown")
            if not tree.order or getattr(tree, "page_state", None):
                raise StopWorkflow("screen observation incomplete or unavailable")
            movement = not tree.partial and await elements.capture_status(run.principal, grant, device, tree)
            run.authorize()
            if movement or tree.event_version != elements.change_versions.get(grant["id"], 0):
                # The waiter may re-read only in response to a new pushed event.
                tree.changed = True
            elements.remember(grant["id"], tree)
            elements.after_action.discard(grant["id"])
            return tree

    async def act(self, run, step, tree, node):
        grant, _ = run.authorize()
        body = ElementAction(
            element_id=node.id,
            action=step.action,
            window=run.grant_id,
            **step.inputs.model_dump(exclude_none=True),
        )
        audit_call(self.hub, run.principal, grant, "screen_workflow_action")
        result = await perform_element_action(
            self.hub.runtime, self.hub, run.conv_id, body, run.principal, Dispatch(run, tree, node)
        )
        if result.get("grant_ended") or result.get("revoked_during"):
            raise StopWorkflow("window grant ended", "stopped")
        if result.get("reason") == "workflow_source":
            raise capability_error(run.step_id, tree.source, result.get("source"))
        if result.get("status") not in ("completed", "no_effect"):
            if result.get("error") == "secure desktop active":
                raise StopWorkflow("secure desktop interrupted the workflow", "stopped")
            raise StopWorkflow("helper did not confirm the action")
        if result.get("navigated"):
            raise StopWorkflow("document changed during the workflow")
        if result.get("source", tree.source) != tree.source:
            raise StopWorkflow("screen source changed during the workflow")
        return result["status"]


def authorized_window(hub, principal, grant_id, conv_id):
    grant, device = require_window(hub, principal, grant_id)
    if grant["id"] != grant_id:
        raise HTTPException(403, "use the exact existing window grant ID")
    if principal.kind == "user" and grant["conv_id"] != conv_id:
        from .screen_grants import window_line_ids

        if grant["conv_id"] not in window_line_ids(hub.runtime.db, conv_id):
            raise HTTPException(403, "window grant does not reach this line")
    return grant, device
