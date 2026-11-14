"""What a line and its processes are told when a window grant starts or ends, and at attach time."""
import json

from .mention_relay import post_private
from .hierarchy import descendants


def clean(text):
    return " ".join(str(text).split())


def usage(grant_id, title, computer, shared_by, line_name=None):
    window = json.dumps(grant_id, ensure_ascii=False)
    target = (f"«{clean(line_name)}»; inherited and usable from this subline" if line_name
              else "this line and its sublines")
    return (f"Window access granted: {shared_by} shared «{clean(title)}» (window={window}) with {target} "
            f"on {clean(computer)}.\n"
            f"Use screen_elements(window={window}) for a summary, then find, ls, or text to locate "
            "content. Use element ids with screen_element_action "
            "(extras(op=\"screen_element_action\", args) if unlisted) to act; page long results "
            "with offset/next_offset and refresh after page changes because ids may become stale. "
            "Commit a field with press key=enter (also tab/escape); prefer invoke on submit buttons. "
            "Every process on this line and its sublines can use this window; actions run one at a time. "
            "UIA changes "
            "invalidate snapshots; pass refresh=true for a fresh read.\n"
            "Read elements first, and the deltas after each action. Take a screenshot "
            f"(extras(op=\"screen_window_snapshot\", args={{\"window\": {window}}})) when layout or "
            "visuals matter, or elements do not explain what is on screen; slim is the usual size.")


def live_processes(db, conv_id):
    return [att for att in db.list_attachments(conv_id) if att["status"] in ("starting", "running")]


def line_window_text(db, conv_id):
    """The windows shared with a line right now, for a process that just attached or was re-briefed."""
    from .screen_grants import line_grants

    if not hasattr(db, "_exec"):
        return ""
    rows = sorted(line_grants(db, conv_id), key=lambda row: row["title"])
    if not rows:
        return ""
    parts = [f"«{clean(row['title'])}» (window={json.dumps(row['id'])}) on {clean(row['device_name'])}" +
             (f" — inherited from «{clean(row['line_name'])}»" if row["conv_id"] != conv_id else "")
             for row in rows]
    return ("Windows shared with this line or inherited (any process here may use them): " +
            "; ".join(parts) +
            ". Read with screen_elements(window=...), act with screen_element_action; a screenshot "
            "(screen_window_snapshot) is for layout or visuals only.")


async def announce(runtime, entry, grant_id, reason=None):
    """One brief line message, and private terminal notices throughout its live subtree."""
    conv_id = entry["conv_id"]
    line = runtime.db.get_conversation(conv_id)
    if not line or line.get("archived_at"):
        return  # an archived line has no processes to tell
    title = clean(entry["title"])
    window = json.dumps(grant_id, ensure_ascii=False)
    for target in (conv_id, *descendants(runtime.db, conv_id, include_archived=False)):
        inherited = target != conv_id
        origin = f" (inherited from «{clean(line['name'])}»)" if inherited else ""
        text = (f"Window «{title}» (window={window}) is no longer shared with this line{origin}: {reason}."
                if reason else usage(grant_id, title, entry["device_name"], entry["shared_by"],
                                     line["name"] if inherited else None))
        for att in live_processes(runtime.db, target):
            await post_private(runtime, target, "system", "system", f"@{att['name']} {text}",
                               audience=att["id"], private=True)
    await runtime.post_message(
        conv_id, "system", "system",
        f"🪟 «{title}» is no longer shared with this line: {reason}" if reason
        else f"🪟 {entry['shared_by']} shared «{title}» with this line")
