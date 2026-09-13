"""A process that posts through the API and then says the same thing is not two events.

Codex leads used the authenticated helper to ``POST /messages`` on their own
line — a hello, a final report — and then said the same words in their
terminal, which the transcript tail posted again. The rollout held each
message once; the room held it twice. The API copy is stamped with the
process's attachment id, so the tailed twin is recognisable: same process,
same words, moments apart. The tail's copy is the one dropped, because the
API post already routed and already woke whoever it named.
"""

from __future__ import annotations

import time

ECHO_WINDOW_SECONDS = 180.0


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()) == " ".join(b.split())


def is_api_echo(db, att_id: str, conv_id: str, body: str) -> bool:
    """Whether this process already posted these words through the API just now."""
    rows = db._exec(
        "SELECT body, created_at FROM messages WHERE conv_id=? AND source_attachment_id=?"
        " ORDER BY id DESC LIMIT 5",
        (conv_id, att_id),
    ).fetchall()
    horizon = time.time() - ECHO_WINDOW_SECONDS
    return any(row["created_at"] >= horizon and _same(row["body"], body) for row in rows)
