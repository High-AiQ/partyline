"""Map a captured accessibility tree to proven CDP element records."""
import asyncio
from itertools import islice

from .cdp_dom_nodes import DETAIL
from .cdp_identity import CHILD_FRAME, UNRESOLVED, identity, token, unactionable
from .cdp_recipes import STATE, WIDGET_ROLES, normalize, value
from .cdp_transport import CDPError

MAP_CONCURRENCY = 16


async def map_nodes(page, nodes, ids, epoch, index):
    elements = []
    pending = iter(nodes[index:index + 2000])
    while batch := list(islice(pending, MAP_CONCURRENCY)):
        frames = {}
        for node in batch:
            ident = ids[node["nodeId"]]
            above = page.ax_frames.get(ids.get(node.get("parentId")))
            frames[ident] = page.ax_frames[ident] = node.get("frameId") or above
        states = await asyncio.gather(*(
            _read_state(page, node, frames[ids[node["nodeId"]]]) for node in batch),
            return_exceptions=True)
        _raise_first(states)
        details = await asyncio.gather(*(
            _read_detail(page, node, state[0], state[1])
            for node, state in zip(batch, states, strict=True)), return_exceptions=True)
        _raise_first(details)
        for node, state, detail in zip(batch, states, details, strict=True):
            item = _map_node(page, node, ids, epoch, state[0], state[1], detail)
            if item is not None:
                elements.append(item)
    return elements


def _raise_first(results):
    error = next((item for item in results if isinstance(item, BaseException)), None)
    if error:
        raise error


async def _read_state(page, node, frame):
    if not node.get("backendDOMNodeId"):
        return {}, None
    try:
        return await page.function(node["backendDOMNodeId"], STATE, release=False), None
    except CDPError as exc:
        if not getattr(exc, "unresolved", False):
            raise
        page.guard()  # revocation or document loss keeps its own refusal
        reason = CHILD_FRAME if frame and page.main_frame and frame != page.main_frame else UNRESOLVED
        return {}, reason


async def _read_detail(page, node, dom, unreachable):
    named = value(node.get("name")) or dom.get("aria_label") or dom.get("title")
    if (unreachable or not node.get("backendDOMNodeId") or node.get("file_input_discovered")
            or not (node.get("dom_discovered") or not named and (dom.get("focusable")
                 or dom.get("role") in WIDGET_ROLES | {"gridcell"}))):
        return {}
    return await page.function(node["backendDOMNodeId"], DETAIL, release=False)


def _map_node(page, node, ids, epoch, dom, unreachable, detail):
    ident = ids[node["nodeId"]]
    dom.update(detail)
    # AX can expose zero-size controls activated through their visible labels.
    if node.get("dom_discovered") and dom.get("hidden"):
        return None
    item = normalize(node, ident, ids.get(node.get("parentId")), dom)
    if page.epoch != epoch:
        return item  # don't seed the new document's action cache from an older AX capture
    proof = identity(page, dom)
    item["action_token"] = token(ident, proof)
    parent = item["parent"]
    page.parents[ident] = parent
    extra = {}
    if why := unactionable(node, dom, unreachable):
        above = parent
        for _ in range(64):  # the parent chain is already in this read
            if above is None or above in page.actionable:
                break
            above = page.parents.get(above)
        item.update(actionable=False, why=why)
        if above in page.actionable:
            item["act_on"] = above
        extra = {"not_actionable": why, "act_on": item.get("act_on")}
    else:
        page.actionable.add(ident)
    # Reuse the node mapping, but always prove the live target before input.
    page.nodes[ident] = {**node, "action_identity": proof, "action_token": item["action_token"], **extra}
    return item
