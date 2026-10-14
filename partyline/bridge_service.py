"""Opening and closing line bridges: the notices, the pack, the live badges.

Only a person opens a bridge; the server closes one on its own when either
ambassador goes away or either line is archived. Every path funnels through
`close_bridge`, so the notices and the badge refresh happen exactly once.
"""

from fastapi import HTTPException

from . import bridge_store as store
from .bridge_pack import close_line_notice, close_notice, open_line_notice, pack_text
from .mention_relay import post_private


async def _refresh(runtime, bridge: dict) -> None:
    for key in ("a", "b"):
        await runtime.broadcast_attachment(
            bridge[f"{key}_conv_id"], bridge[f"{key}_attachment_id"])


async def open_bridge(runtime, a: dict, b: dict, opened_by: str) -> dict:
    db = runtime.db
    reason = store.refusal(db, a, b)
    if reason is not None:
        raise HTTPException(409, reason)
    bridge = store.create(db, a, b, opened_by)
    views = {key: store.side_view(db, bridge, key) for key in ("a", "b")}
    for mine, theirs in (("a", "b"), ("b", "a")):
        me, peer = views[mine], views[theirs]
        await runtime.post_message(
            me["conv_id"], "system", "system",
            open_line_notice(me["name"], peer["name"], peer["conv_name"], opened_by))
        await post_private(
            runtime, me["conv_id"], "system", "system",
            pack_text(peer["name"], peer["conv_name"]),
            audience=me["attachment_id"], source=(None, me["conv_id"]))
    await _refresh(runtime, bridge)
    return store.view(db, bridge)


async def close_bridge(runtime, bridge: dict, closed_by: str, reason: str) -> bool:
    """Close once. ``closed_by`` is a person's handle or ``system`` with the reason."""
    db = runtime.db
    if not store.mark_closed(db, bridge["id"], closed_by, reason):
        return False
    by = closed_by if closed_by != "system" else reason
    views = {key: store.side_view(db, bridge, key) for key in ("a", "b")}
    for mine, theirs in (("a", "b"), ("b", "a")):
        me, peer = views[mine], views[theirs]
        await runtime.post_message(
            me["conv_id"], "system", "system",
            close_line_notice(me["name"], peer["name"], peer["conv_name"], by))
        att = db.get_attachment(me["attachment_id"])
        if att is not None and att["status"] in store.LIVE:
            await post_private(
                runtime, me["conv_id"], "system", "system",
                close_notice(peer["name"], peer["conv_name"], by),
                audience=me["attachment_id"], source=(None, me["conv_id"]))
    await _refresh(runtime, bridge)
    return True


async def close_for_attachment(runtime, att_id: str, reason: str) -> None:
    """Close on a deliberate stop; a restart (shutdown, reattachment) never does."""
    if getattr(runtime, "stopping", False) or att_id in runtime.reattaching:
        return
    bridge = store.open_bridge_for_attachment(runtime.db, att_id)
    if bridge is not None:
        await close_bridge(runtime, bridge, "system", reason)


async def close_for_line(runtime, conv_id: str, reason: str) -> None:
    bridge = store.open_bridge_for_line(runtime.db, conv_id)
    if bridge is not None:
        await close_bridge(runtime, bridge, "system", reason)


async def reconcile_after_restart(runtime) -> None:
    """Close bridges whose ambassador did not come back from a restart.

    Called once reattachment has finished (and at startup when no plan will run):
    a restart itself never closes a bridge, only a failure to resume does.
    """
    from .reattach_liveness import is_live

    for bridge in store.open_bridges(runtime.db):
        for key in ("a", "b"):
            if not is_live(runtime, bridge[f"{key}_attachment_id"]):
                name = store.side_view(runtime.db, bridge, key)["name"]
                await close_bridge(
                    runtime, bridge, "system",
                    f"ambassador @{name} did not come back after the restart")
                break
