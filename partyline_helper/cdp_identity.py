"""A live backend-node proof, independent of unrelated page events."""
import hashlib

from .cdp_transport import CDPError

TARGET_CHANGED = ("target changed or moved since it was read; read it again, or use "
                  "screen_window_snapshot + screen_window_click")


class TargetChanged(CDPError):
    def __init__(self):
        super().__init__(TARGET_CHANGED)


def identity(page, state):
    return (page.epoch, state.get("document_identity"), tuple(state.get("bounds") or ()))


def token(ident, proof):
    return hashlib.blake2b(repr((ident, proof)).encode(), digest_size=16).hexdigest()


def prove(page, node, state):
    """Resolution uses the original backend id; disconnected/replaced documents never pass."""
    proof = node.get("action_identity")
    if (not proof or not proof[1] or len(proof[2]) != 4 or state.get("connected") is not True
            or identity(page, state) != proof):
        raise TargetChanged()


async def reprove(page, node):
    from .cdp_recipes import STATE
    prove(page, node, await page.function(node["backendDOMNodeId"], STATE, proof=True))


def failure(page, exc, error):
    return {"status": "unconfirmed" if page.dispatched else "failed", "source": "cdp",
            "error": error, "revoked_during": not page.live,
            **({"reason": "target_changed"} if isinstance(exc, TargetChanged) else {})}
