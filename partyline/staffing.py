"""Lead-scoped staffing snapshot: preset traits and conservatively matched live processes."""

from __future__ import annotations

from .approval_bubble import pending_approvals
from .compaction_events import compaction_counts
from .hierarchy import descendants, subtree_conversation_ids
from .preset_traits import coerce_preset, coerce_traits, match_preset
from .resource_leases import describe_leases

LIVE = ("starting", "running")


def staffing_report(db, conv_id: str) -> dict:
    presets = [row for row in (coerce_preset(p) for p in db.list_presets()) if row]
    catalog = [
        {
            "id": preset["id"],
            "title": preset["title"],
            "name": preset["name"],
            "adapter": preset["adapter"],
            **coerce_traits(preset),
        }
        for preset in presets
    ]
    processes = []
    lines = []
    matched_any = False
    for line_id in [conv_id, *descendants(db, conv_id)]:
        conv = db.get_conversation(line_id)
        if conv is None:
            continue
        if conv.get("accepted_sha"):
            lines.append({
                "id": line_id,
                "name": conv["name"],
                "accepted_sha": conv["accepted_sha"],
            })
        for att in db.list_attachments(line_id):
            if att["status"] not in LIVE:
                continue
            matched = match_preset(att, presets)
            if matched is not None:
                matched_any = True
            processes.append({
                "line_id": line_id,
                "line": conv["name"],
                "handle": att["name"],
                "adapter": att["adapter"],
                "captain": bool(att.get("is_lead")),
                "matched_preset": None if matched is None else {
                    "id": matched["id"],
                    "name": matched["name"],
                    "title": matched["title"],
                },
                "traits": None if matched is None else coerce_traits(matched),
            })
    return {
        "presets_in_use": matched_any,
        "presets": catalog,
        "processes": processes,
        "lines": lines,
    }


def _free_presets(presets: list[dict], counts: dict[str, int]) -> list[dict]:
    """Presets with capacity left, with a display string for each.

    A worker preset (no ``can_manage``) stays free only while no live
    process matches it — the old, single-instance view. A ``can_manage``
    preset runs one instance per line and is always free, unless it
    declares ``max_instances``: then it stays free while the live count is
    below the cap. The display carries the remaining-seat count when more
    than one seat is left ("astra (2 more)").
    """
    free = []
    for preset in presets:
        traits = coerce_traits(preset)
        count = counts.get(preset["id"], 0)
        max_instances = int(preset.get("max_instances") or 0)
        remaining = None if max_instances == 0 else max_instances - count
        if traits["can_manage"]:
            if remaining is None or remaining > 0:
                display = preset["name"] + (
                    f" ({remaining} more)" if remaining is not None and remaining > 1
                    else "")
                free.append({"name": preset["name"], "traits": traits,
                             "display": display})
        elif count == 0:
            free.append({"name": preset["name"], "traits": traits,
                         "display": preset["name"]})
    return free


def staffing_line(db, conv_id: str, *, runtime=None) -> str:
    """One line for a captain's wake: subtree use and globally free presets.

    Rides every captain wake next to the goal, unconditionally: the endpoint
    is advice a captain has to remember to call, and a captain choosing its
    next sub-line should see the board without asking. Pending human
    approvals across the subtree ride it too, so a captain (at the root, the
    person's own captain) sees a child stopped on a gate without peeking.
    """
    presets = [row for row in (coerce_preset(p) for p in db.list_presets()) if row]
    pending = pending_approvals(db, conv_id, runtime=runtime)
    if not presets and not pending:
        return ""
    in_use: list[str] = []
    matched_counts: dict[str, int] = {}
    subtree = set(subtree_conversation_ids(db, conv_id))
    compacted = compaction_counts(db)
    for conv in db.list_conversations():
        for att in db.list_attachments(conv["id"]):
            if att["status"] not in LIVE:
                continue
            matched = match_preset(att, presets)
            if matched is not None:
                matched_counts[matched["id"]] = matched_counts.get(matched["id"], 0) + 1
            if conv["id"] not in subtree:
                continue
            role = " captain" if att.get("is_lead") else ""
            label = f"{att['name']} «{conv['name']}»{role}"
            compactions = compacted.get(att["id"])
            if compactions:
                label += f" ×{compactions} compactions"
            in_use.append(label)
    free = _free_presets(presets, matched_counts)
    captains = ", ".join(
        entry["display"] for entry in free if entry["traits"]["can_manage"]
    ) or "none"
    workers = ", ".join(
        entry["display"] for entry in free if entry["traits"]["implements"]
    ) or "none"
    busy = "; ".join(in_use) or "nobody"
    parts = [f"in use: {busy}", f"free captains: {captains}", f"free workers: {workers}"]
    leases = describe_leases(db)
    if leases:
        parts.append(leases)
    if pending:
        counted = ", ".join(f"«{name}» {kind}" for name, kind in pending)
        parts.append(f"approvals pending: {len(pending)} ({counted})")
    return "(staffing — " + ". ".join(parts) + ")"
