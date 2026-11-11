"""Account for proven deliveries while attachment ownership is reserved."""


def confirm_reserved(
    runtime, att_id: str, message_ids: list[int], runtime_owner: str | None, *, boundary: bool = False
) -> bool:
    """Advance only the proven frontier; caller holds the ownership reservation."""
    if not message_ids:
        return False
    adapter = runtime.live.get(att_id)
    metadata = (adapter.att.get("adapter_metadata") or {}) if adapter else {}
    if metadata.get("delivery_proof") == "none-with-reason" and not boundary:
        return False
    attachment = runtime.db.get_attachment(att_id)
    if attachment is None or attachment.get("runtime_owner") != runtime_owner:
        return False
    entry = runtime.uncredited.get(att_id)
    if entry is not None and entry["owner"] != runtime_owner:
        del runtime.uncredited[att_id]
        entry = None
    if entry is None:
        entry = {"owner": runtime_owner, "ids": set(), "confirmed": set()}
        runtime.uncredited[att_id] = entry
    entry.setdefault("confirmed", set())
    ids = set(message_ids)
    entry["ids"].update(ids)
    entry["confirmed"].update(ids)
    entry.get("claim_ids", set()).difference_update(ids)
    unresolved = entry["ids"] - entry["confirmed"]
    frontier = min(unresolved) - 1 if unresolved else max(entry["ids"])
    eligible = entry["confirmed"] & {mid for mid in entry["ids"] if mid <= frontier}
    if eligible and not runtime.db.set_last_seen(att_id, max(eligible), runtime_owner):
        return False
    attachment = runtime.db.get_attachment(att_id)
    high_water = attachment["last_seen"] if attachment is not None else 0
    credited = {mid for mid in entry["confirmed"] if mid <= high_water}
    entry["ids"].difference_update(credited)
    entry["confirmed"].difference_update(credited)
    runtime.db.clear_queued_delivery_ids(att_id, list(credited))
    if not entry["ids"]:
        runtime.uncredited.pop(att_id, None)
        runtime.unclaimed_noticed.discard(att_id)
    return max(message_ids) <= high_water
