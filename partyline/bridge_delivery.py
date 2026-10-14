"""Speaking over a bridge: ``@[bridge]<peer>`` in an ambassador's message.

The ordinary mention regex does not match ``@[``, so the two forms never
collide. Stamping happens before the sender's message is broadcast (so people
never see it) and delivery happens when routing sees the stamp. A copy that
arrives over the bridge is foreign-sourced and carries its own audience, so it
is never stamped, relayed or answered on its own: it moves only when its
recipient writes a fresh ``@[bridge]`` message.
"""

import re
import unicodedata
import time

from .bridge_store import (
    WINDOW_LIMIT, WINDOW_SECONDS, open_bridge_for_attachment, side, side_view,
    sent_in_window,
)
from .message_queries import select_message_by_id
from .mention_relay import is_foreign, post_private, speaker_attachment

BRIDGE_RE = re.compile(r"(?<![A-Za-z0-9_])@\[bridge\]([A-Za-z0-9][A-Za-z0-9_.-]*)", re.I)
PAUSED = "⇄ bridge paused: rate limit"


CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


def bridge_names(body: str) -> set[str]:
    """Handles named with ``@[bridge]``, trailing sentence punctuation tolerated.

    Quoted code is not speech, and copied text can carry invisible formatting
    characters, so both are cleared the way ordinary mentions clear them.
    """
    text = "".join(c for c in CODE_RE.sub(" ", body or "") if unicodedata.category(c) != "Cf")
    names: set[str] = set()
    for name in BRIDGE_RE.findall(text):
        names |= {name.lower(), name.rstrip(".-_").lower()}
    return names - {""}


def _ambassador(db, conv_id: str, message: dict) -> tuple[dict, dict] | None:
    """(speaker, bridge) when an agent message comes from an open bridge's ambassador."""
    if message.get("sender_type") != "agent" or message.get("audience_attachment_id"):
        return None
    if is_foreign(message):
        return None
    speaker = speaker_attachment(db, conv_id, message)
    if speaker is None:
        return None
    bridge = open_bridge_for_attachment(db, speaker["id"])
    return (speaker, bridge) if bridge else None


def stamp_outbound(db, conv_id: str, message: dict) -> dict:
    """Mark an ambassador's message that addresses its counterpart; nothing else."""
    names = bridge_names(message.get("body", ""))
    if not names:
        return message
    found = _ambassador(db, conv_id, message)
    if found is None:
        return message
    speaker, bridge = found
    peer = side_view(db, bridge, side(bridge, speaker["id"])[1])
    if peer["name"].lower() not in names:
        return message
    db._exec("UPDATE messages SET bridge_id=? WHERE id=?", (bridge["id"], message["id"]))
    return {**message, "bridge_id": bridge["id"]}


def speaks_over_bridge(db, att_id: str, body: str) -> bool:
    """True when this ambassador's words address its counterpart across its open bridge."""
    names = bridge_names(body)
    bridge = open_bridge_for_attachment(db, att_id) if names else None
    if bridge is None:
        return False
    peer = side_view(db, bridge, side(bridge, att_id)[1])
    return peer["name"].lower() in names


async def _tell(runtime, conv_id: str, att_id: str, text: str) -> None:
    await post_private(runtime, conv_id, "system", "system", text, audience=att_id,
                       source=(None, conv_id), route=False)


async def route_bridge(runtime, conv_id: str, message: dict) -> bool:
    """Handle bridge speech in a routed message. True when it was a bridge delivery."""
    db = runtime.db
    if message.get("bridge_id") and not message.get("audience_attachment_id"):
        return await _deliver(runtime, conv_id, message)
    if (message.get("sender_type") != "agent" or message.get("audience_attachment_id")
            or is_foreign(message) or not bridge_names(message.get("body", ""))):
        return False
    speaker = speaker_attachment(db, conv_id, message)
    if speaker is None:
        return False
    bridge = open_bridge_for_attachment(db, speaker["id"])
    if bridge is None:
        await _tell(runtime, conv_id, speaker["id"],
                    "⚠ no bridge: this line has no open bridge for you, so nothing crossed")
    else:
        peer = side_view(db, bridge, side(bridge, speaker["id"])[1])
        await _tell(runtime, conv_id, speaker["id"],
                    f"⚠ nothing crossed: your counterpart is @{peer['name']} on "
                    f"«{peer['conv_name']}» — address it as @[bridge]{peer['name']}")
    return False


async def _deliver(runtime, conv_id: str, message: dict) -> bool:
    db = runtime.db
    speaker = speaker_attachment(db, conv_id, message)
    bridge = open_bridge_for_attachment(db, speaker["id"]) if speaker else None
    if bridge is None or bridge["id"] != message["bridge_id"]:
        if speaker:
            await _tell(runtime, conv_id, speaker["id"],
                        "⚠ this bridge is closed: nothing crossed")
        return True
    mine, theirs = side(bridge, speaker["id"])
    peer = side_view(db, bridge, theirs)
    target = db.get_attachment(peer["attachment_id"])
    now = time.time()
    if sent_in_window(db, bridge["id"], speaker["id"], now) >= WINDOW_LIMIT:
        await _tell(runtime, conv_id, speaker["id"],
                    f"⚠ bridge rate limit: {WINDOW_LIMIT} messages per {WINDOW_SECONDS // 60} "
                    "minutes — this one was not delivered; wait before sending more")
        await _pause_once(runtime, bridge, now)
        return True
    if target is None:
        await _tell(runtime, conv_id, speaker["id"],
                    f"⚠ @{peer['name']} is gone — nothing crossed")
        return True
    copy = db.add_message(peer["conv_id"], message["sender"], "agent", message["body"])
    db._exec(
        "UPDATE messages SET source_attachment_id=?, source_conv_id=?,"
        " audience_attachment_id=?, bridge_id=? WHERE id=?",
        (speaker["id"], conv_id, peer["attachment_id"], bridge["id"], copy["id"]),
    )
    copy = select_message_by_id(db._exec, peer["conv_id"], copy["id"])
    await runtime.route_mentions(peer["conv_id"], copy, force=True)
    return True


async def _pause_once(runtime, bridge: dict, now: float) -> None:
    """One visible 'paused' notice per window on each line."""
    db = runtime.db
    for line_id in (bridge["a_conv_id"], bridge["b_conv_id"]):
        seen = db._exec(
            "SELECT 1 FROM messages WHERE conv_id=? AND sender_type='system' AND body=?"
            " AND created_at>?", (line_id, PAUSED, now - WINDOW_SECONDS)).fetchone()
        if seen is None:
            await runtime.post_message(line_id, "system", "system", PAUSED)
