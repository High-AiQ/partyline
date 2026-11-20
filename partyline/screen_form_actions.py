"""Fill independent known fields through the ordinary checked element-action path."""
from fastapi import HTTPException

from .screen_audit import record_standing_window_access
from .screen_element_actions import ElementAction, after, diffed, perform_element_action
from .screen_eval import audit_call
from .screen_tree import OUT_BYTES
from .screen_tree_answer import size

KEEP = ("reason", "error", "note", "value_changed", "effect", "navigated", "revoked_during", "grant_ended")


def clip(text, limit):
    return text.encode()[:limit].decode(errors="ignore")


def compact(item, result):
    """Keep the outcome needed for partial recovery, not helper markup or repeated input values."""
    answer = {"element_id": clip(item.element_id, 128), "status": result.get("status", "failed")}
    for key in KEEP:
        if key not in result:
            continue
        value = result[key]
        answer[key] = clip(value, 240) if isinstance(value, str) else value
    return answer


def stopped(result):
    return result.get("status") not in ("completed", "no_effect") or any(
        result.get(key) for key in ("navigated", "revoked_during", "grant_ended"))


async def act(runtime, hub, conv_id, body, principal, grant):
    """Attempt each assignment once, stop at the first problem, then do at most one scoped read."""
    from .screen_workflow_learning import read_observation, record_call

    results, completed, acted = [], 0, False
    for item in body.assignments:
        single = ElementAction(element_id=item.element_id, action=item.action,
                               value=item.value, window=grant["id"])
        audit_call(hub, principal, grant, "screen_element_action", len(item.value))
        await record_standing_window_access(runtime, hub, principal, conv_id, "uia_action",
                                            grant["id"], None, "started")
        retained = hub.elements.snapshots.get(grant["id"])
        try:
            outcome = await perform_element_action(runtime, hub, conv_id, single, principal)
        except HTTPException as exc:
            outcome = {"status": "failed", "error": str(exc.detail)}
        if (retained is not None and grant["id"] not in hub.elements.snapshots
                and not stopped(outcome) and len(results) + 1 < len(body.assignments)):
            # Only this group reuses the pre-action proof; after_action still forces later callers to refresh.
            hub.elements.remember(grant["id"], retained)
        status = outcome.get("status", "failed")
        await record_standing_window_access(runtime, hub, principal, conv_id, "uia_action",
                                            grant["id"], None, status)
        tree = hub.elements.fresh(grant["id"])
        observation = read_observation(tree, outcome.get("after"))
        record_call(runtime.db, grant["id"], "screen_element_action",
                    single.model_dump(exclude_none=True), status, observation)
        results.append(compact(item, outcome))
        completed += status in ("completed", "no_effect")
        acted |= status in ("completed", "no_effect", "unconfirmed")
        if stopped(outcome):
            break

    last = results[-1]
    status = ("unconfirmed" if last["status"] == "unconfirmed" else
              "completed" if len(results) == len(body.assignments) and not stopped(last) else
              "partial" if completed else "failed")
    result = {"status": status, "completed": completed, "results": results,
              "remaining": len(body.assignments) - len(results)}
    if status != "completed" and completed:
        result["partial"] = True
    if body.then:
        result["after"] = await after(hub, principal, grant, body.then, result)
        if not body.then.explicit():
            result["after"] = diffed(result["after"])
        if acted and not any(row.get("grant_ended") for row in results):
            tree = hub.elements.snapshots.get(grant["id"])
            hub.elements.action_completed(grant["id"], bool(tree))  # the next ordinary read must be fresh
    # The read already fits the remaining budget; keep pathological helper errors bounded too.
    for key in ("error", "note", "effect"):
        while size(result) > OUT_BYTES and any(isinstance(row.get(key), str) and len(row[key]) > 40
                                               for row in results):
            for row in results:
                if isinstance(row.get(key), str) and len(row[key]) > 40:
                    row[key] = clip(row[key], 40)
    return result
