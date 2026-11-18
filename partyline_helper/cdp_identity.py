"""A live backend-node proof, independent of unrelated page events."""
import hashlib

from .cdp_transport import CDPError

TARGET_CHANGED = ("read it again, or use "
                  "screen_window_snapshot + screen_window_click")


class TargetChanged(CDPError):
    def __init__(self, detail="backend node or action token unavailable"):
        super().__init__(f"target changed: {detail}; {TARGET_CHANGED}")


class NotActionable(CDPError):
    """The listed node has no DOM element CDP can drive; nothing changed, so a re-read cannot help."""

    def __init__(self, why, act_on=None):
        self.act_on = act_on
        super().__init__(f"target has no DOM element ({why}); " + (
            f"act on its parent {act_on}" if act_on else
            "act on a parent element, or use screen_window_snapshot + screen_window_click"))


def unactionable(node, dom, unreachable=False):
    """Why CDP cannot act on a read node, or None for an Element target with a live backend node."""
    if not node.get("backendDOMNodeId"):
        return "accessibility-only node"
    if unreachable:
        return "child frame not reachable from this page session"
    if "non_element" in dom:
        return "text node" if dom["non_element"] == 3 else "not an element"
    return None


def identity(page, state):
    return (page.epoch, state.get("document_identity"),
            tuple(round(value) for value in state.get("bounds") or ()))


def token(ident, proof):
    return hashlib.blake2b(repr((ident, proof[:2])).encode(), digest_size=16).hexdigest()


def prove(page, node, state):
    """Prove the original backend node and document, allowing layout movement.

    Bounds (rounded CSS pixels) are observations, not identity. Mouse dispatch takes
    a live hit test from this same node, then its CDP box supplies a main-frame
    viewport point (DOM bounds are frame-relative). Moved nodes pass but covered,
    hidden and offscreen nodes refuse. No cached coordinate authorizes input.
    """
    proof = node.get("action_identity")
    if not proof or not proof[1] or len(proof[2]) != 4:
        raise TargetChanged("read identity unavailable")
    changed = []
    if page.epoch != proof[0]:
        changed.append(f"page epoch {proof[0]} → {page.epoch}")
    if state.get("document_identity") != proof[1]:
        changed.append("document identity changed")
    if state.get("connected") is not True:
        changed.append("connected=false")
    if changed:
        bounds = identity(page, state)[2]
        if bounds != proof[2]:
            changed.append(f"bounds {list(proof[2])} → {list(bounds)}")
        raise TargetChanged(", ".join(changed))


async def reprove(page, node, mouse=False):
    from .cdp_recipes import DISPATCH, STATE
    state = await page.function(node["backendDOMNodeId"], DISPATCH if mouse else STATE, proof=True)
    prove(page, node, state)
    if mouse:
        if not state.get("hit"):
            detail = state.get("reason") or "element is covered or outside the viewport"
            bounds = identity(page, state)[2]
            if bounds != node["action_identity"][2]:
                detail += f"; bounds {list(node['action_identity'][2])} → {list(bounds)}"
            raise CDPError(detail)
        # DOM rectangles/hit tests use the node's own frame. CDP box coordinates
        # include frame offsets and viewport transforms required by mouse input.
        box = await page.call("DOM.getBoxModel", {"backendNodeId": node["backendDOMNodeId"]})
        quad = box["model"]["content"]
        return {"x": sum(quad[::2]) / 4, "y": sum(quad[1::2]) / 4}


def failure(page, exc, error):
    return {"status": "unconfirmed" if page.dispatched else "failed", "source": "cdp",
            "error": error, "revoked_during": not page.live,
            **({"reason": "target_changed"} if isinstance(exc, TargetChanged) else
               {"reason": "not_actionable", "act_on": exc.act_on} if isinstance(exc, NotActionable) else {})}
