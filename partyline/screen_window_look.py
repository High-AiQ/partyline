"""One window look: image and numbered state from one helper capture generation."""
from fastapi import HTTPException

from .screen_grants import require_window, resolve_window
from .screen_look_data import line
from .screen_tree import Snapshot
from .screen_tree_ids import IdSpace
from .screen_window_snapshot import image_tokens
from .screen_window_marks import USE

STALE = "stale mark; take a fresh screen_window_look"


class WindowLooks:
    def __init__(self, hub):
        self.hub, self.latest = hub, {}

    def end(self, grant_id):
        self.latest.pop(grant_id, None)

    async def take(self, principal, store, window, detail="thumb", query=None):
        grant, device = resolve_window(self.hub, principal, window)
        gid, elements = grant["id"], self.hub.elements
        if device.get("windows", 0) < 5:
            raise HTTPException(409, "update the Partyline helper to use screen_window_look")
        fit = {"edge": 1000, "pixels": 700_000} if detail == "thumb" else (
            {"edge": 1600, "pixels": 2_560_000} if detail == "slim" else None)
        async with elements.locked(gid):
            self.latest.pop(gid, None)
            elements.forget(gid)
            version = elements.change_versions.get(gid, 0)
            try:
                answer = await elements.exchange(principal, grant, device, "look_window", overlay=True,
                                                 fit=fit, query=query, wait=70)
            except (TimeoutError, OSError, RuntimeError) as exc:
                raise HTTPException(409, "the computer did not finish the look") from exc
            capture = answer.get("look", {})
            if not answer.get("ok") or not capture.get("generation") or not answer.get("snapshot_id"):
                raise HTTPException(409, str(answer.get("error") or "look capture unavailable")[:300])
            space = elements.spaces.setdefault(gid, IdSpace())
            space.renew()
            tree = Snapshot(capture.get("snapshot_id"), elements.clock(), space)
            tree.add(capture.get("elements", []))
            tree.scope = {"look": True}  # bounded box state, never reuse it as a full text read
            tree.event_version, tree.event_counter = version, capture.get("captured_event_counter")
            tree.source = capture.get("source", "uia")
            tree.look_generation = capture["generation"]
            result = await self.hub.snapshots.keep(store, principal, grant, answer, detail)
            marks, lines = [], []
            for mark in answer.get("marks", []):
                node = tree.nodes.get(tree.by_helper.get(mark["id"]))
                if node is None:
                    raise HTTPException(502, "look boxes and elements disagree; "
                                        "take a fresh screen_window_look")
                marks.append({"n": mark["n"], "id": node.id, "box": mark["box"]})
                lines.append(line(mark["n"], node))
            if "snapshot" not in result:
                raise HTTPException(409, "look geometry unavailable; take a fresh screen_window_look")
            require_window(self.hub, principal, gid)
            elements.remember(gid, tree)
            elements.after_action.discard(gid)
            self.latest[gid] = {"by": principal.name, "tree": tree,
                                "generation": capture["generation"], "snapshot": result["snapshot"],
                                "marks": {mark["n"]: mark for mark in marks}}
            result.update(coordinates=USE, image_mime=answer["mime"], generation=capture["generation"],
                          marks=marks, lines=lines,
                          image_tokens=image_tokens(result["width"], result["height"]))
            if capture.get("changing"):
                result["changing"] = "window changed during capture; element state may lag the image"
            if capture.get("truncated"):
                result["marks_note"] = "truncated to at most 80 boxes; narrow query for more matches"
            return result

    def target(self, principal, grant, number):
        gid = grant["id"]
        look = self.latest.get(gid)
        if not look or look["by"] != principal.name or number not in look["marks"]:
            raise HTTPException(409, STALE)
        mark = look["marks"][number]
        return look, mark, look["tree"].nodes[mark["id"]]


async def mark_action(runtime, hub, store, conv_id, body, request):
    from .auth_guard import request_principal
    from .screen_element_actions import after, diffed, element_action
    from .screen_window_click import WindowClick, point_operation

    principal = request_principal(request)
    grant, _ = resolve_window(hub, principal, body.window)
    look, mark, node = hub.snapshots.looks.target(principal, grant, body.mark)
    if body.action in node.actions:
        return await element_action(runtime, hub, conv_id, body.model_copy(update={
            "element_id": node.helper}), request)
    if body.action not in ("invoke", "click"):
        raise HTTPException(409, "the marked element does not offer that action")
    # Validate normal parameter rules; force never bypasses a point guard.
    try:
        body.parameters()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    left, top, right, bottom = mark["box"]
    click = WindowClick(window=grant["id"], snapshot=look["snapshot"],
                        x=(left + right) // 2, y=(top + bottom) // 2)
    result = await point_operation(runtime, hub, store, conv_id, click, request,
                                   mark=body.mark, generation=look["generation"])
    if body.then and body.then.reads() and result.get("status") in ("completed", "no_effect"):
        result["after"] = await after(hub, principal, grant, body.then, result)
        if not body.then.explicit():
            result["after"] = diffed(result["after"])
    return result
