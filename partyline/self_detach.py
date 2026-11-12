"""A process does not detach itself out of habit.

Workers cannot close anything: the ``close`` capability is a captain's. A
captain closes *other* processes freely, but a captain that detaches itself
whenever it has asked a person a question leaves that person talking to an
empty line, and has to be resumed (and re-briefed, and sometimes compacted)
for every reply. So a captain's own detach is refused unless it names the
person who explicitly asked for it. A captain handover is the other way out,
and the server performs that one itself.

The handle is an assertion, not proof: it makes the detach deliberate and
puts the name in the audit log.
"""

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)

RULE = (
    "a captain detaches itself only when a person explicitly asked it to, or through a captain "
    "handover; being idle, finished or waiting on a person is not a reason. Stay attached. If a "
    "person did ask, repeat the call with ?told_by=<their handle>"
)


def own(principal, att_id: str) -> bool:
    """Whether ``principal`` is the process behind ``att_id``."""
    return principal.kind == "machine" and principal.attachment_id == att_id


def asked_self_detach(db, principal, att_id: str, told_by: str | None) -> bool:
    """True for a self-detach a person asked for; refuse any other self-detach."""
    if not own(principal, att_id):
        return False
    handle = (told_by or "").strip().lstrip("@").lower()
    if not handle or db._exec(
            "SELECT 1 FROM users WHERE lower(handle)=?", (handle,)).fetchone() is None:
        raise HTTPException(403, RULE)
    logger.info("self-detach attachment=%s told_by=%s", att_id, handle)
    return True
