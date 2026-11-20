"""Complete, bounded AX-subtree evidence for one anticipated form dependency."""
import asyncio
import hashlib
import uuid

from .cdp_ax import exposed
from .cdp_page_mapping import map_nodes
from .workflow_dispatch import document

NODE_CAP = 256
BATCH = 16


def incomplete(message):
    return {"elements_unavailable": message, "dependency_complete": False, "scoped": True}


async def subtree(page, root_id):
    root = page.nodes.get(root_id)
    if not root or not root.get("backendDOMNodeId"):
        return incomplete("dependency root changed; read the section again")
    wanted, collected, pending = {root["nodeId"]}, {}, [root["backendDOMNodeId"]]
    while pending:
        batch, pending = pending[:BATCH], pending[BATCH:]
        replies = await asyncio.gather(*(page.call("Accessibility.getPartialAXTree", {
            "backendNodeId": backend, "fetchRelatives": True}) for backend in batch))
        for reply in replies:
            present = {node["nodeId"]: node for node in reply.get("nodes", [])}
            for ident, node in present.items():
                if ident not in wanted or ident in collected:
                    continue
                collected[ident] = node
                for child in node.get("childIds", []):
                    if child in wanted:
                        continue
                    wanted.add(child)
                    if len(wanted) > NODE_CAP:
                        return incomplete("dependency scope exceeds 256 accessibility nodes")
                    backend = present.get(child, {}).get("backendDOMNodeId")
                    if not backend:
                        return incomplete("dependency scope has an unreadable descendant")
                    pending.append(backend)
    if len(collected) != len(wanted):
        return incomplete("dependency scope did not return a complete subtree")
    return list(collected.values())  # discovery order keeps parents before their children


async def snapshot(page, root_id):
    """Read only the root's complete subtree; never silently substitute a full or partial window."""
    before = page.access.event_status()["event_counter"]
    raw = await subtree(page, root_id)
    if isinstance(raw, dict):
        return raw
    epoch = page.epoch
    nodes = exposed(raw)
    ids = {node["nodeId"]: hashlib.blake2b(
        f'{page.access.session.window_grant_id}:{page.identity}:{page.target}:{epoch}:'
        f'{node.get("backendDOMNodeId", node["nodeId"])}'.encode(), digest_size=8).hexdigest()
        for node in nodes}
    try:
        elements = await map_nodes(page, nodes, ids, epoch, 0, NODE_CAP)
    finally:
        if (page.live and page.page_state == "alive" and page.access.grant is page.grant
                and not page.access.gate.revoked.is_set() and not page.page_dialog):
            await page.call("Runtime.releaseObjectGroup", {"objectGroup": "partyline"})
    await page.call("Runtime.evaluate", {"expression": "0", "returnByValue": True})
    result = {"source": "cdp", "action_identity_supported": True, "elements": elements,
              "snapshot_id": uuid.uuid4().hex, "workflow_document": document(page),
              "captured_event_counter": before, "dependency_complete": True, "scoped": True,
              **page.access.event_status()}
    page.access.keep(result, None, scoped=True)
    return result
