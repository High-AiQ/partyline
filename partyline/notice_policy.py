"""Which system notices a process is pasted, and which only people read.

A system notice is *needs-action* when the process that would read it may have to do, stop,
decide or learn something it cannot know otherwise, and *informational* when it only records
what already happened: a restart that finished, a wait that was declared, a worktree the
process itself asked for, a person's passing reaction. People read every notice in the line
and the UI; this rule only decides what is pasted into a process's turn, where each line
costs tokens on every later turn.

Unknown notices are needs-action. A new system notice is delivered until someone reads it
and adds it here, because wrongly hiding an instruction costs more than a stale line.
"""

from __future__ import annotations

import re

# Each entry: (name, body pattern, True when the notice must have no audience).
# A notice addressed to one process (``audience_attachment_id``) is the server speaking
# to that process; only the entries marked here may be dropped from such a copy.
INFORMATIONAL = (
    ("wait declared", r"^⏳ waiting, not stalled: ", False),
    # ❌ is the one reaction that disagrees; the rest only agree or watch, and the reacted
    # message shows them to a process that reads it (read_messages).
    ("reaction", r"^☺ \S+ reacted (?!❌)\S+ to your «", False),
    ("process resumed or restarted", r"^@\S+ (resumed with full context|restarted fresh) · session ", True),
    ("process ready after restart", r"^☏ @\S+ is ready after restart; advancing to the next process$", True),
    ("process already live", r"^☏ @\S+ is already live on line '.*'; treating it as ready", True),
    ("process replaced (public copy)", r"^↻ @\S+ replaced with a fresh instance \(by @\S+\)", True),
    ("transcript found", r"^\S+: transcript found after \d+s — the line is reachable again\.$", True),
    ("review worktree", r"^☏ review worktree: ", True),
    ("scratch worktree", r"^⚒ scratch worktree( dropped by)?", True),
    ("storage cleared", r"^storage cleared by @", True),
    ("line renamed or restored", r"^☏ line (renamed|restored from the archive)", True),
    ("worktree saved", r"^☏ worktree changes saved to ", True),
    ("memory limit set", r"^Memory limit for \S+ set to ", True),
    ("reattachment declined", r"^☏ @\S+ declined process reattachment after restart$", True),
    ("window shared", r"^🪟 .* shared «.*» with @", True),
)
_COMPILED = tuple((name, re.compile(pattern), public) for name, pattern, public in INFORMATIONAL)


def classify(message: dict) -> str:
    """``"informational"`` or ``"needs-action"`` for one stored message."""
    if message.get("sender_type") != "system":
        return "needs-action"
    body = message.get("body") or ""
    private = bool(message.get("audience_attachment_id"))
    for _name, pattern, public_only in _COMPILED:
        if pattern.search(body) and not (public_only and private):
            return "informational"
    return "needs-action"


def is_informational(message: dict) -> bool:
    return classify(message) == "informational"


def digest_candidates(db, conv_id: str, after_id: int, name: str, att_id: str) -> list[dict]:
    """The messages a process is pasted: everything unseen except informational notices."""
    return [message for message in db.messages_after(conv_id, after_id, name, att_id)
            if not is_informational(message)]
