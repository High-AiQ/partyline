"""The one server-side rule hiding reaction notices from human clients.

A reaction on a process's message is stored as a system copy addressed to
that process alone (``audience_attachment_id``), so it rides that process's
digest: the reaction may be a person's whole answer, and the process must
read it. Humans already see the reaction itself on the message and in its
reactions payload, so for them the copy is repeated speech — and before the
fix it leaked into their transcript. The rule: a system copy that carries an
audience AND has the reaction-notice body is never sent to a human client,
neither in the transcript query nor in the WebSocket fan-out, and the
frontend needs no knowledge of it. Other private copies (cross-line relays,
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


def hide_reaction_notices_clause(alias: str = "m") -> str:
    """SQL fragment excluding reaction-notice copies from human transcript reads."""
    return (
        f"AND NOT ({alias}.sender_type='system'"
        f" AND {alias}.audience_attachment_id IS NOT NULL"
        f" AND {alias}.body LIKE ?)"
    )
