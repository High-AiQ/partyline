"""Side-effect-free workflow preview against one uncached live observation."""

from fastapi import HTTPException

from .screen_element_state import CAPTURE_SECONDS
from .screen_workflow_evidence import authorized_window
from .screen_tree import Snapshot
from .screen_tree_ids import IdSpace
from .screen_workflow_evidence import above, matches, verdict
from .screen_eval import audit_call


async def observe(service, principal, conv_id, grant_id):
    grant, device = authorized_window(service.hub, principal, grant_id, conv_id)
    audit_call(service.hub, principal, grant, "screen_workflow_read")
    elements = service.hub.elements
    async with elements.locked(grant_id):
        authorized_window(service.hub, principal, grant_id, conv_id)
        tree = Snapshot(None, elements.clock(), IdSpace())
        tree.workflow_read = True
        tree.event_version = elements.change_versions.get(grant_id, 0)
        result = await elements.capture_parts(
            principal, grant, device, tree, elements.clock() + CAPTURE_SECONDS
        )
        if isinstance(result, dict) or tree.cursor or tree.note or not tree.order:
            raise HTTPException(409, "preview requires a complete live observation")
        if await elements.capture_status(principal, grant, device, tree):
            raise HTTPException(409, "the window changed during preview; take another preview")
        authorized_window(service.hub, principal, grant_id, conv_id)
        return tree


def target_report(tree, target):
    if target is None:
        return {"state": "not_required", "match_count": 0,
                "ambiguous": False, "multiply_matched": False}
    scope_ids = None
    if target.within:
        scopes = [node for node in tree.nodes.values() if matches(node, target.within)]
        if len(scopes) != 1:
            count = len(scopes)
            return {"state": "ambiguous" if count > 1 else "missing", "match_count": count,
                    "ambiguous": count > 1, "multiply_matched": False}
        scope_ids = {node.id for node in scopes}
        candidates = [node for node in tree.nodes.values()
                      if matches(node, target) and scope_ids.intersection(above(tree, node.id)[1:])]
    else:
        candidates = [node for node in tree.nodes.values() if matches(node, target)]
    count = len(candidates)
    if target.ordinal is not None:
        if count == target.match_count:
            state, ambiguous = "resolved", False
        else:
            state, ambiguous = (("missing", False) if count == 0 else ("ambiguous", count > 1))
    else:
        state, ambiguous = (("missing", False) if count == 0 else
                            ("multiply_matched", False) if count > 1 else ("resolved", False))
    return {"state": state, "match_count": count, "ambiguous": ambiguous,
            "multiply_matched": count > 1}


def precondition_report(tree, check, step_target):
    check_target = step_target if check.target == "step_target" else check.target
    resolution = target_report(tree, check_target)
    result = verdict(tree, check, step_target)
    if resolution["state"] == "missing" and check.check not in ("absent", "present"):
        result = None
    if resolution["state"] == "missing" and check.check == "present":
        state = "resolved"
    elif result is not None and resolution["state"] in ("resolved", "not_required"):
        state = "resolved"
    elif result is True:
        state = "resolved"
    else:
        state = resolution["state"]
        if state in ("resolved", "not_required"):
            state = "unresolved"
    return {**resolution, "state": state, "verdict": result}


def inspect_plan(tree, plan):
    results = []
    for step_id, step in plan:
        target = target_report(tree, step.target)
        checks = [precondition_report(tree, check, step.target) for check in step.preconditions]
        results.append({"step": step_id, **target, "preconditions": checks})
    return results
