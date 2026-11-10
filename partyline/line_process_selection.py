"""Select live processes and identify interrupted turns for line operations."""

from .hierarchy import descendants


def live_attachments(db, conv_id: str, include_children: bool) -> list[dict]:
    line_ids = [conv_id, *descendants(db, conv_id)] if include_children else [conv_id]
    return [att for line_id in line_ids for att in db.list_attachments(line_id)
            if att["status"] in ("starting", "running")]


def mid_turn_blocker(live: list[dict], presence) -> dict | None:
    if presence is None:
        return None
    working = [att for att in live if presence.is_working(att["id"])]
    if not working:
        return None
    names = ", ".join("@" + att["name"] for att in working)
    return {"code": "process_mid_turn",
            "message": f"processes mid-turn: {names}; wait for them to finish before "
                       "using stop_processes=true"}
