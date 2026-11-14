"""What a line and its processes are told when a window grant starts or ends, and at attach time."""
import json

from .mention_relay import post_private


def clean(text):
    return " ".join(str(text).split())


def usage(grant_id, title, computer, shared_by):
    window = json.dumps(grant_id, ensure_ascii=False)
    return (f"Window access granted: {shared_by} shared «{clean(title)}» (window={window}) with this line "
            f"on {clean(computer)}.\n"
            f"Use screen_elements(window={window}) for a summary, then find, ls, or text to locate "
            "content. Use element ids with screen_element_action "
            "(extras(op=\"screen_element_action\", args) if unlisted) to act; page long results "
            "with offset/next_offset and refresh after page changes because ids may become stale. "
            "Every process on this line can use this window; actions run one at a time.")


def live_processes(db, conv_id):
    return [att for att in db.list_attachments(conv_id) if att["status"] in ("starting", "running")]


def line_window_text(db, conv_id):
    """The windows shared with a line right now, for a process that just attached or was re-briefed."""
    from .screen_grants import GRANTS

    if not hasattr(db, "_exec"):
        return ""
    rows = db._exec(GRANTS + " AND g.conv_id=? ORDER BY g.title", (conv_id,)).fetchall()
    if not rows:
        return ""
    parts = [f"«{clean(row['title'])}» (window={json.dumps(row['id'])}) on {clean(row['device_name'])}"
             for row in rows]
    return ("Windows a person shared with this line (any process here may use them): " + "; ".join(parts) +
            ". Read with screen_elements(window=...), act with screen_element_action.")


async def announce(runtime, entry, grant_id, reason=None):
    """One brief line message, and the private terminal notice for every live process on the line."""
    conv_id = entry["conv_id"]
    line = runtime.db.get_conversation(conv_id)
    if not line or line.get("archived_at"):
        return  # an archived line has no processes to tell
    title = clean(entry["title"])
    window = json.dumps(grant_id, ensure_ascii=False)
    text = (f"Window «{title}» (window={window}) is no longer shared with this line: {reason}."
            if reason else usage(grant_id, title, entry["device_name"], entry["shared_by"]))
    for att in live_processes(runtime.db, conv_id):
        await post_private(runtime, conv_id, "system", "system", f"@{att['name']} {text}",
                           audience=att["id"], private=True)
    await runtime.post_message(
        conv_id, "system", "system",
        f"🪟 «{title}» is no longer shared with this line: {reason}" if reason
        else f"🪟 {entry['shared_by']} shared «{title}» with this line")
