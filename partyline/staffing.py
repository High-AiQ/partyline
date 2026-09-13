"""Lead-scoped staffing snapshot: preset traits and conservatively matched live processes."""

from __future__ import annotations

from .hierarchy import descendants
from .preset_traits import coerce_preset, coerce_traits, match_preset

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
    matched_any = False
    for line_id in [conv_id, *descendants(db, conv_id)]:
        conv = db.get_conversation(line_id)
        if conv is None:
            continue
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
    return {"presets_in_use": matched_any, "presets": catalog, "processes": processes}
