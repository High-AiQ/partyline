"""The one server-side rule hiding reaction notices from human clients.

A reaction on a process's message is stored as a system copy addressed to
that process alone (``audience_attachment_id``), so it rides that process's
digest: the reaction may be a person's whole answer, and the process must
read it. Humans already see the reaction itself on the message and in its
reactions payload, so for them the copy is repeated speech — and before the
fix it leaked into their transcript. The rule: a system copy that carries an
audience AND has the reaction-notice body is never sent to a human client,
neither in the transcript query nor in the WebSocket fan-out, and the
frontend needs no knowledge of it. Line-bridge traffic (rows carrying
``bridge_id``) is hidden the same way and more thoroughly: from every
transcript read and every fan-out, and from every process's digest except the
copy's addressee (``BRIDGE_DIGEST_CLAUSE``); a person reads it only through
the bridge's audit log. A task process's mention of its root captain is hidden from people on the root
line the same way (``task_private``), while the captain's digest still carries it.

Line-bridge traffic has two rows. The ambassador's own message (``bridge_id``, no
audience) is said on this line, so people see it in the chat, marked as having
crossed the bridge. The copy delivered to the counterpart (``bridge_id`` AND an
audience) is the bridge's business: people never see it, and only its addressee's
digest carries it (``BRIDGE_DIGEST_CLAUSE``). Processes on the ambassador's own
line never see either row through their digest, so no process is delivered twice.
Other private copies (cross-line relays,
return-path notices, captain-pack riders) stay human-visible: they carry
operational context, not an acknowledgement the human already sees, so this
rule does not claim them.
"""

import re

# Both spellings describe the body reaction_routes._wake_process builds:
# "☺ <handle> reacted <emoji> to your «<snippet>»". The LIKE form filters
# stored history in SQL; the regex decides live WebSocket fan-out.
REACTION_NOTICE_LIKE = "☺ % reacted % to your «%"
_REACTION_NOTICE_BODY = re.compile(r"^☺ \S+ reacted \S+ to your «")


def is_reaction_notice(message: dict) -> bool:
    """Whether this row is a reaction notice addressed to one process."""
    return (
        message.get("sender_type") == "system"
        and bool(message.get("audience_attachment_id"))
        and bool(_REACTION_NOTICE_BODY.match(message.get("body") or ""))
    )


BRIDGE_DIGEST_CLAUSE = " AND (m.bridge_id IS NULL OR m.audience_attachment_id IS NOT NULL)"


def bridge_copy_sql(alias: str = "m") -> str:
    """SQL condition: a bridge row delivered to the counterpart, which people never read."""
    return f"({alias}.bridge_id IS NOT NULL AND {alias}.audience_attachment_id IS NOT NULL)"


def is_bridge_copy(message: dict) -> bool:
    return bool(message.get("bridge_id")) and bool(message.get("audience_attachment_id"))


def hide_reaction_notices_clause(alias: str = "m") -> str:
    """SQL fragment excluding reaction notices and bridge copies from transcript reads."""
    return (
        f" AND NOT {bridge_copy_sql(alias)} AND {alias}.task_private=0"
        f" AND NOT ({alias}.sender_type='system'"
        f" AND {alias}.audience_attachment_id IS NOT NULL"
        f" AND {alias}.body LIKE ?)"
    )
